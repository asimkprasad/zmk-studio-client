"""The boundary: what a caller gets back is ours, and nothing is dropped crossing it.

Two claims, and the second is the one that needs machinery.

1. Every read returns a message defined in `proto/keyboard.proto`. If one ever
   returns a ZMK message again, the library is back to exporting somebody else's
   protocol and the README's promise is false.

2. The translation loses nothing. This is checked by walking the model's own
   descriptors rather than against a list written here, because a hand list goes
   stale the moment the schema grows a field and then quietly certifies that the
   field is populated when it is not. A dropped field is this project's recurring
   failure: it produces a valid-looking record, no exception, exit 0.
"""
from __future__ import annotations

import pytest

from zmk_studio_client import Keyboard, model
from zmk_studio_client._pb import behaviors_pb2, core_pb2, keymap_pb2
from zmk_studio_client import _from_zmk

OURS = "zmk_studio_client/proto/keyboard.proto"


# --------------------------------------------------------------------------- #
# fixtures: ZMK messages with every field set to a distinct, non-default value
# --------------------------------------------------------------------------- #
#
# Distinct on purpose, so that the spelled-out expectations below catch a crossed
# pair: `rotation_y=rx` is invisible when rx == ry, and the three rotation fields
# are exactly where upstream's one-letter names invite the mistake.
#
# Note what each half of this file can prove. The descriptor walk catches a field
# that was DROPPED; it cannot catch one that was crossed, because both ends stay
# non-default. Only the spelled-out expectations catch that. Neither is redundant.

def _zmk_keymap() -> keymap_pb2.Keymap:
    return keymap_pb2.Keymap(
        available_layers=9,
        max_layer_name_length=16,
        layers=[
            keymap_pb2.Layer(id=3, name="SYM", bindings=[
                keymap_pb2.BehaviorBinding(behavior_id=11, param1=0x08070006, param2=5),
                keymap_pb2.BehaviorBinding(behavior_id=12, param1=7, param2=8),
            ]),
            keymap_pb2.Layer(id=4, name="FUN", bindings=[
                keymap_pb2.BehaviorBinding(behavior_id=13, param1=9, param2=10),
            ]),
        ])


def _zmk_layouts() -> keymap_pb2.PhysicalLayouts:
    return keymap_pb2.PhysicalLayouts(
        active_layout_index=1,
        layouts=[
            keymap_pb2.PhysicalLayout(name="Default", keys=[
                keymap_pb2.KeyPhysicalAttrs(width=1, height=2, x=3, y=4, r=5, rx=6, ry=7),
            ]),
            keymap_pb2.PhysicalLayout(name="Split", keys=[
                keymap_pb2.KeyPhysicalAttrs(width=11, height=12, x=13, y=14,
                                            r=15, rx=16, ry=17),
            ]),
        ])


def _zmk_behavior() -> behaviors_pb2.GetBehaviorDetailsResponse:
    """One behavior declaring every kind of parameter the protocol has.

    No real behavior looks like this. It is built to exercise all five oneof
    variants in one pass, because the variants are copied by hand - a oneof cannot
    be assigned wholesale - and a hand copy is where one gets forgotten.
    """
    def described(name, **kind):
        value = behaviors_pb2.BehaviorParameterValueDescription(name=name)
        for key, payload in kind.items():
            if payload is True:
                getattr(value, key).SetInParent()
            elif key == "constant":
                value.constant = payload
            else:
                getattr(value, key).CopyFrom(payload)
        return value

    return behaviors_pb2.GetBehaviorDetailsResponse(
        id=11,
        display_name="Mod-Tap",
        metadata=[
            behaviors_pb2.BehaviorBindingParametersSet(
                param1=[described("Key", hid_usage=behaviors_pb2.BehaviorParameterHidUsage(
                    keyboard_max=0xE7, consumer_max=0x29D))],
                param2=[described("Layer", layer_id=True)]),
            behaviors_pb2.BehaviorBindingParametersSet(
                param1=[described("Profile",
                                  range=behaviors_pb2.BehaviorParameterValueDescriptionRange(
                                      min=0, max=4))],
                param2=[described("Clear All Profiles", constant=3)]),
            behaviors_pb2.BehaviorBindingParametersSet(
                param1=[described("Toggle", nil=True)],
                param2=[described("Toggle", nil=True)]),
        ])


# --------------------------------------------------------------------------- #
# claim 1: the reads hand back our types
# --------------------------------------------------------------------------- #

