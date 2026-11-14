# zmk-studio-client

A Python client for the [ZMK Studio RPC protocol](https://zmk.dev/docs/development/studio-rpc-protocol) —
the protocol ZMK Studio itself speaks to a running keyboard over USB serial or Bluetooth GATT.

**Unofficial.** Not affiliated with, endorsed by, or maintained by the ZMK project. The
protocol definitions it generates from are ZMK's, at
[`zmkfirmware/zmk-studio-messages`](https://github.com/zmkfirmware/zmk-studio-messages).

## What it is

A connected keyboard, and everything you can ask it:

```python
from zmk_studio_client import connect

keyboard = connect()
try:
    keymap = keyboard.keymap()          # zmk_studio_client.model.Keymap
    print(len(keymap.layers))
finally:
    keyboard.close()
```

Everything a keyboard hands back is defined by this library, in
[`keyboard.proto`](src/zmk_studio_client/proto/keyboard.proto), and reachable as
`zmk_studio_client.model`. ZMK's own generated messages stop at the RPC floor and
never cross the boundary, so a consumer is not coupled to the shape of a protocol
it did not ask about, and never has to regenerate bindings from someone else's
repository to name a type. The schema ships in the wheel, so a client in another
language can generate from it directly.

Writing is a separate door, named at the call site:

```python
from zmk_studio_client.writable import connect_writable

keyboard = connect_writable()
try:
    edit = keyboard.edit()
    edit.set_binding(layer_id=0, position=13, behavior_id=0, param1=0x70004)
    edit.save()          # explicit; nothing commits on its own
finally:
    keyboard.close()
```

## What it is not

It does not read or write `.keymap` files, and it does not compile firmware. A `.keymap`
file is devicetree, consumed at build time. This talks to a keyboard that is already
running, over the same RPC ZMK Studio uses, and changes land in the settings partition —
no reflash.

It is also not a backup tool. It returns a model; what you do with it is yours.

## Connecting

Unlock the keyboard first (`&studio_unlock`), and close ZMK Studio so the port or
GATT session is free. A locked keyboard answers `device_info()` and `lock_state()`;
every other read and every write raises `KeyboardLocked`.

`connect()` and `connect_writable()` are **macOS only**: USB serial discovery looks
for `/dev/cu.usbmodem*`, and Bluetooth GATT goes through `CoreBluetooth`. Nothing
above [`connection.py`](src/zmk_studio_client/connection.py) is platform-specific —
on Linux or Windows, pass any three-method `Connection` (`send`, `receive`, `close`)
to `Keyboard(Rpc(Wire(conn)))`.

## Status

Early, and the API will move. What is settled: the reads return model messages, the
model is versioned (`zmk_studio_client.v1`), and `_pb` is private.

Known gaps, each deliberate rather than overlooked:

- Writing is limited to key bindings (`set_layer_binding`, `save_changes`,
  `discard_changes`). Adding, removing, moving or renaming layers, switching the
  active physical layout, locking Studio, and resetting settings are refused with
  `WriteRefused`.
- A dropped connection surfaces as whatever the transport raised. There is no
  `ConnectionLost`.
- Encoders are absent, because the protocol has no sensor bindings at all. No
  client built on this RPC can capture rotary encoder behaviour.
- The model describes a keymap, not a firmware: a behaviour's tapping-term, flavor
  and hold-trigger settings are not reported by the protocol and so are not here.

## Licence

MIT — see [`LICENSE`](LICENSE). The vendored protocol definitions under
[`src/third_party/zmk_studio_messages/`](src/third_party/zmk_studio_messages/) and
the bindings generated from them carry ZMK's MIT licence
(`Copyright (c) 2024 The ZMK Contributors`).
