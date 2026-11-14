"""The read-only guarantee, checked against the generated protobuf descriptors.

The point of driving this from the descriptors rather than a hand-written list is that
it cannot go stale: reconcile.sh pulling a new upstream revision that adds an
RPC makes this fail until someone classifies the new call. A list written out by hand
would simply not mention it.

The check lives in ReadRequest's constructor, so these assert that the object cannot
be built at all - not that some validator was remembered on the way past.
"""
from __future__ import annotations

import pytest

from zmk_studio_client import Keyboard, reads as rpc
from zmk_studio_client.writable import WritableKeyboard

#: Every (subsystem, field) the protocol defines, read off the descriptors.
ALL_RPCS = frozenset(
    (subsystem, field.name)
    for subsystem, module in rpc._SUBSYSTEMS.items()
    for field in module.Request.DESCRIPTOR.oneofs[0].fields
)

#: The calls that change the keyboard. Named explicitly, so that a failure report says
#: which one got through rather than only that the count moved.
MUTATORS = [
    ("core", "lock"),
    ("core", "reset_settings"),
    ("keymap", "set_layer_binding"),
    ("keymap", "save_changes"),
    ("keymap", "discard_changes"),
    ("keymap", "set_active_physical_layout"),
    ("keymap", "move_layer"),
    ("keymap", "add_layer"),
    ("keymap", "remove_layer"),
    ("keymap", "restore_layer"),
    ("keymap", "set_layer_props"),
]


@pytest.mark.parametrize("subsystem,field", MUTATORS)
def test_a_mutating_call_cannot_be_built(subsystem: str, field: str) -> None:
    # Asserting the field still exists first keeps this from passing vacuously: a
    # renamed or misspelled RPC is also absent from READS, so the refusal below would
    # hold for a call that is no longer the one being guarded against.
    assert (subsystem, field) in ALL_RPCS, f"{subsystem}.{field} is no longer an RPC"
    with pytest.raises(rpc.WriteAttempted):
        rpc.ReadRequest(subsystem, field)


def test_every_rpc_is_either_an_allowed_read_or_unbuildable() -> None:
    """No call in the protocol is unclassified - the property the README claims."""
    for subsystem, field in sorted(ALL_RPCS):
        if (subsystem, field) in rpc.READS:
            continue
        with pytest.raises(rpc.WriteAttempted):
            rpc.ReadRequest(subsystem, field)


def test_the_allowlist_names_only_real_rpcs() -> None:
    assert rpc.READS <= ALL_RPCS


#: Each allowed read, and the Keyboard method that performs it. Spelled out because
#: no mechanical rule turns ("core", "get_device_info") into device_info().
#:
#: The two behaviors reads share one method on purpose: the ids are useless without
#: the names, so `behaviors()` performs both and keeps the table. The mapping is
#: therefore onto, not one-to-one, and the assertions below say so.
READ_METHODS = {
    ("core", "get_device_info"): "device_info",
    ("core", "get_lock_state"): "lock_state",
    ("keymap", "get_keymap"): "keymap",
    ("keymap", "get_physical_layouts"): "physical_layouts",
    ("keymap", "check_unsaved_changes"): "unsaved_changes",
    ("behaviors", "list_all_behaviors"): "behaviors",
    ("behaviors", "get_behavior_details"): "behaviors",
}


def test_the_keyboard_exposes_a_method_for_every_allowlist_entry() -> None:
    """The read surface is the allowlist, so no call site names a field.

    Fails in both directions on purpose: a read added to READS without a method is
    unreachable, and a method without an allowlist entry could not have been built.
    """
    assert set(READ_METHODS) == set(rpc.READS)
    for method in READ_METHODS.values():
        assert callable(getattr(Keyboard, method, None)), method


def test_the_keyboard_has_no_other_way_to_send() -> None:
    """Anything public beyond the reads and close() would be a second door."""
    assert _public(Keyboard) == set(READ_METHODS.values()) | {"close"}


def test_a_writable_keyboard_adds_exactly_one_method() -> None:
    """The subclass is the whole difference between reading and writing.

    If it ever grows a second public method, the question "what can change this
    keyboard" stops having a one-word answer, which is the property that lets a
    caller be reviewed by reading one file.
    """
    assert _public(WritableKeyboard) == {"edit", "close"}
    assert set(dir(WritableKeyboard)) - set(dir(Keyboard)) == {"edit"}


def test_a_plain_keyboard_cannot_be_asked_to_edit() -> None:
    """The guarantee at the type, not only at the import graph."""
    assert not hasattr(Keyboard, "edit")


def _public(cls) -> set[str]:
    """Callables defined on `cls` itself, excluding inherited and private ones."""
    return {
        name for name, attribute in vars(cls).items()
        if callable(attribute) and not name.startswith("_")
    }


def test_the_allowlist_has_not_been_widened() -> None:
    # Every entry is a request a read-only Keyboard can send. Growing the list is a
    # decision, not a detail, so it should not be possible to make it on the way past.
    assert len(rpc.READS) == 7
    assert len(ALL_RPCS) == 18
