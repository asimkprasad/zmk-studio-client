from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class LockState(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    LOCK_STATE_UNSPECIFIED: _ClassVar[LockState]
    LOCK_STATE_LOCKED: _ClassVar[LockState]
    LOCK_STATE_UNLOCKED: _ClassVar[LockState]
LOCK_STATE_UNSPECIFIED: LockState
LOCK_STATE_LOCKED: LockState
LOCK_STATE_UNLOCKED: LockState

class DeviceInfo(_message.Message):
    __slots__ = ("name", "serial_number")
    NAME_FIELD_NUMBER: _ClassVar[int]
    SERIAL_NUMBER_FIELD_NUMBER: _ClassVar[int]
    name: str
    serial_number: bytes
    def __init__(self, name: _Optional[str] = ..., serial_number: _Optional[bytes] = ...) -> None: ...

class Keymap(_message.Message):
    __slots__ = ("layers", "available_layers", "max_layer_name_length")
    LAYERS_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_LAYERS_FIELD_NUMBER: _ClassVar[int]
    MAX_LAYER_NAME_LENGTH_FIELD_NUMBER: _ClassVar[int]
    layers: _containers.RepeatedCompositeFieldContainer[Layer]
    available_layers: int
    max_layer_name_length: int
    def __init__(self, layers: _Optional[_Iterable[_Union[Layer, _Mapping]]] = ..., available_layers: _Optional[int] = ..., max_layer_name_length: _Optional[int] = ...) -> None: ...

class Layer(_message.Message):
    __slots__ = ("id", "name", "bindings")
    ID_FIELD_NUMBER: _ClassVar[int]
    NAME_FIELD_NUMBER: _ClassVar[int]
    BINDINGS_FIELD_NUMBER: _ClassVar[int]
    id: int
    name: str
    bindings: _containers.RepeatedCompositeFieldContainer[Binding]
    def __init__(self, id: _Optional[int] = ..., name: _Optional[str] = ..., bindings: _Optional[_Iterable[_Union[Binding, _Mapping]]] = ...) -> None: ...

class Binding(_message.Message):
    __slots__ = ("behavior_id", "param1", "param2")
    BEHAVIOR_ID_FIELD_NUMBER: _ClassVar[int]
    PARAM1_FIELD_NUMBER: _ClassVar[int]
    PARAM2_FIELD_NUMBER: _ClassVar[int]
    behavior_id: int
    param1: int
    param2: int
    def __init__(self, behavior_id: _Optional[int] = ..., param1: _Optional[int] = ..., param2: _Optional[int] = ...) -> None: ...

class PhysicalLayouts(_message.Message):
    __slots__ = ("active_index", "layouts")
    ACTIVE_INDEX_FIELD_NUMBER: _ClassVar[int]
    LAYOUTS_FIELD_NUMBER: _ClassVar[int]
    active_index: int
    layouts: _containers.RepeatedCompositeFieldContainer[PhysicalLayout]
    def __init__(self, active_index: _Optional[int] = ..., layouts: _Optional[_Iterable[_Union[PhysicalLayout, _Mapping]]] = ...) -> None: ...

class PhysicalLayout(_message.Message):
    __slots__ = ("name", "keys")
    NAME_FIELD_NUMBER: _ClassVar[int]
    KEYS_FIELD_NUMBER: _ClassVar[int]
    name: str
    keys: _containers.RepeatedCompositeFieldContainer[KeyPosition]
    def __init__(self, name: _Optional[str] = ..., keys: _Optional[_Iterable[_Union[KeyPosition, _Mapping]]] = ...) -> None: ...

class KeyPosition(_message.Message):
    __slots__ = ("x", "y", "width", "height", "rotation", "rotation_x", "rotation_y")
    X_FIELD_NUMBER: _ClassVar[int]
    Y_FIELD_NUMBER: _ClassVar[int]
    WIDTH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    ROTATION_FIELD_NUMBER: _ClassVar[int]
    ROTATION_X_FIELD_NUMBER: _ClassVar[int]
    ROTATION_Y_FIELD_NUMBER: _ClassVar[int]
    x: int
    y: int
    width: int
    height: int
    rotation: int
    rotation_x: int
    rotation_y: int
    def __init__(self, x: _Optional[int] = ..., y: _Optional[int] = ..., width: _Optional[int] = ..., height: _Optional[int] = ..., rotation: _Optional[int] = ..., rotation_x: _Optional[int] = ..., rotation_y: _Optional[int] = ...) -> None: ...

class Behavior(_message.Message):
    __slots__ = ("id", "display_name", "parameter_sets")
    ID_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_NAME_FIELD_NUMBER: _ClassVar[int]
    PARAMETER_SETS_FIELD_NUMBER: _ClassVar[int]
    id: int
    display_name: str
    parameter_sets: _containers.RepeatedCompositeFieldContainer[ParameterSet]
    def __init__(self, id: _Optional[int] = ..., display_name: _Optional[str] = ..., parameter_sets: _Optional[_Iterable[_Union[ParameterSet, _Mapping]]] = ...) -> None: ...

class ParameterSet(_message.Message):
    __slots__ = ("param1", "param2")
    PARAM1_FIELD_NUMBER: _ClassVar[int]
    PARAM2_FIELD_NUMBER: _ClassVar[int]
    param1: _containers.RepeatedCompositeFieldContainer[ParameterValue]
    param2: _containers.RepeatedCompositeFieldContainer[ParameterValue]
    def __init__(self, param1: _Optional[_Iterable[_Union[ParameterValue, _Mapping]]] = ..., param2: _Optional[_Iterable[_Union[ParameterValue, _Mapping]]] = ...) -> None: ...

class ParameterValue(_message.Message):
    __slots__ = ("name", "no_value", "constant", "range", "hid_usage", "layer_id")
    NAME_FIELD_NUMBER: _ClassVar[int]
    NO_VALUE_FIELD_NUMBER: _ClassVar[int]
    CONSTANT_FIELD_NUMBER: _ClassVar[int]
    RANGE_FIELD_NUMBER: _ClassVar[int]
    HID_USAGE_FIELD_NUMBER: _ClassVar[int]
    LAYER_ID_FIELD_NUMBER: _ClassVar[int]
    name: str
    no_value: NoValue
    constant: int
    range: ValueRange
    hid_usage: HidUsage
    layer_id: LayerId
    def __init__(self, name: _Optional[str] = ..., no_value: _Optional[_Union[NoValue, _Mapping]] = ..., constant: _Optional[int] = ..., range: _Optional[_Union[ValueRange, _Mapping]] = ..., hid_usage: _Optional[_Union[HidUsage, _Mapping]] = ..., layer_id: _Optional[_Union[LayerId, _Mapping]] = ...) -> None: ...

class NoValue(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class LayerId(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ValueRange(_message.Message):
    __slots__ = ("min", "max")
    MIN_FIELD_NUMBER: _ClassVar[int]
    MAX_FIELD_NUMBER: _ClassVar[int]
    min: int
    max: int
    def __init__(self, min: _Optional[int] = ..., max: _Optional[int] = ...) -> None: ...

class HidUsage(_message.Message):
    __slots__ = ("keyboard_max", "consumer_max")
    KEYBOARD_MAX_FIELD_NUMBER: _ClassVar[int]
    CONSUMER_MAX_FIELD_NUMBER: _ClassVar[int]
    keyboard_max: int
    consumer_max: int
    def __init__(self, keyboard_max: _Optional[int] = ..., consumer_max: _Optional[int] = ...) -> None: ...
