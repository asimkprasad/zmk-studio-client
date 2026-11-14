"""The one place that sees both ZMK's messages and ours.

Every read on `Keyboard` passes its answer through a function here. Keeping the
translation in a single module is what makes the boundary checkable: if ZMK renames
a field or renumbers an enum, exactly one file stops compiling against reality, and
`tests/test_model.py` fails rather than a consumer silently receiving a default.

The translation is never a copy. Each difference below was a decision, and the
reason is recorded beside it rather than in a commit message nobody will find.
"""
from __future__ import annotations

from . import model
from ._pb import core_pb2

#: Upstream spells the locked state as its zero value, so an unset field and a
#: locked keyboard are indistinguishable. Ours separates them. Written as a table
#: rather than an arithmetic shift because the two enums are not parallel and
#: never will be: UNSPECIFIED has no upstream counterpart by design.
_LOCK_STATES = {
    core_pb2.ZMK_STUDIO_CORE_LOCK_STATE_LOCKED: model.LockState.LOCK_STATE_LOCKED,
    core_pb2.ZMK_STUDIO_CORE_LOCK_STATE_UNLOCKED: model.LockState.LOCK_STATE_UNLOCKED,
}


def device_info(response) -> model.DeviceInfo:
    return model.DeviceInfo(name=response.name, serial_number=response.serial_number)


def lock_state(value) -> model.LockState:
    """Translate, and refuse to guess.

    An unrecognised value means upstream added a lock state this build has never
    heard of. Returning UNSPECIFIED would be a silent downgrade to "nobody
    answered", which is exactly the shape of failure this library keeps finding:
    valid-looking output, no error, exit 0. So it raises.
    """
    try:
        return _LOCK_STATES[value]
    except KeyError:
        raise ValueError(
            f"keyboard reported lock state {value}, which these message "
            f"definitions do not define; refusing to report it as unknown") from None


def keymap(response) -> model.Keymap:
    out = model.Keymap(
        available_layers=response.available_layers,
        max_layer_name_length=response.max_layer_name_length)
    for layer in response.layers:
        # Bindings keep their order because the order IS the key position, in both
        # shapes. Nothing here sorts, filters or compacts them: dropping one would
        # shift every key after it onto the wrong position.
        out.layers.add(
            id=layer.id,
            name=layer.name,
            bindings=[
                model.Binding(behavior_id=b.behavior_id, param1=b.param1, param2=b.param2)
                for b in layer.bindings
            ])
    return out


def physical_layouts(response) -> model.PhysicalLayouts:
    out = model.PhysicalLayouts(active_index=response.active_layout_index)
    for layout in response.layouts:
        out.layouts.add(
            name=layout.name,
            keys=[
                # r, rx and ry spelled out. The only place in the library that has
                # to know which of the three one-letter fields is the angle.
                model.KeyPosition(
                    x=key.x, y=key.y, width=key.width, height=key.height,
                    rotation=key.r, rotation_x=key.rx, rotation_y=key.ry)
                for key in layout.keys
            ])
    return out


def behavior(response) -> model.Behavior:
    """One entry of the behavior table, from `GetBehaviorDetailsResponse`.

    `metadata` becomes `parameter_sets`. This rename is the reason the model exists
    at all: a consumer downstream was converting between the two spellings by hand,
    in a function whose docstring warned that the shapes "are NOT interchangeable
    and the difference is easy to miss" - because both carry `id` and
    `display_name` and differ only in the field that decides how a binding reads.
    """
    out = model.Behavior(id=response.id, display_name=response.display_name)
    for source in response.metadata:
        target = out.parameter_sets.add()
        for described in source.param1:
            _parameter_value(described, target.param1.add())
        for described in source.param2:
            _parameter_value(described, target.param2.add())
    return out


def _parameter_value(source, target) -> None:
    """Copy one parameter description, preserving which oneof variant is set.

    Field by field, because a oneof cannot be assigned wholesale and because the
    variant names differ: upstream's `nil` is our `no_value`, and its `value_type`
    is our `kind`.

    An unrecognised variant raises for the same reason `lock_state` does. The
    alternative - a `ParameterValue` carrying a name and no kind - would decode as
    a behavior whose parameters nobody declared, which renders every binding
    through the fallback and says nothing about why.
    """
    target.name = source.name
    variant = source.WhichOneof("value_type")
    if variant == "constant":
        target.constant = source.constant
    elif variant == "range":
        target.range.min = source.range.min
        target.range.max = source.range.max
    elif variant == "hid_usage":
        target.hid_usage.keyboard_max = source.hid_usage.keyboard_max
        target.hid_usage.consumer_max = source.hid_usage.consumer_max
    elif variant == "layer_id":
        target.layer_id.SetInParent()
    elif variant == "nil":
        target.no_value.SetInParent()
    elif variant is None:
        # A description that declares no kind. Upstream permits it; it means the
        # keyboard named a slot without saying what goes in it. Carried through as
        # a name with no kind, which is what it is.
        pass
    else:
        raise ValueError(
            f"behavior parameter {source.name!r} declares kind {variant!r}, which "
            f"these message definitions do not define")
