"""The write surface, checked against the generated protobuf descriptors.

Driven from the descriptors for the same reason tests/test_readonly.py is: a proto
refresh that adds an RPC must make this fail until someone classifies the new call.
A hand-written list would simply not mention it.

The two allowlists are the whole story. reads.READS is what a read-only caller may
send; write.WRITES is what `writable` may send. Everything else in the protocol is
unconstructible from either, and these tests are what make that a fact rather than a
claim in a docstring.
"""
from __future__ import annotations

import pytest

from zmk_studio_client import reads, writes as write
from zmk_studio_client import rpc as keyboard_rpc

#: Every (subsystem, field) the protocol defines, read off the descriptors.
ALL_RPCS = frozenset(
    (subsystem, field.name)
    for subsystem, module in reads._SUBSYSTEMS.items()
    for field in module.Request.DESCRIPTOR.oneofs[0].fields
)

#: Mutating calls that must stay unconstructible even on the write path. Named one by
#: one so a failure says which got through, not merely that a count moved.
NEVER = [
    ("core", "lock"),
    ("core", "reset_settings"),
    ("keymap", "add_layer"),
    ("keymap", "remove_layer"),
    ("keymap", "move_layer"),
    ("keymap", "restore_layer"),
    ("keymap", "set_layer_props"),
    ("keymap", "set_active_physical_layout"),
]


def test_the_allowlist_names_only_real_rpcs() -> None:
    assert write.WRITES <= ALL_RPCS


def test_the_two_allowlists_do_not_overlap() -> None:
    """A call is a read or a write, never both; otherwise neither door means anything."""
    assert not (write.WRITES & reads.READS)


@pytest.mark.parametrize("subsystem,field", NEVER)
def test_a_refused_call_cannot_be_built(subsystem: str, field: str) -> None:
    # Assert the field still exists first, so a renamed RPC - which is also absent from
    # WRITES - cannot make this pass for a call that is no longer the one being guarded.
    assert (subsystem, field) in ALL_RPCS, f"{subsystem}.{field} is no longer an RPC"
    with pytest.raises(write.WriteRefused):
        write.WriteRequest(subsystem, field)


def test_resetting_settings_is_refused_by_name() -> None:
    """The one call that wipes the stored keymap and BLE bonds. Worth its own test."""
    with pytest.raises(write.WriteRefused, match="wipes the stored keymap"):
        write.WriteRequest("core", "reset_settings")


def test_every_rpc_is_either_an_allowed_write_or_unbuildable() -> None:
    """No call in the protocol is unclassified on the write path."""
    for subsystem, field in sorted(ALL_RPCS):
        if (subsystem, field) in write.WRITES:
            continue
        with pytest.raises(write.WriteRefused):
            write.WriteRequest(subsystem, field)


def test_a_read_is_refused_with_a_pointer_to_the_read_path() -> None:
    """Refusing is not enough if it leaves the caller with nowhere to go."""
    with pytest.raises(write.WriteRefused, match="reads.ReadRequest"):
        write.WriteRequest("keymap", "get_keymap")


def test_the_allowlist_has_not_been_widened() -> None:
    # Every entry is a request that changes a real keyboard. Growing this list is a
    # decision, not a detail, so it should not be possible to make it on the way past.
    assert len(write.WRITES) == 3
    assert len(ALL_RPCS) == 18


# --------------------------------------------------------------------------- #
# the constructors
# --------------------------------------------------------------------------- #

def test_each_permitted_call_has_exactly_one_constructor() -> None:
    """The module's write surface is the allowlist, so no call site spells a field."""
    built = {
        write.set_binding(0, 0, 1),
        write.save_changes(),
        write.discard_changes(),
    }
    assert {(r.subsystem, r.field) for r in built} == write.WRITES


def test_set_binding_carries_every_field_it_was_given() -> None:
    request = write.set_binding(layer_id=4, position=37, behavior_id=9,
                                param1=0x08070006, param2=3)
    sent = request.message.keymap.set_layer_binding
    assert sent.layer_id == 4
    assert sent.key_position == 37
    assert sent.binding.behavior_id == 9
    assert sent.binding.param1 == 0x08070006
    assert sent.binding.param2 == 3


def test_a_binding_defaults_to_no_parameters() -> None:
    """&trans and &none take none; a caller should not have to pass zeroes."""
    sent = write.set_binding(0, 1, 22).message.keymap.set_layer_binding
    assert sent.binding.param1 == 0 and sent.binding.param2 == 0


def test_request_ids_are_unique_across_both_doors() -> None:
    """Reads and writes share one connection, so one counter.

    The id is stamped by Rpc at send time, not by the constructor: a request is a
    value describing what you want, and the number tracking it belongs to the
    connection carrying it. A collision would make match_response hand a caller the
    answer to someone else's request.
    """
    sent = []

    class Recorder:
        def send(self, message):
            sent.append(message.request_id)

        def receive(self, timeout):
            return None

    rpc_layer = keyboard_rpc.Rpc(Recorder())
    for request in (reads.ReadRequest("keymap", "get_keymap"),
                    write.save_changes(),
                    reads.ReadRequest("core", "get_lock_state"),
                    write.discard_changes()):
        with pytest.raises(TimeoutError):
            rpc_layer.call(request, timeout=0.01)
    assert len(set(sent)) == len(sent) == 4


def test_a_request_carries_no_id_until_it_is_sent() -> None:
    """Two identical requests are identical values, not objects differing by a number."""
    assert reads.ReadRequest("keymap", "get_keymap").request_id == 0
    assert write.save_changes().request_id == 0


def test_a_write_goes_out_framed_like_a_read() -> None:
    """Same wire format; the allowlist is the only difference between the two doors.

    Asserted through the wire rather than on the request, because framing is the
    wire's job - a request is a value and knows nothing about bytes.
    """
    from zmk_studio_client.wire import EOF, SOF, Wire

    class Recorder:
        def __init__(self): self.sent = b""
        def send(self, data): self.sent = data
        def receive(self, timeout): return b""
        def close(self): pass

    for request in (reads.ReadRequest("keymap", "get_keymap"), write.save_changes()):
        recorder = Recorder()
        Wire(recorder).send(request.message)
        assert recorder.sent[0] == SOF and recorder.sent[-1] == EOF


def test_a_framed_write_parses_back_to_what_was_sent() -> None:
    from zmk_studio_client._pb import studio_pb2
    request = write.set_binding(2, 11, 5, param1=458756)
    parsed = studio_pb2.Request()
    parsed.ParseFromString(request.message.SerializeToString())
    assert parsed.request_id == request.request_id
    assert parsed.keymap.set_layer_binding.binding.param1 == 458756
