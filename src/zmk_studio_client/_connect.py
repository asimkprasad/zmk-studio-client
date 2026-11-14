"""Finding a transport that answers, and handing back an Rpc on it.

The ZMK firmware runs the RPC on whichever endpoint the keyboard currently outputs
through: serial when it is on USB, GATT when it is on Bluetooth. A keyboard set to
Bluetooth will not answer on its USB serial port at all. This module hides that by
trying what is present and reporting plainly when nothing answers.

**Why it returns an Rpc and not a Keyboard.** The shallow reason is that
`zmk_studio_client/__init__.py` imports this module to build `connect()`, so importing
Keyboard back would be a cycle. The real reason is that a Keyboard would be the
wrong answer: both doors - the one that can only read and the one that can also
write - need this same probe, and a probe that returned a Keyboard would force the
writable door to take a read-only object and promote it. Handing back the floor
below lets each door build its own thing, and neither has to know the other exists.

So the probe speaks Rpc, which is also the honest altitude for the question it
asks. "Does anything answer on this port" is not a question about keyboards.
"""
from __future__ import annotations

from .connection import (
    NotReachable,
    find_bluetooth,
    open_serial,
    require_supported_platform,
    serial_candidates,
)
from .reads import ReadRequest, WriteAttempted
from .rpc import KeyboardLocked, Rpc
from .wire import Wire

#: The probe. Cheap on purpose: a keyboard that is on Bluetooth leaves its USB port
#: present but silent, so this has to time out rather than answer, once per candidate.
_PROBE = ReadRequest("core", "get_device_info")
_PROBE_TIMEOUT = 2.0


def open_rpc() -> Rpc:
    """Open an Rpc to the keyboard over whichever transport replies.

    Serial is tried first because it is cheap to rule out: if the keyboard is on
    Bluetooth the port exists but never replies, so a short probe falls through to
    GATT without the caller needing to know which endpoint is active.

    WriteAttempted and KeyboardLocked are re-raised rather than collected: neither
    says anything about whether the keyboard is reachable, and reporting either as a
    connection failure would hide the real cause behind NotReachable.
    """
    require_supported_platform()

    failures = []
    for port in serial_candidates():
        rpc = None
        try:
            rpc = Rpc(Wire(open_serial(port)))
            rpc.call(_PROBE, _PROBE_TIMEOUT)
            return rpc
        except Exception as exc:
            _release(rpc)
            if isinstance(exc, (WriteAttempted, KeyboardLocked)):
                raise
            failures.append(f"serial {port}: {exc}")
    try:
        return Rpc(Wire(find_bluetooth()))
    except (WriteAttempted, KeyboardLocked):
        raise
    except Exception as exc:
        failures.append(f"bluetooth: {exc}")
    raise NotReachable("could not reach the keyboard.\n  " + "\n  ".join(failures))


def _release(rpc) -> None:
    """Close an Rpc that failed to come up, ignoring any further failure.

    One whose constructor raised holds no port, hence the None check; one whose probe
    timed out holds a claim that has to be given back before the next candidate is
    tried, or a later run finds its own earlier process still holding the port.
    """
    if rpc is None:
        return
    try:
        rpc.close()
    except Exception:
        pass
