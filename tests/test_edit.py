"""What an Edit does with changes nobody decided about.

A well-behaved caller always settles its edit - save on success, discard on every
failure path - so the cases here are the ones a careful caller never reaches. That is
the point of testing them: Edit is a general API, and the next caller may not have
that discipline.

Driven against a recording Rpc rather than a fake Edit, so these assert what actually
leaves for the keyboard.
"""
from __future__ import annotations

import pytest

from zmk_studio_client._pb import behaviors_pb2, keymap_pb2
from zmk_studio_client import Keyboard
from zmk_studio_client.writable import (
    BindingRejected,
    Edit,
    EditAbandoned,
    EditSettled,
    SaveRefused,
    WritableKeyboard,
)

#: Two behaviors, as a firmware build would report them.
BEHAVIORS = {
    0: behaviors_pb2.GetBehaviorDetailsResponse(id=0, display_name="Key Press"),
    7: behaviors_pb2.GetBehaviorDetailsResponse(id=7, display_name="None"),
}


class Recorder:
    """An Rpc that says yes to everything and remembers what it was asked."""

    def __init__(self, *, save_ok=True, binding_ok=True, discard_raises=False):
        self.save_ok = save_ok
        self.binding_ok = binding_ok
        self.discard_raises = discard_raises
        self.fields: list[str] = []
        self.closed = False

    def call(self, request, timeout: float = 10.0):
        self.fields.append(request.field)
        response = keymap_pb2.Response()
        if request.field == "set_layer_binding":
            response.set_layer_binding = (
                keymap_pb2.SET_LAYER_BINDING_RESP_OK if self.binding_ok
                else keymap_pb2.SET_LAYER_BINDING_RESP_INVALID_LOCATION)
        elif request.field == "save_changes":
            if self.save_ok:
                response.save_changes.ok = True
            else:
                response.save_changes.err = keymap_pb2.SAVE_CHANGES_ERR_NOT_SUPPORTED
        elif request.field == "discard_changes":
            if self.discard_raises:
                raise OSError("link dropped")
            response.discard_changes = True
        elif request.field == "list_all_behaviors":
            return behaviors_pb2.Response(
                list_all_behaviors=behaviors_pb2.ListAllBehaviorsResponse(
                    behaviors=list(BEHAVIORS)))
        elif request.field == "get_behavior_details":
            wanted = request.message.behaviors.get_behavior_details.behavior_id
            return behaviors_pb2.Response(get_behavior_details=BEHAVIORS[wanted])
        return response

    def close(self) -> None:
        self.closed = True


def _edit(**kwargs) -> tuple[Edit, Recorder]:
    recorder = Recorder(**kwargs)
    return Edit(recorder, BEHAVIORS), recorder


def _binding(edit: Edit) -> None:
    edit.set_binding(layer_id=0, position=1, behavior_id=0, param1=4)


# --------------------------------------------------------------------------- #
# nothing commits unless it is asked to
# --------------------------------------------------------------------------- #

def test_a_binding_is_sent_but_not_committed() -> None:
    """The whole basis of the rollback: writes land in RAM, not in flash."""
    edit, recorder = _edit()
    _binding(edit)
    assert recorder.fields == ["set_layer_binding"]
    assert edit.pending == 1


def test_an_edit_commits_only_when_save_is_called() -> None:
    """No implicit commit, anywhere. An exception must not decide this."""
    edit, recorder = _edit()
    _binding(edit)
    edit.save()
    assert recorder.fields == ["set_layer_binding", "save_changes"]


def test_discarding_leaves_the_keymap_alone() -> None:
    edit, recorder = _edit()
    _binding(edit)
    edit.discard()
    assert recorder.fields[-1] == "discard_changes"
    assert "save_changes" not in recorder.fields


# --------------------------------------------------------------------------- #
# close() with pending changes
# --------------------------------------------------------------------------- #

def test_closing_on_pending_changes_discards_them_and_says_so() -> None:
    """Silence here would let a missing branch decide whether a keymap changed."""
    keyboard = WritableKeyboard(Recorder())
    recorder = keyboard._rpc
    _binding(keyboard.edit())
    with pytest.raises(EditAbandoned, match="1 binding change"):
        keyboard.close()
    assert "discard_changes" in recorder.fields
    assert "save_changes" not in recorder.fields
    assert recorder.closed, "the transport must be released even when close() raises"


