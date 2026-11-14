"""Writes: the three calls the write surface may send, and nothing else.

A separate module from `reads` on purpose. The two allowlists could share a file and
the code would be shorter, but then `__init__` - which needs ReadRequest - would reach
WriteRequest through the same import, and "a read-only caller cannot modify the
keyboard" would stop being something the import graph can prove.
Keeping them apart costs one file and buys a guarantee that holds for code paths no
test exercises.

WRITES is deliberately smaller than "every mutating call in the protocol". Changing
key bindings on a live keyboard needs to set bindings and commit or discard them; it
does not need to add, remove, reorder or rename layers, and it never needs to wipe
settings. A call absent from WRITES is unconstructible here exactly as it is in
`reads`, so widening the surface is a decision someone has to make on purpose.

NEVER permitted, in any version: core.reset_settings (wipes the stored keymap and BLE
bonds) and core.lock.
"""
from __future__ import annotations

import typing

from ._pb import keymap_pb2, studio_pb2
from .reads import READS, _SUBSYSTEMS, _build

#: (subsystem, field) pairs the write surface may send. Must never overlap READS.
WRITES = frozenset({
    ("keymap", "set_layer_binding"),
    ("keymap", "save_changes"),
    ("keymap", "discard_changes"),
})


class WriteRefused(Exception):
    """Something tried to build a mutating call outside WRITES."""


#: Mutating calls that exist in the protocol and are refused anyway, with the reason.
#: Kept as data so the refusal can explain itself instead of saying only "no".
_REFUSED = {
    ("core", "reset_settings"):
        "wipes the stored keymap and BLE bonds",
    ("core", "lock"):
        "locks Studio; this library does not change the lock state",
    ("keymap", "add_layer"): "changes the layer set; only binding edits are supported",
    ("keymap", "remove_layer"): "changes the layer set; only binding edits are supported",
    ("keymap", "move_layer"): "reorders layers; only binding edits are supported",
    ("keymap", "restore_layer"): "revives a removed layer; only binding edits are supported",
    ("keymap", "set_layer_props"): "renames a layer; only binding edits are supported",
    ("keymap", "set_active_physical_layout"):
        "re-keys every binding by changing the active layout; only binding edits are supported",
}



class WriteRequest:
    """One mutating request `writable` is permitted to send.

    Refuses in the constructor, mirroring `reads.ReadRequest`: holding a WriteRequest is
    itself the proof that it names one of the three permitted calls. There is no
    separate validator for a future call site to skip.
    """

    __slots__ = ("subsystem", "field", "message")

    def __init__(self, subsystem: str, field: str, value: typing.Any = True) -> None:
        if (subsystem, field) not in WRITES:
            raise WriteRefused(_why(subsystem, field))
        self.subsystem = subsystem
        self.field = field
        self.message = studio_pb2.Request()
        _build(self.message, subsystem, field, value)

    @property
    def request_id(self) -> int:
        return self.message.request_id

    def __repr__(self) -> str:
        return f"WriteRequest({self.subsystem}.{self.field} #{self.request_id})"


def _why(subsystem: str, field: str) -> str:
    """The refusal message, naming the reason when there is a specific one."""
    reason = _REFUSED.get((subsystem, field))
    if reason is not None:
        return f"{subsystem}.{field} is refused: {reason}"
    if (subsystem, field) in READS:
        return f"{subsystem}.{field} is a read; build it with reads.ReadRequest"
    return f"{subsystem}.{field} is not a call this library sends"


# --------------------------------------------------------------------------- #
# One constructor per permitted call, so no call site spells a field name.
# --------------------------------------------------------------------------- #

def set_binding(layer_id: int, position: int, behavior_id: int,
                param1: int = 0, param2: int = 0) -> WriteRequest:
    """Place one binding on one key of one layer.

    `behavior_id` is assigned by the firmware, not by the protocol, so it is only
    meaningful against the behavior table of the board being written to. Callers must
    map a snapshot's behavior by NAME against a live behaviors.list_all_behaviors read
    rather than replaying the id the snapshot stored; a stale id is individually valid
    and will be accepted, binding the key to the wrong behavior in silence.
    """
    request = keymap_pb2.SetLayerBindingRequest(
        layer_id=layer_id,
        key_position=position,
        binding=keymap_pb2.BehaviorBinding(
            behavior_id=behavior_id, param1=param1, param2=param2),
    )
    return WriteRequest("keymap", "set_layer_binding", request)


def save_changes() -> WriteRequest:
    """Commit pending binding changes to the keyboard's settings storage.

    Until this is sent, every set_binding is in RAM and `discard_changes` undoes all of
    them. This is the only irreversible call in the module.
    """
    return WriteRequest("keymap", "save_changes")


def discard_changes() -> WriteRequest:
    """Throw away every pending binding change held in RAM."""
    return WriteRequest("keymap", "discard_changes")
