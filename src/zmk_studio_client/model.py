"""The types this library hands back: one import, no generated package to name.

Everything a `Keyboard` returns is defined here, in `proto/keyboard.proto`. A
consumer names `zmk_studio_client.model.Keymap` and never reaches into a `_pb`
directory, never learns which `.proto` file a message came from, and never has to
regenerate bindings from somebody else's repository to spell a type.

That is the whole point of the module. ZMK's own messages are the shape of the RPC
that carries them - request envelopes, response oneofs, a `metadata` field that is
really a parameter table - and a consumer holding one would be coupled to a
protocol it did not ask about. `_from_zmk.py` is where the two meet, and it is the
only place in the library that sees both.

The schema ships inside the wheel. A client in another language generates from it:

    python3 -c 'import zmk_studio_client, pathlib;
                print(pathlib.Path(zmk_studio_client.__file__).parent / "proto")'
"""
from __future__ import annotations

from .proto.keyboard_pb2 import (
    Behavior,
    Binding,
    DeviceInfo,
    HidUsage,
    KeyPosition,
    Keymap,
    Layer,
    LayerId,
    LockState,
    NoValue,
    ParameterSet,
    ParameterValue,
    PhysicalLayout,
    PhysicalLayouts,
    ValueRange,
)

__all__ = [
    "Behavior", "Binding", "DeviceInfo", "HidUsage", "KeyPosition", "Keymap",
    "Layer", "LayerId", "LockState", "NoValue", "ParameterSet", "ParameterValue",
    "PhysicalLayout", "PhysicalLayouts", "ValueRange",
]
