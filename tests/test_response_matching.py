"""Responses are matched on subsystem as well as request id.

Both cases here were silent failures before: the keyboard said one thing and the caller
read another, with no exception and no diagnostic. Each test asserts on what a caller
would actually have got, because that is where the damage was - a snapshot with no
layers in it, written over the last good one, exit code 0.
"""
from __future__ import annotations

import pytest

from zmk_studio_client import reads, rpc
from zmk_studio_client._pb import meta_pb2, studio_pb2


def _read(subsystem: str = "keymap", field: str = "get_keymap") -> reads.ReadRequest:
    """A request to match against, with its id fixed for the assertions below."""
    request = reads.ReadRequest(subsystem, field)
    request.message.request_id = 1
    return request


def _response(request_id: int, subsystem: str, populate=None):
    """A parsed Response, which is what `Wire` hands up. Parsing is the wire's job."""
    resp = studio_pb2.Response()
    resp.request_response.request_id = request_id
    target = getattr(resp.request_response, subsystem)
    if populate is None:
        target.SetInParent()
    else:
        populate(target)
    return resp


def _unlock_required(request_id: int = 1):
    return _response(
        request_id, "meta",
        lambda meta: setattr(meta, "simple_error", meta_pb2.UNLOCK_REQUIRED))


def test_a_locked_keyboard_raises_instead_of_yielding_an_empty_keymap() -> None:
    with pytest.raises(rpc.KeyboardLocked) as caught:
        rpc.match_response(_unlock_required(), _read())
    assert "unlock" in str(caught.value).lower()


def test_the_empty_keymap_this_guards_against_is_real() -> None:
    """Why the subsystem check is needed at all, rather than a meta special case.

    Reading an unset branch of a proto3 oneof yields a default instance, so the error
    response above is indistinguishable from a successful one to a caller that only
    reaches for the field it asked about.
    """
    parsed = _unlock_required()
    assert parsed.request_response.WhichOneof("subsystem") == "meta"
    assert len(parsed.request_response.keymap.get_keymap.layers) == 0


def test_a_generic_error_is_reported_not_swallowed() -> None:
    raw = _response(
        1, "meta",
        lambda meta: setattr(meta, "simple_error", meta_pb2.MSG_DECODE_FAILED))
    with pytest.raises(rpc.RpcError) as caught:
        rpc.match_response(raw, _read())
    assert "MSG_DECODE_FAILED" in str(caught.value)


def test_no_response_is_reported_not_swallowed() -> None:
    raw = _response(1, "meta", lambda meta: setattr(meta, "no_response", True))
    with pytest.raises(rpc.RpcError):
        rpc.match_response(raw, _read())


def test_a_reply_on_another_subsystem_does_not_satisfy_the_request() -> None:
    """The case that needs no locked keyboard.

    request_id is a per-process counter starting at 1, so a reply still in flight from
    an earlier run carries the id this run is waiting for. Matching on the id alone
    handed it back, and `.keymap.get_keymap` on a core response is an empty keymap.
    """
    raw = _response(1, "core", lambda core: core.get_device_info.SetInParent())
    assert rpc.match_response(raw, _read()) is None


def test_the_right_subsystem_still_matches() -> None:
    request = _read()
    raw = _response(request.request_id, "keymap",
                    lambda keymap: keymap.get_keymap.SetInParent())
    matched = rpc.match_response(raw, request)
    assert matched is not None
    assert matched.request_id == request.request_id


def test_another_request_id_is_ignored() -> None:
    raw = _response(2, "keymap", lambda keymap: keymap.get_keymap.SetInParent())
    assert rpc.match_response(raw, _read()) is None


def test_a_notification_is_ignored() -> None:
    resp = studio_pb2.Response()
    resp.notification.keymap.unsaved_changes_status_changed = True
    assert rpc.match_response(resp, _read()) is None


def test_nothing_arriving_is_ignored() -> None:
    """`Wire.receive` returns None when the timeout expires with no message.

    Unparseable bytes no longer reach here at all: the wire drops a frame that is not
    a message, which is where that decision belongs now. See tests/test_wire.py.
    """
    assert rpc.match_response(None, _read()) is None
