"""L0: bytes to and from one keyboard. Nothing here knows what a keymap is.

The whole contract is three methods. `receive` promises only *some bytes, eventually*
- never a whole message - because Bluetooth delivers MTU-sized notifications with no
relation to message boundaries. A connection that promised whole messages would be
lying, and the lie would surface only under a long keymap on a weak signal. Reassembly
belongs one floor up, in `wire`, where it is a pure function that tests can feed one
byte at a time.

That is the trade this layer is built around: **it is the only code no test can
reach, so everything that can leave it, leaves.**

Two implementations, because how bytes physically move is owned by hardware and
operating systems. Discovery is a free function rather than a constructor: before
discovery there is no object, only a radio, and you cannot ask an object to find
itself.

Not yet implemented: raising when a live connection drops. The design calls for it -
a disconnect currently surfaces one floor up as "the keyboard did not answer", which
converts a failure we can identify into one we cannot - but adding it would change
behaviour, so it is a separate change from this move.
"""
from __future__ import annotations

import glob
import sys
import time
import typing

SERVICE_UUID = "00000000-0196-6107-c967-c5cfb1c2482a"
CHRC_UUID = "00000001-0196-6107-c967-c5cfb1c2482a"


class NotReachable(Exception):
    """No keyboard could be reached on any transport."""


class Connection(typing.Protocol):
    """A byte pipe to one keyboard.

    Deliberately not an abstract base class: the real implementations and any test
    double satisfy this by shape, with no inheritance and nothing to register.
    """

    def send(self, data: bytes) -> None:
        """Put bytes on the wire. Returns when they are handed off, not when answered."""

    def receive(self, timeout: float) -> bytes:
        """Whatever has arrived, which may be nothing, part of a frame, or several."""

    def close(self) -> None:
        """Release the transport. Never writes anything."""


class BleConnection:
    """Studio RPC over GATT, through CoreBluetooth on macOS.

    Constructed by `find_bluetooth`, which does the discovery; by the time this exists
    the peripheral is connected and the characteristic is subscribed.
    """

    def __init__(self, central, peripheral, delegate, mtu: int, core_bluetooth) -> None:
        self._central = central
        self._peripheral = peripheral
        self._delegate = delegate
        self._mtu = mtu
        self._CB = core_bluetooth

    def send(self, data: bytes) -> None:
        from Foundation import NSData

        for start in range(0, len(data), self._mtu):
            part = data[start:start + self._mtu]
            self._peripheral.writeValue_forCharacteristic_type_(
                NSData.dataWithBytes_length_(part, len(part)),
                self._delegate.chrc, self._CB.CBCharacteristicWriteWithResponse)

    def receive(self, timeout: float) -> bytes:
        # Capped at half a second so a caller's long deadline still yields often
        # enough for it to notice its own expiry.
        _pump_until(lambda: bool(self._delegate.inbox), max(0.05, min(timeout, 0.5)))
        out = b"".join(self._delegate.inbox)
        self._delegate.inbox.clear()
        return out

    def close(self) -> None:
        self._central.cancelPeripheralConnection_(self._peripheral)


class SerialConnection:
    """Studio RPC over the USB CDC port, used when the keyboard outputs via USB."""

    def __init__(self, port: str) -> None:
        import serial

        self._port = serial.Serial(port, 115200, timeout=0.2)

    def send(self, data: bytes) -> None:
        self._port.write(data)
        self._port.flush()

    def receive(self, timeout: float) -> bytes:
        return self._port.read(4096)

    def close(self) -> None:
        self._port.close()


def _pump_until(predicate, timeout: float) -> None:
    """Run CoreBluetooth's loop until `predicate` holds or the time is up.

    The adapter between a callback-driven stack and a synchronous `receive`. It is the
    most intricate code in this layer and the least testable, which is an uncomfortable
    pairing; it exists once, here, rather than being spread through the read path.
    """
    from Foundation import NSDate, NSRunLoop

    deadline = time.time() + timeout
    while not predicate() and time.time() < deadline:
        NSRunLoop.currentRunLoop().runUntilDate_(
            NSDate.dateWithTimeIntervalSinceNow_(0.05))