class _FakeRpc:
    """Answers each read with a ZMK message, the way a keyboard would."""

    def __init__(self):
        self.closed = False

    def call(self, request, timeout: float = 10.0):
        if request.field == "get_device_info":
            return core_pb2.Response(get_device_info=core_pb2.GetDeviceInfoResponse(
                name="Sofle", serial_number=b"\xde\xad\xbe\xef"))
        if request.field == "get_lock_state":
            return core_pb2.Response(
                get_lock_state=core_pb2.ZMK_STUDIO_CORE_LOCK_STATE_UNLOCKED)
        if request.field == "get_keymap":
            return keymap_pb2.Response(get_keymap=_zmk_keymap())
        if request.field == "get_physical_layouts":
            return keymap_pb2.Response(get_physical_layouts=_zmk_layouts())
        if request.field == "check_unsaved_changes":
            return keymap_pb2.Response(check_unsaved_changes=True)
        if request.field == "list_all_behaviors":
            return behaviors_pb2.Response(
                list_all_behaviors=behaviors_pb2.ListAllBehaviorsResponse(behaviors=[11]))
        if request.field == "get_behavior_details":
            return behaviors_pb2.Response(get_behavior_details=_zmk_behavior())
        raise AssertionError(f"unexpected read: {request.field}")

    def close(self):
        self.closed = True


@pytest.mark.parametrize("method", ["device_info", "keymap", "physical_layouts"])
def test_a_read_returns_a_message_from_our_own_schema(method: str) -> None:
    answer = getattr(Keyboard(_FakeRpc()), method)()
    assert answer.DESCRIPTOR.file.name == OURS, (
        f"Keyboard.{method}() returned {answer.DESCRIPTOR.full_name}, which is "
        f"defined in {answer.DESCRIPTOR.file.name}")


def test_the_behavior_table_is_ours_too() -> None:
    table = Keyboard(_FakeRpc()).behaviors()
    assert set(table) == {11}
    assert table[11].DESCRIPTOR.file.name == OURS
    # The field whose two spellings the tool was reconciling by hand.
    assert table[11].parameter_sets


def test_every_name_the_model_exports_is_defined_by_our_schema() -> None:
    """`model` must not become a place that re-exports upstream by accident."""
    for name in model.__all__:
        thing = getattr(model, name)
        descriptor = getattr(thing, "DESCRIPTOR", None)
        file = descriptor.file.name if hasattr(descriptor, "file") else descriptor.name
        assert file == OURS, f"model.{name} comes from {file}"


# --------------------------------------------------------------------------- #
# claim 2: nothing is dropped crossing the boundary
# --------------------------------------------------------------------------- #

def _unset(message, prefix: str = "") -> list[str]:
    """Field paths left at their default after a translation from a full source.

    Fields inside a oneof are skipped: only one can be set, so their absence is not
    evidence of anything. They are covered by `_variants` instead.
    """
    missing: list[str] = []
    for field in message.DESCRIPTOR.fields:
        if field.containing_oneof is not None:
            continue
        path = f"{prefix}{field.name}"
        value = getattr(message, field.name)
        if field.is_repeated:
            if not value:
                missing.append(path)
            elif field.type == field.TYPE_MESSAGE:
                for index, item in enumerate(value):
                    missing += _unset(item, f"{path}[{index}].")
        elif field.type == field.TYPE_MESSAGE:
            if not message.HasField(field.name):
                missing.append(path)
            else:
                missing += _unset(value, f"{path}.")
        elif not value:
            missing.append(path)
    return missing


def _variants(message) -> set[str]:
    """Every oneof variant set anywhere in the tree, as `Message.variant`."""
    found: set[str] = set()
    for oneof in message.DESCRIPTOR.oneofs:
        chosen = message.WhichOneof(oneof.name)
        if chosen:
            found.add(f"{message.DESCRIPTOR.name}.{chosen}")
    for field in message.DESCRIPTOR.fields:
        if field.type != field.TYPE_MESSAGE:
            continue
        value = getattr(message, field.name)
        if field.is_repeated:
            for item in value:
                found |= _variants(item)
        elif message.HasField(field.name):
            found |= _variants(value)
    return found


@pytest.mark.parametrize("convert,source", [
    (_from_zmk.device_info, core_pb2.GetDeviceInfoResponse(
        name="Sofle", serial_number=b"\xde\xad\xbe\xef")),
    (_from_zmk.keymap, _zmk_keymap()),
    (_from_zmk.physical_layouts, _zmk_layouts()),
    (_from_zmk.behavior, _zmk_behavior()),
])
def test_translation_populates_every_field_of_the_model(convert, source) -> None:
    """Driven by the model's descriptors, so a new field fails until it is mapped.

    Every source above has all of its own fields set, so any model field still at
    its default afterwards was dropped on the way across.
    """
    assert _unset(convert(source)) == []


def test_every_parameter_kind_survives_translation() -> None:
    """The five oneof variants, copied one branch at a time in `_parameter_value`.

    Named individually rather than counted: a count passes when one branch is
    copied twice and another not at all.
    """
    assert _variants(_from_zmk.behavior(_zmk_behavior())) == {
        "ParameterValue.hid_usage", "ParameterValue.layer_id",
        "ParameterValue.range", "ParameterValue.constant",
        "ParameterValue.no_value",
    }


def test_the_completeness_check_would_notice_a_dropped_field() -> None:
    """Non-vacuity. Without this, the walk above could be returning [] for nothing."""
    full = _from_zmk.keymap(_zmk_keymap())
    assert _unset(full) == []
    full.layers[0].ClearField("name")
    assert _unset(full) == ["layers[0].name"]


