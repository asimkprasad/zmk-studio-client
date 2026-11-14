"""L3: one request, its answer, and nothing else.

`Wire` hands back whatever message arrived - the answer to your question, the answer
to someone else's, or an unsolicited notification. It has no idea what you asked;
send and receive are independent operations down there. This layer invents the
pairing, and discarding everything that is not yours is the whole job.

It is also where the only genuinely dangerous bug in the stack is prevented. See
`match_response`.

A concrete class, not a Protocol. An async or a pipelining version can be named, but
neither is substitutable behind this contract - async changes every caller's
signature, and pipelining retires the promise that a call returns before the next is
sent. They would be rewrites wearing the same name.
"""
from __future__ import annotations

import time
import typing

from ._pb import meta_pb2
from .wire import Wire


class KeyboardLocked(Exception):
    """The keyboard refused because ZMK Studio has not been unlocked."""


class RpcError(Exception):
    """The keyboard answered with a protocol-level error instead of the data asked for."""


class Rpc:
    """Sends one request and returns the response that answers it."""

    def __init__(self, wire: Wire) -> None:
        self._wire = wire
        self._next_id = 0

    def call(self, request: typing.Any, timeout: float = 10.0) -> typing.Any:
        """Send `request` and return the subsystem response that answers it.

        Returns the *subsystem* payload - a keymap.Response, a core.Response - not the
        studio envelope, which has been checked and discarded by then. Which subsystem
        comes back depends on which went out, so the return type varies with the
        argument in a way one annotation cannot express.

        The deadline spans the whole call rather than each receive, so discarding ten
        unmatched messages cannot stretch a ten second timeout into a hundred.
        """
        request.message.request_id = self._take_id()
        self._wire.send(request.message)
        deadline = time.time() + timeout
        while time.time() < deadline:
            matched = match_response(self._wire.receive(deadline - time.time()), request)
            if matched is not None:
                return getattr(matched, request.subsystem)
        raise TimeoutError(
            f"keyboard did not answer {request.subsystem}.{request.field}")

    def close(self) -> None:
        self._wire.close()

    def _take_id(self) -> int:
        """Allocate this connection's next request id.

        The counter belongs to the connection, not to a module: two keyboards open at
        once get independent sequences, and a request is a value describing what you
        want rather than an object carrying a number nobody chose.
        """
        self._next_id += 1
        return self._next_id


def match_response(resp, request):
    """Return the RequestResponse answering `request`, or None for anything else.

    Notifications and responses to other requests are discarded here so callers never
    have to reason about the keyboard's unsolicited traffic.

    Matching on the subsystem as well as the id is what keeps a failure loud. A
    RequestResponse carries its payload in a oneof, and reading an unset branch of a
    proto3 oneof yields a default instance rather than raising - so a reply on the
    `meta` subsystem, which is how the keyboard reports UNLOCK_REQUIRED, would be
    handed back to a caller reaching for `.keymap.get_keymap` as a keymap with no
    layers in it. An error would become an empty result: no exception, no log, a
    valid-looking empty message handed back to the caller.

    The id alone cannot tell the two apart for a second reason. It is a per-connection
    counter, so a reply left over from an earlier run can legitimately carry the id
    this run is waiting for; such a reply is discarded here and the caller keeps
    waiting.
    """
    if resp is None or resp.WhichOneof("type") != "request_response":
        return None
    rr = resp.request_response
    if rr.request_id != request.request_id:
        return None
    answered = rr.WhichOneof("subsystem")
    if answered == "meta":
        raise _meta_error(rr.meta, f"{request.subsystem}.{request.field}")
    if answered != request.subsystem:
        return None
    return rr


def _meta_error(meta, expect: str) -> Exception:
    """Translate a meta response into the exception it stands for."""
    if meta.WhichOneof("response_type") == "simple_error":
        if meta.simple_error == meta_pb2.UNLOCK_REQUIRED:
            return KeyboardLocked(
                "the keyboard is locked, so it will not answer secured requests. Unlock it "
                "with ZMK Studio's unlock gesture (the &studio_unlock behavior), close "
                "Studio, and try again. The protocol has no unlock request, so "
                "a client cannot do it for you.")
        condition = meta_pb2.ErrorConditions.Name(meta.simple_error)
        return RpcError(f"the keyboard rejected {expect}: {condition}")
    return RpcError(f"the keyboard returned no response to {expect}")
