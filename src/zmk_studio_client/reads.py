"""Reads: the allowlist, and the proof that a call does not change anything.

Not a layer. A ReadRequest is a value that flows down through rpc, wire and
connection, and its type is a claim: holding one is evidence the call passed READS.
The wrapper carries nothing the protobuf lacks - both `subsystem` and `field` are
derivable from the message - so its whole value is in what cannot be constructed.

**This module is deliberately separate from `writes`.** Both allowlists are permanent
and it is tempting to put them in one file, but the separation is what makes the
import graph able to say which callers can change a keyboard: `__init__` imports this
module and not its sibling, so the read-only surface has no route to a write even in
code no test exercises. Merged, that guarantee would weaken to "nobody calls the wrong
constructor", which is a convention rather than a fact. See tests/test_isolation.py.

Every operation in the ZMK Studio protocol is a separate field of a protobuf oneof;
eighteen exist, of which seven are reads. The check is in the constructor, so a
request naming one of the other eleven cannot be *built* - not built and then
rejected - and there is no second path that forgot to call a validator.

READS is an allowlist over (subsystem, field) rather than a list of calls to avoid.
That is the part which survives a proto refresh: an upstream revision adding a
mutating call arrives unconstructible and stays that way until someone classifies it.
tests/test_readonly.py enumerates the protocol from the generated descriptors, so the
claim is checked rather than asserted.
"""
from __future__ import annotations

import typing

from ._pb import behaviors_pb2, core_pb2, keymap_pb2, studio_pb2

#: (subsystem, field) pairs a read-only caller may send. Also the whole read surface:
#: Keyboard has one method per entry and nothing else that sends.
READS = frozenset({
    ("core", "get_device_info"),
    ("core", "get_lock_state"),
    ("keymap", "get_keymap"),
    ("keymap", "get_physical_layouts"),
    ("keymap", "check_unsaved_changes"),
    ("behaviors", "list_all_behaviors"),
    ("behaviors", "get_behavior_details"),
})

_SUBSYSTEMS = {"core": core_pb2, "behaviors": behaviors_pb2, "keymap": keymap_pb2}


class WriteAttempted(Exception):
    """Something tried to build a request that would modify the keyboard."""


def _build(message, subsystem: str, field: str, value) -> None:
    """Populate the envelope's subsystem arm with the call being made."""
    sub = _SUBSYSTEMS[subsystem].Request()
    if value is True:
        setattr(sub, field, True)
    else:
        getattr(sub, field).CopyFrom(value)
    getattr(message, subsystem).CopyFrom(sub)


class ReadRequest:
    """One read a read-only Keyboard is permitted to send.

    Refuses in the constructor, so possessing a ReadRequest is itself the proof that
    it is a read. There is no way to hold one that names a mutating call.

    It carries the subsystem it expects an answer on, which is what lets
    `rpc.match_response` reject a reply belonging to something else without the
    caller having to repeat itself. The request_id stays zero until `Rpc.call`
    stamps it, so two identical requests are equal values.
    """

    __slots__ = ("subsystem", "field", "message")

    def __init__(self, subsystem: str, field: str, value: typing.Any = True) -> None:
        """`value` is True for the bool-valued reads, or a populated message for
        behaviors.get_behavior_details, which takes a behavior id."""
        if (subsystem, field) not in READS:
            raise WriteAttempted(
                f"{subsystem}.{field} is not a read; ReadRequest cannot modify the keyboard"
            )
        self.subsystem = subsystem
        self.field = field
        self.message = studio_pb2.Request()
        _build(self.message, subsystem, field, value)

    @property
    def request_id(self) -> int:
        return self.message.request_id

    def __repr__(self) -> str:
        return f"ReadRequest({self.subsystem}.{self.field} #{self.request_id})"
