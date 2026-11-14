"""L1: whole messages over a connection that only carries bytes.

This is the layer that makes the connection's honesty affordable. `Connection.receive`
promises only *some bytes* - a 2,403-byte keymap response arrives across ten to
fourteen notifications, or 121 at the minimum MTU - and everything above here wants
one complete message at a time.

Framing and encoding live together rather than as two floors. Nobody wants a frame
that is not a message: the only consumer of a frame is the parser, and the only
producer of bytes worth framing is the serialiser. They are also not different
domains - byte stuffing and protobuf are both ZMK Studio's choices, arriving together
and changing together.

`FrameReader` stays a class of its own, tested on its own, just not a public one. A
clean boundary on the outside does not require a flat interior.

What this layer does NOT do is decide whether a message is *yours*. It has no idea
what you asked; `send` and `receive` are independent operations with no relationship
between them. Correlation is `rpc`'s job, one floor up.
"""
from __future__ import annotations

import time
import typing

from .connection import Connection
from ._pb import studio_pb2

#: Frame delimiters. A payload byte equal to any of these is escaped, which is why a
#: 2,403-byte response frames to 2,413 rather than 2,405.
SOF, ESC, EOF = 0xAB, 0xAC, 0xAD


def frame(payload: bytes) -> bytes:
    """Wrap a serialised message in the transport framing."""
    out = bytearray([SOF])
    for byte in payload:
        if byte in (SOF, ESC, EOF):
            out.append(ESC)
        out.append(byte)
    out.append(EOF)
    return bytes(out)


class FrameReader:
    """Reassembles frames from an arbitrarily chunked byte stream.

    Bytes arrive split across MTU-sized GATT indications or serial reads with no
    relationship to frame boundaries, so feed() accepts any chunking and returns
    whole frames only. Malformed input resynchronises at the next SOF rather than
    raising, because a partial frame is not worth failing a dump over.
    """

    _IDLE, _DATA, _ESCAPED = 0, 1, 2

    def __init__(self) -> None:
        self._state = self._IDLE
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        for byte in data:
            if self._state == self._IDLE:
                if byte == SOF:
                    self._state, self._buf = self._DATA, bytearray()
            elif self._state == self._DATA:
                if byte == ESC:
                    self._state = self._ESCAPED
                elif byte == EOF:
                    frames.append(bytes(self._buf))
                    self._state = self._IDLE
                elif byte == SOF:
                    self._buf = bytearray()  # unescaped SOF: start over
                else:
                    self._buf.append(byte)
            else:
                self._buf.append(byte)
                self._state = self._DATA
        return frames


class Wire:
    """Whole messages over a connection that only carries bytes.

    Holds the only two buffers in the stack: the partial frame that does not yet
    complete a message, and completed messages not yet handed over - because one
    chunk can end one frame and begin another, or contain three.

    A concrete class, not a Protocol. There is exactly one ZMK Studio wire format, so
    there is exactly one Wire; substitution happens at the Connection below it, where
    a test can hand back one byte at a time and this code runs for real.
    """

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
        self._reader = FrameReader()
        self._ready: list[typing.Any] = []

    def send(self, message: typing.Any) -> None:
        """Serialise, frame, and put it on the wire. Waits for nothing."""
        self._connection.send(frame(message.SerializeToString()))

    def receive(self, timeout: float) -> typing.Any | None:
        """The next complete message, or None if none arrived in time.

        Whatever arrived - the answer to your question, the answer to someone else's,
        or an unsolicited notification. Telling those apart is not this layer's job.
        """
        if self._ready:
            return self._ready.pop(0)
        deadline = time.time() + timeout
        while time.time() < deadline:
            for payload in self._reader.feed(
                    self._connection.receive(deadline - time.time())):
                message = studio_pb2.Response()
                try:
                    message.ParseFromString(payload)
                except Exception:
                    # A frame that is not a message. Dropped, and the caller's
                    # deadline keeps running - whether silence is the right answer
                    # on the write path is an open question.
                    continue
                self._ready.append(message)
            if self._ready:
                return self._ready.pop(0)
        return None

    def close(self) -> None:
        self._connection.close()