def test_closing_after_a_save_is_quiet() -> None:
    """The normal path. A close() that always shouted would teach people to ignore it."""
    keyboard = WritableKeyboard(Recorder())
    edit = keyboard.edit()
    _binding(edit)
    edit.save()
    keyboard.close()
    assert keyboard._rpc.closed


def test_closing_with_nothing_pending_is_quiet() -> None:
    keyboard = WritableKeyboard(Recorder())
    keyboard.edit()
    keyboard.close()
    assert "discard_changes" not in keyboard._rpc.fields


def test_the_transport_is_released_even_when_the_discard_fails() -> None:
    """The worst case: the link dropped. Losing the port as well helps nobody."""
    keyboard = WritableKeyboard(Recorder(discard_raises=True))
    _binding(keyboard.edit())
    with pytest.raises(OSError):
        keyboard.close()
    assert keyboard._rpc.closed


# --------------------------------------------------------------------------- #
# an edit is one decision
# --------------------------------------------------------------------------- #

def test_a_saved_edit_refuses_further_bindings() -> None:
    """Reopening a committed batch would leave half a change pending behind it."""
    edit, _ = _edit()
    _binding(edit)
    edit.save()
    with pytest.raises(EditSettled):
        _binding(edit)


def test_a_discarded_edit_refuses_further_bindings() -> None:
    edit, _ = _edit()
    edit.discard()
    with pytest.raises(EditSettled):
        _binding(edit)


def test_a_refused_save_leaves_the_edit_open_to_be_discarded() -> None:
    """If a failed save settled the edit, the rollback could not run."""
    edit, recorder = _edit(save_ok=False)
    _binding(edit)
    with pytest.raises(SaveRefused, match="NOT_SUPPORTED"):
        edit.save()
    edit.discard()
    assert recorder.fields[-1] == "discard_changes"


# --------------------------------------------------------------------------- #
# the behavior id check
# --------------------------------------------------------------------------- #

def test_an_id_this_firmware_does_not_define_is_refused_before_it_is_sent() -> None:
    """A stale id is individually valid, so the keyboard would accept it.

    It would bind the key to whatever that index means in this build - the wrong
    keymap, written in silence. This is the last place that can catch it.
    """
    edit, recorder = _edit()
    with pytest.raises(BindingRejected, match="not one this firmware defines"):
        edit.set_binding(layer_id=0, position=1, behavior_id=99)
    assert recorder.fields == [], "nothing may leave for a refused binding"
    assert edit.pending == 0


def test_a_rejection_from_the_keyboard_names_the_behavior() -> None:
    """'the keyboard said no' is half an error; which key, bound to what, is the rest."""
    edit, _ = _edit(binding_ok=False)
    with pytest.raises(BindingRejected) as caught:
        _binding(edit)
    message = str(caught.value)
    assert "Key Press" in message and "INVALID_LOCATION" in message
    assert edit.pending == 0, "a refused binding is not pending"


# --------------------------------------------------------------------------- #
# edit() needs the behavior table, which is what makes it refuse when locked
# --------------------------------------------------------------------------- #

def test_opening_an_edit_reads_the_behavior_table() -> None:
    """Not incidental: it is why a locked keyboard refuses edit() with no special case."""
    keyboard = WritableKeyboard(Recorder())
    keyboard.edit()
    assert "list_all_behaviors" in keyboard._rpc.fields


def test_the_behavior_table_is_read_once_per_connection() -> None:
    """Fifty behaviors is fifty round trips; plan-then-apply used to pay four times."""
    keyboard = WritableKeyboard(Recorder())
    for _ in range(3):
        keyboard.behaviors()
    keyboard.edit()
    assert keyboard._rpc.fields.count("list_all_behaviors") == 1
    assert keyboard._rpc.fields.count("get_behavior_details") == len(BEHAVIORS)


def test_a_plain_keyboard_offers_no_way_to_open_an_edit() -> None:
    assert not hasattr(Keyboard(Recorder()), "edit")
