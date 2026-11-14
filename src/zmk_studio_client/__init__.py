"""The transport stack: everything between the application and the radio.

Four floors, bottom to top:

    connection.py   bytes              <-> radio      the only untestable code
    wire.py         whole messages     <-> bytes      framing, encoding, reassembly
    rpc.py          THE right message  <-> messages   correlation, timeouts, errors
    Keyboard        what the keyboard knows            this module

ZMK's generated messages stop at `rpc.py`. Above it everything is `model`, this
library's own schema, and `_from_zmk.py` is the only module that sees both. So a
consumer never imports `_pb`, never names a type from somebody else's repository,
and is not coupled to the shape of an RPC it did not ask about.

`reads.py` and `writes.py` are not floors. They hold values that flow down through
all of them, and their type is a proof: holding a ReadRequest is evidence the call
passed READS, holding a WriteRequest that it passed WRITES.

**This module deliberately imports neither `writes` nor `writable`.** Re-exporting
either here would put a write onto the package surface, where a caller reaches it as
a bare name and no import graph can tell read-only code from code that changes a
keyboard. That is why `WritableKeyboard` is not defined here beside `Keyboard`
despite being its subclass: a class that can write, defined in this file, would drag
`writes` into every module that imports `ReadRequest`.

So `import zmk_studio_client` can only read. Writing means naming
`zmk_studio_client.writable`, in a line a reviewer can grep for and an application
can forbid - which is how a consumer builds the stronger guarantee this library
cannot make on its own. tests/test_isolation.py enforces both halves.
"""
from __future__ import annotations

from . import model
from ._connect import open_rpc
from ._from_zmk import behavior as _behavior, device_info as _device_info
from ._from_zmk import keymap as _keymap, lock_state as _lock_state
from ._from_zmk import physical_layouts as _physical_layouts
from ._revision import STUDIO_MESSAGES_REVISION
from .connection import Connection, NotReachable
from .reads import READS, ReadRequest, WriteAttempted
from .rpc import KeyboardLocked, Rpc, RpcError
from .wire import Wire

#: The upstream revision of zmk-studio-messages these bindings were generated from.
#:
#: Public, though the module holding it is not: a consumer that records what it read
#: - an archive format, a bug report, a cache key - needs to say which definitions
#: decoded it, and has no other way to find out. The module stays private because it
#: is written by the reconcile script, not by hand.
__all__ = [
    "STUDIO_MESSAGES_REVISION",
    "model",
    "Connection", "NotReachable",
    "Wire",
    "READS", "ReadRequest", "WriteAttempted",
    "Rpc", "KeyboardLocked", "RpcError",
    "Keyboard", "connect",
]


class Keyboard:
    """One connected keyboard, and everything a read-only caller may ask it.

    The methods below are the whole surface: one per entry in `reads.READS`, each
    returning a `model` message rather than the envelope it arrived in, or the ZMK
    message inside it. Callers never name a subsystem or a field, so there is no
    call site that could name a mutating one, and nothing outside this package has
    to know the shape of the wire - or that there is a wire.

    A Keyboard cannot change a keyboard. That is not a convention - the class holds
    an Rpc and the only requests it can build are ReadRequests, whose constructor
    refuses anything outside the allowlist. To write, you need `writable.py`, and
    reaching it is an import a reviewer can see.
    """

    def __init__(self, rpc: Rpc) -> None:
        self._rpc = rpc
        self._behaviors: dict[int, model.Behavior] | None = None

    # -- what it knows ---------------------------------------------------------

    def device_info(self, timeout: float = 10.0) -> model.DeviceInfo:
        """Name and hardware serial. Answered even when the keyboard is locked."""
        return _device_info(
            self._read(ReadRequest("core", "get_device_info"), timeout).get_device_info)

    def lock_state(self) -> model.LockState:
        """Whether Studio has been unlocked (`model.LockState`).

        Answered even when the keyboard is locked. A caller about to read the keymap
        does not need to check this first: a locked keyboard refuses secured reads
        with UNLOCK_REQUIRED, which `rpc` raises as `KeyboardLocked`, so asking up
        front would spend a round trip for no extra information.
        """
        return _lock_state(
            self._read(ReadRequest("core", "get_lock_state")).get_lock_state)

    def keymap(self) -> model.Keymap:
        """Every layer and every binding."""
        return _keymap(self._read(ReadRequest("keymap", "get_keymap")).get_keymap)

    def physical_layouts(self) -> model.PhysicalLayouts:
        """The key geometry, and which layout is active."""
        return _physical_layouts(
            self._read(ReadRequest("keymap", "get_physical_layouts")).get_physical_layouts)

    def unsaved_changes(self) -> bool:
        """Whether the keyboard holds edits not yet written to flash."""
        return bool(self._read(ReadRequest("keymap", "check_unsaved_changes")).check_unsaved_changes)

    def behaviors(self) -> dict[int, model.Behavior]:
        """Every behavior this firmware build defines, keyed by its live id.

        Two RPCs behind one method, because the pair is useless apart: the ids a
        keyboard reports mean nothing without the names, and nothing wants one id's
        details in isolation. The ids are firmware-assigned - an index into this
        build's table - which is why a stored binding has to be re-mapped by display
        name before it can be written back, and why the table is read live every run.

        Read once per connection and kept. Fifty behaviors is fifty round trips, and
        a caller that reads a keymap, plans edits, and verifies them wants the same
        table repeatedly on one connection. Keeping it is safe
        because a firmware's behavior table cannot change while it is running - only
        a reflash changes it, and a reflash drops the connection.

        The memoization also answers a question that looked separate: what `edit()`
        should do against a locked keyboard. It needs this table, this is a read, and
        a locked keyboard refuses reads - so `edit()` raises KeyboardLocked with no
        special case written for it.
        """
        if self._behaviors is None:
            self._behaviors = {
                behavior_id: self._behavior_details(behavior_id)
                for behavior_id in self._behavior_ids()
            }
        return self._behaviors

    def close(self) -> None:
        self._rpc.close()

    # -- the two halves of behaviors(), which nothing else should want ---------

    def _behavior_ids(self):
        return self._read(ReadRequest("behaviors", "list_all_behaviors")).list_all_behaviors.behaviors

    def _behavior_details(self, behavior_id: int):
        from ._pb import behaviors_pb2

        query = behaviors_pb2.GetBehaviorDetailsRequest(behavior_id=behavior_id)
        return _behavior(
            self._read(ReadRequest("behaviors", "get_behavior_details", query))
            .get_behavior_details)

    def _read(self, request: ReadRequest, timeout: float = 10.0):
        """Send one read and return the subsystem response that answers it.

        Private, and narrower than the Rpc beneath it: it is annotated for and only
        ever handed a ReadRequest. A public send here would be a second door, and the
        permission check lives in the request constructor rather than in this method,
        so a public one would not be checking anything anyway.
        """
        return self._rpc.call(request, timeout)


def connect() -> Keyboard:
    """Open a keyboard that can be read and cannot be written.

    The read-only half of the pair. `writable.connect_writable()` is the other, and
    they are two functions rather than one with a flag so that the caller names which
    one it wants at the call site, and so that the type it gets back is the proof:
    there is no method on a Keyboard that changes anything.
    """
    return Keyboard(open_rpc())
