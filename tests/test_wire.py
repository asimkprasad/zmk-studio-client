"""Whole messages out of a stream that promises nothing.

This file is the reason the wire is a layer rather than part of the connection or
part of rpc. Every case below is about bytes arriving in a shape nobody chose, and
none of them mentions a request, a reply or a timeout on an answer - that vocabulary
belongs one floor up.

The fake connection hands back one byte at a time, which is the pathological chunking
no real Bluetooth stack would produce and no hardware test could provoke.
"""
from __future__ import annotations

from zmk_studio_client._pb import keymap_pb2, studio_pb2
from zmk_studio_client.wire import SOF, FrameReader, Wire, frame


class Trickle:
    """A connection that returns the stream one byte per call."""

    def __init__(self, data: bytes = b"") -> None:
        self.outbox = bytearray(data)
        self.sent = bytearray()

    def send(self, data: bytes) -> None:
        self.sent.extend(data)

    def receive(self, timeout: float) -> bytes:
        if not self.outbox:
            return b""
        return bytes([self.outbox.pop(0)])

    def close(self) -> None:
        pass


class AllAtOnce(Trickle):
    """The other extreme: everything in a single read."""

    def receive(self, timeout: float) -> bytes:
        out, self.outbox = bytes(self.outbox), bytearray()
        return out


def _response(request_id: int = 1, layers: int = 0) -> studio_pb2.Response:
    resp = studio_pb2.Response()
    resp.request_response.request_id = request_id
    keymap = resp.request_response.keymap.get_keymap
    for index in range(layers):
        keymap.layers.add(id=index, name=f"L{index}")
    return resp


# --------------------------------------------------------------------------- #
# reassembly: the reason this layer exists
# --------------------------------------------------------------------------- #

def test_a_message_split_across_single_byte_reads_arrives_whole() -> None:
    """The connection may return one byte at a time and must still work."""
    wanted = _response(7, layers=6)
    wire = Wire(Trickle(frame(wanted.SerializeToString())))
    got = wire.receive(5.0)
    assert got is not None
    assert got.request_response.request_id == 7
    assert len(got.request_response.keymap.get_keymap.layers) == 6


def test_three_messages_in_one_read_are_delivered_one_at_a_time() -> None:
    """A chunk can end one frame and contain two more. None may be lost."""
    stream = b"".join(frame(_response(i).SerializeToString()) for i in (1, 2, 3))
    wire = Wire(AllAtOnce(stream))
    assert [wire.receive(1.0).request_response.request_id for _ in range(3)] == [1, 2, 3]


def test_a_buffered_message_is_returned_without_touching_the_connection() -> None:
    """The second of two frames must not need more bytes to arrive."""
    stream = b"".join(frame(_response(i).SerializeToString()) for i in (1, 2))
    connection = AllAtOnce(stream)
    wire = Wire(connection)
    wire.receive(1.0)
    assert not connection.outbox          # everything already consumed
    assert wire.receive(0.0).request_response.request_id == 2


def test_a_payload_containing_a_frame_marker_survives() -> None:
    """A keymap really does contain 0xAB bytes; escaping is not hypothetical."""
    wanted = _response(1)
    wanted.request_response.keymap.get_keymap.layers.add(
        id=0, name="«¬­")
    raw = wanted.SerializeToString()
    assert SOF in raw, "this test is pointless unless the payload needs escaping"
    framed = frame(raw)
    assert len(framed) > len(raw) + 2, "no escaping happened"
    got = Wire(Trickle(framed)).receive(5.0)
    assert got.request_response.keymap.get_keymap.layers[0].name == "«¬­"


def test_an_incomplete_frame_yields_nothing_rather_than_half_a_message() -> None:
    truncated = frame(_response(1, layers=3).SerializeToString())[:-5]
    assert Wire(Trickle(truncated)).receive(0.3) is None


def test_nothing_arriving_returns_none() -> None:
    assert Wire(Trickle(b"")).receive(0.1) is None


def test_a_frame_that_is_not_a_message_is_dropped_and_the_next_one_read() -> None:
    """A corrupt frame is skipped silently and the stream resynchronises.

    Recorded as the current behaviour, not as an endorsement - on the write path a
    dropped reply becomes a timeout rather than a distinct transport error.
    """
    stream = frame(b"\x08\xff\xff\xff\xff\xff\xff") + frame(_response(9).SerializeToString())
    got = Wire(AllAtOnce(stream)).receive(1.0)
    assert got is not None and got.request_response.request_id == 9


# --------------------------------------------------------------------------- #
# sending
# --------------------------------------------------------------------------- #

def test_send_frames_the_message() -> None:
    connection = Trickle()
    request = studio_pb2.Request(request_id=4)
    request.keymap.get_keymap = True
    Wire(connection).send(request)
    assert bytes(connection.sent) == frame(request.SerializeToString())


def test_send_waits_for_nothing() -> None:
    """send and receive are independent; nothing here pairs them."""
    connection = Trickle()
    wire = Wire(connection)
    for _ in range(3):
        wire.send(studio_pb2.Request(request_id=1))
    assert len(connection.sent) > 0        # three requests out, no reply needed


# --------------------------------------------------------------------------- #
# the frame reader on its own
# --------------------------------------------------------------------------- #

def test_the_reader_resynchronises_after_junk() -> None:
    reader = FrameReader()
    assert reader.feed(b"\x01\x02\x03") == []          # no SOF yet: ignored
    assert reader.feed(frame(b"hello")) == [b"hello"]


def test_the_reader_restarts_on_an_unescaped_start_byte() -> None:
    reader = FrameReader()
    assert reader.feed(bytes([SOF]) + b"junk" + frame(b"good")) == [b"good"]


def test_the_reader_accepts_any_chunking() -> None:
    payload = bytes(range(256)) * 4
    framed = frame(payload)
    reader = FrameReader()
    out = []
    for index in range(0, len(framed), 7):
        out.extend(reader.feed(framed[index:index + 7]))
    assert out == [payload]
