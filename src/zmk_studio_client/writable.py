"""The only module in this package that can change a keyboard.

It is a module of its own, rather than three more classes in `__init__.py`, for the
same reason `writes.py` is separate from `reads.py`: the package init is on the read
path, reached by every module that wants a ReadRequest, so anything defined there is
reachable by everything. `WritableKeyboard` is a subclass of `Keyboard` and would sit
naturally beside it - and defining it there would drag `writes` into every read-only
caller's import closure and dissolve the guarantee `connect()` rests on.

So the rule that split the allowlists applies again one floor up, and it generalises:
the guarantee is not a property of the allowlists, it is a property of every module
on the read path. Reaching a write means importing this file by name, in a line a
reviewer can grep for and tests/test_isolation.py can see.

The division of labour between the two classes here:

    WritableKeyboard   a Keyboard that can also open an Edit
    Edit               pending binding changes, and the decision to keep them
"""
from __future__ import annotations

from collections.abc import Mapping

from . import Keyboard, Rpc, model
from ._connect import open_rpc
from . import writes
from ._pb import keymap_pb2

__all__ = ["WritableKeyboard", "Edit", "connect_writable",
           "BindingRejected", "SaveRefused", "EditSettled", "EditAbandoned"]

#: The keyboard's "that worked" for a binding write. Everything else is a refusal.
_BINDING_OK = keymap_pb2.SET_LAYER_BINDING_RESP_OK


class BindingRejected(Exception):
    """The keyboard refused one binding. Nothing was committed."""


class SaveRefused(Exception):
    """The keyboard refused to commit. The pending changes are still pending."""


class EditSettled(Exception):
    """This edit was already saved or discarded, so it cannot be added to."""


class EditAbandoned(Exception):
    """close() found pending changes that were neither saved nor discarded.

    They have been discarded by the time this is raised. It exists because the
    alternative - closing quietly - would let a caller's missing branch decide
    whether a keyboard changed, which is the one outcome `Edit` is built to
    make impossible.
    """


class WritableKeyboard(Keyboard):
    """A keyboard that can be read, and changed.

    Subclassing is right here rather than composition: every read a caller performs
    before or after editing is a real Keyboard read, and nothing about them changes
    because writing is possible. The subclass adds exactly one method.
    """

    def __init__(self, rpc: Rpc) -> None:
        super().__init__(rpc)
        self._edit: Edit | None = None

    def edit(self) -> Edit:
        """Begin changing the keymap. Nothing is sent until a binding is set.

        Loads the behavior table first, which is what makes this refuse on a locked
        keyboard: the table is a read, and a locked keyboard refuses reads. The table
        is also what lets an Edit check a behavior id against the firmware that is
        actually going to receive it. Memoized on the Keyboard, so when the caller
        has already read `behaviors()` this costs nothing.
        """
        self._edit = Edit(self._rpc, self.behaviors())
        return self._edit

    def close(self) -> None:
        """Release the transport, discarding - loudly - any edit left pending.

        Pending bindings live in the keyboard's RAM until save_changes, so a discard
        genuinely undoes them and closing cannot leave a half-written keymap. What it
        could leave is a caller who thinks it saved, so this raises after discarding.

        The connection is closed either way, including when the discard itself fails.
        A raise from here during stack unwinding will chain onto whatever was already
        being raised rather than replace it, so no cause is lost.
        """
        pending = 0
        try:
            if self._edit is not None:
                pending = self._edit._abandon()
        finally:
            self._edit = None
            super().close()
        if pending:
            raise EditAbandoned(
                f"{pending} binding change(s) were pending and neither saved nor "
                f"discarded; they have now been discarded, so the keymap on the "
                f"keyboard is unchanged")


