"""Reaching the keyboard: the parts that can be checked without one.

Only connect()'s control flow is testable here. Opening a port or a CoreBluetooth
connection is the one thing no test can do, which is why those two live alone in
zmk_studio_client/connection.py and everything else lives above them.
"""
from __future__ import annotations

import pytest

import zmk_studio_client
from zmk_studio_client import connection


def test_a_non_darwin_host_is_told_why_rather_than_blamed(monkeypatch) -> None:
    """The README claims macOS only; connect() has to say the same thing.

    Without this the serial glob matches nothing, the GATT import fails, and the two
    together are reported as the keyboard being unreachable - which sends a Linux user
    looking at their cable.
    """
    monkeypatch.setattr(connection.sys, "platform", "linux")
    with pytest.raises(zmk_studio_client.NotReachable) as caught:
        zmk_studio_client.connect()
    message = str(caught.value)
    assert "macOS only" in message
    assert "ttyACM" in message


def test_the_documented_custom_connection_stack_is_exported_at_top_level() -> None:
    """README tells non-macOS callers to build `Keyboard(Rpc(Wire(conn)))`."""
    from zmk_studio_client import Connection, Keyboard, Rpc, Wire

    for symbol in ("Connection", "Keyboard", "Rpc", "Wire"):
        assert symbol in zmk_studio_client.__all__

    class DummyPipe:
        def send(self, data: bytes) -> None: pass
        def receive(self, timeout: float) -> bytes: return b""
        def close(self) -> None: pass

    pipe: Connection = DummyPipe()
    kb = Keyboard(Rpc(Wire(pipe)))
    kb.close()