# --------------------------------------------------------------------------- #
# claim 2a: the values arrive where they belong
# --------------------------------------------------------------------------- #
#
# Spelled out rather than walked. A descriptor walk proves nothing was left behind;
# only an expected value proves that `rotation_y` holds ry and not rx.

def test_a_keymap_arrives_field_for_field() -> None:
    assert _from_zmk.keymap(_zmk_keymap()) == model.Keymap(
        available_layers=9,
        max_layer_name_length=16,
        layers=[
            model.Layer(id=3, name="SYM", bindings=[
                model.Binding(behavior_id=11, param1=0x08070006, param2=5),
                model.Binding(behavior_id=12, param1=7, param2=8),
            ]),
            model.Layer(id=4, name="FUN", bindings=[
                model.Binding(behavior_id=13, param1=9, param2=10),
            ]),
        ])


def test_the_rotation_fields_are_not_crossed() -> None:
    """r, rx and ry, which upstream names in one letter each.

    Its `r` is the angle and its `rx`/`ry` are the centre it turns about. Three
    adjacent int32 fields with one-letter names: a crossed pair here would rotate
    every key about the wrong point and still look like valid geometry.
    """
    assert _from_zmk.physical_layouts(_zmk_layouts()) == model.PhysicalLayouts(
        active_index=1,
        layouts=[
            model.PhysicalLayout(name="Default", keys=[
                model.KeyPosition(x=3, y=4, width=1, height=2,
                                  rotation=5, rotation_x=6, rotation_y=7)]),
            model.PhysicalLayout(name="Split", keys=[
                model.KeyPosition(x=13, y=14, width=11, height=12,
                                  rotation=15, rotation_x=16, rotation_y=17)]),
        ])


def test_a_behavior_arrives_with_its_parameter_sets_in_order() -> None:
    """Order matters: `decode` tries the sets in sequence and takes the first that
    admits the bound values, so reordering them changes how a binding reads."""
    converted = _from_zmk.behavior(_zmk_behavior())
    assert converted.id == 11
    assert converted.display_name == "Mod-Tap"
    assert [(p.param1[0].name, p.param2[0].name) for p in converted.parameter_sets] == [
        ("Key", "Layer"), ("Profile", "Clear All Profiles"), ("Toggle", "Toggle")]
    assert converted.parameter_sets[0].param1[0].hid_usage == model.HidUsage(
        keyboard_max=0xE7, consumer_max=0x29D)
    assert converted.parameter_sets[1].param1[0].range == model.ValueRange(min=0, max=4)
    assert converted.parameter_sets[1].param2[0].constant == 3


def test_device_info_keeps_the_serial_raw() -> None:
    """Not hashed, not hex. What to do with an identifier is the consumer's policy,
    and a library that pre-digested it would make the raw form unreachable."""
    converted = _from_zmk.device_info(core_pb2.GetDeviceInfoResponse(
        name="Sofle", serial_number=b"\xde\xad\xbe\xef"))
    assert converted == model.DeviceInfo(name="Sofle", serial_number=b"\xde\xad\xbe\xef")

# --------------------------------------------------------------------------- #
# the two translations that refuse rather than guess
# --------------------------------------------------------------------------- #

def test_locked_is_not_spelled_as_unset() -> None:
    """Upstream's LOCKED is zero; ours is not, and that is the whole point.

    A zero-valued LOCKED means a field nobody set reads as a definite state - the
    same shape as reading an unset oneof branch and getting a valid empty message,
    which is how this project once shipped empty backups.
    """
    assert model.LockState.LOCK_STATE_UNSPECIFIED == 0
    assert _from_zmk.lock_state(core_pb2.ZMK_STUDIO_CORE_LOCK_STATE_LOCKED) == (
        model.LockState.LOCK_STATE_LOCKED)
    assert _from_zmk.lock_state(core_pb2.ZMK_STUDIO_CORE_LOCK_STATE_UNLOCKED) == (
        model.LockState.LOCK_STATE_UNLOCKED)
    assert model.LockState.LOCK_STATE_LOCKED != 0


def test_an_unknown_lock_state_raises_rather_than_reading_as_unknown() -> None:
    with pytest.raises(ValueError, match="refusing"):
        _from_zmk.lock_state(99)


def test_a_parameter_slot_with_no_declared_kind_is_carried_through() -> None:
    """Upstream permits a description that names a slot and declares nothing.

    Carried as a name with no kind, because that is what the keyboard said. The
    decoder downstream already treats an undeclared slot as undeclared.
    """
    source = behaviors_pb2.GetBehaviorDetailsResponse(
        id=1, display_name="Odd",
        metadata=[behaviors_pb2.BehaviorBindingParametersSet(
            param1=[behaviors_pb2.BehaviorParameterValueDescription(name="Mystery")])])
    converted = _from_zmk.behavior(source)
    slot = converted.parameter_sets[0].param1[0]
    assert slot.name == "Mystery"
    assert slot.WhichOneof("kind") is None