class Edit:
    """Binding changes held in the keyboard's RAM, and what becomes of them.

    `save()` is explicit and has no implicit counterpart. There is no commit on a
    clean exit, no commit in a destructor, nothing that writes flash because a block
    ended: an implicit commit would mean an unrelated exception decides whether the
    keymap changed. The caller asks, or it does not happen.

    One Edit is one decision. After save() or discard() it is settled and refuses
    further bindings, so a caller cannot accidentally reopen a committed batch and
    leave half of a second change pending behind the first one's success.
    """

    def __init__(self, rpc: Rpc, behaviors: Mapping[int, model.Behavior]) -> None:
        self._rpc = rpc
        self._behaviors = behaviors
        self._pending = 0
        self._settled = False

    @property
    def pending(self) -> int:
        """How many bindings are waiting in RAM for a save() that may never come."""
        return self._pending

    def set_binding(self, layer_id: int, position: int, behavior_id: int,
                    param1: int = 0, param2: int = 0) -> None:
        """Queue one binding change. Reversible until save().

        Checks `behavior_id` against the live table before sending. A stale id is
        individually valid and the keyboard will accept it, binding the key to
        whatever that index means in this build - a wrong keymap written in silence,
        which is the failure the remapping exists to prevent. This is the last place
        that can still catch it, and it is cheap because the table is already here.
        """
        self._require_open()
        if behavior_id not in self._behaviors:
            raise BindingRejected(
                f"behavior id {behavior_id} is not one this firmware defines "
                f"(it has {len(self._behaviors)}: "
                f"{sorted(self._behaviors)}). A snapshot's ids must be re-mapped by "
                f"display name against the live table before they are written back.")

        request = writes.set_binding(
            layer_id=layer_id, position=position, behavior_id=behavior_id,
            param1=param1, param2=param2)
        result = self._rpc.call(request).set_layer_binding
        if result != _BINDING_OK:
            raise BindingRejected(
                f"the keyboard rejected layer {layer_id} position {position} -> "
                f"{self._name(behavior_id)}: {_binding_error(result)}")
        self._pending += 1

    def save(self) -> None:
        """Commit every pending binding to the settings partition. Irreversible."""
        self._require_open()
        result = self._rpc.call(writes.save_changes()).save_changes
        if result.WhichOneof("result") != "ok" or not result.ok:
            raise SaveRefused(
                f"the keyboard would not commit the changes: {_save_error(result)}")
        self._settled = True

    def discard(self) -> None:
        """Throw the pending bindings away. The keymap is left as it was."""
        self._require_open()
        self._rpc.call(writes.discard_changes())
        self._settled = True

    # -- internals -------------------------------------------------------------

    def _abandon(self) -> int:
        """Discard on behalf of close(), reporting how much was thrown away.

        Returns 0 when there was nothing to do, so close() stays quiet on the normal
        path and is loud only when a caller forgot to decide.
        """
        if self._settled or not self._pending:
            return 0
        count = self._pending
        self.discard()
        return count

    def _require_open(self) -> None:
        if self._settled:
            raise EditSettled(
                "this edit was already saved or discarded; open another with edit()")

    def _name(self, behavior_id: int) -> str:
        details = self._behaviors.get(behavior_id)
        name = getattr(details, "display_name", "") if details else ""
        return f"{name!r} (id {behavior_id})" if name else f"id {behavior_id}"


def connect_writable() -> WritableKeyboard:
    """Open a keyboard that can be changed.

    The other half of the pair, `zmk_studio_client.connect()` being the read-only one. Two
    functions rather than one with a flag, so the ability to write is named at the
    call site and visible in the type that comes back.
    """
    return WritableKeyboard(open_rpc())


def _binding_error(code: int) -> str:
    try:
        return keymap_pb2.SetLayerBindingResponse.Name(code)
    except ValueError:
        return f"unknown response {code}"


def _save_error(result) -> str:
    if result.WhichOneof("result") == "err":
        try:
            return keymap_pb2.SaveChangesErrorCode.Name(result.err)
        except ValueError:
            return f"unknown error {result.err}"
    return "no result reported"