def find_bluetooth() -> Connection:
    """Find the connected keyboard and open a GATT connection to it.

    A keyboard already paired and connected as a HID device does not advertise, so
    scanners never see it. It has to be retrieved from CoreBluetooth's list of
    connected peripherals instead, which is why this is not a scan.
    """
    import objc
    from Foundation import NSObject
    import CoreBluetooth as CB

    class Delegate(NSObject):
        def init(self):
            self = objc.super(Delegate, self).init()
            self.powered = self.ready = False
            self.chrc = None
            self.inbox = []
            return self

        def centralManagerDidUpdateState_(self, central):
            self.powered = central.state() == CB.CBManagerStatePoweredOn

        def centralManager_didConnectPeripheral_(self, central, peripheral):
            peripheral.setDelegate_(self)
            peripheral.discoverServices_([CB.CBUUID.UUIDWithString_(SERVICE_UUID)])

        def peripheral_didDiscoverServices_(self, peripheral, error):
            for service in peripheral.services() or []:
                if service.UUID().UUIDString().lower() == SERVICE_UUID:
                    peripheral.discoverCharacteristics_forService_(
                        [CB.CBUUID.UUIDWithString_(CHRC_UUID)], service)

        def peripheral_didDiscoverCharacteristicsForService_error_(self, p, service, error):
            for chrc in service.characteristics() or []:
                if chrc.UUID().UUIDString().lower() == CHRC_UUID:
                    self.chrc = chrc
                    p.setNotifyValue_forCharacteristic_(True, chrc)

        def peripheral_didUpdateNotificationStateForCharacteristic_error_(self, p, c, error):
            self.ready = error is None

        def peripheral_didUpdateValueForCharacteristic_error_(self, p, chrc, error):
            if error is None and chrc.value() is not None:
                self.inbox.append(bytes(chrc.value()))

    delegate = Delegate.alloc().init()
    central = CB.CBCentralManager.alloc().initWithDelegate_queue_options_(
        delegate, None, None)
    _pump_until(lambda: delegate.powered, 5.0)
    if not delegate.powered:
        raise NotReachable("Bluetooth is off")

    peripherals = central.retrieveConnectedPeripheralsWithServices_(
        [CB.CBUUID.UUIDWithString_(SERVICE_UUID)])
    if not peripherals:
        raise NotReachable(
            "no connected keyboard exposes the Studio service - is it connected "
            "over Bluetooth, and is ZMK Studio closed?")

    peripheral = peripherals[0]
    central.connectPeripheral_options_(peripheral, None)
    _pump_until(lambda: delegate.ready, 15.0)
    if not delegate.ready:
        raise NotReachable("connected but could not subscribe to the RPC characteristic")

    mtu = max(int(peripheral.maximumWriteValueLengthForType_(
        CB.CBCharacteristicWriteWithResponse)), 20)
    return BleConnection(central, peripheral, delegate, mtu, CB)


def open_serial(port: str) -> Connection:
    """Open the USB CDC port. Does not check that a keyboard is listening on it."""
    return SerialConnection(port)


def serial_candidates() -> list[str]:
    """Ports that might be a keyboard, by Darwin's naming."""
    return glob.glob("/dev/cu.usbmodem*")


def require_supported_platform() -> None:
    """Both transports are Darwin-specific; say so before either fails obscurely.

    GATT needs CoreBluetooth, and the serial probe looks for /dev/cu.usbmodem*, which
    no other platform names that way. Left to themselves, the probe finds nothing and
    the GATT import fails, which together read as "your keyboard is unreachable".
    """
    if sys.platform != "darwin":
        raise NotReachable(
            f"macOS only, and this is {sys.platform}. The Bluetooth path needs "
            "CoreBluetooth; the serial probe looks for /dev/cu.usbmodem*, which is "
            "Darwin's naming (Linux uses /dev/ttyACM*, Windows a COM port). Nothing "
            "above this layer is platform-specific, so porting is a matter of adding "
            "a Connection.")
