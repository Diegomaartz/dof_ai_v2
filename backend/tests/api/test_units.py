"""Unit tests for SSE encoding, cancellation, rate parsing and client IP resolution."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from django.test import RequestFactory

from api.events import ChatEvent
from api.sse import encode_event, sse_stream
from api.throttle import Rate, client_ip


def test_encode_event_is_a_single_data_line() -> None:
    frame = encode_event(ChatEvent("token", {"text": "línea 1\nlínea 2"}))
    assert frame == 'event: token\ndata: {"text": "línea 1\\nlínea 2"}\n\n'


@pytest.mark.anyio
async def test_client_disconnect_cancels_the_agent() -> None:
    state = {"cancelled": False, "produced": 0}

    async def endless() -> AsyncIterator[ChatEvent]:
        try:
            while True:
                state["produced"] += 1
                yield ChatEvent("token", {"text": "x"})
                await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    stream = sse_stream(endless(), keepalive_seconds=5)
    assert (await anext(stream)).startswith("event: token")
    await stream.aclose()  # what the ASGI server does when the browser goes away
    await asyncio.sleep(0)
    assert state["cancelled"] is True
    produced = state["produced"]
    await asyncio.sleep(0.05)
    assert state["produced"] == produced  # nothing keeps running (and spending tokens) after the disconnect


@pytest.mark.parametrize(
    ("value", "rate"),
    [("10/minute", Rate(10, 60)), ("5/second", Rate(5, 1)), ("100/hours", Rate(100, 3600))],
)
def test_rate_parse(value: str, rate: Rate) -> None:
    assert Rate.parse(value) == rate


@pytest.mark.parametrize("value", ["10", "x/minute", "10/day"])
def test_rate_parse_rejects_bad_values(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid rate"):
        Rate.parse(value)


def test_client_ip_trusts_only_configured_proxy_hops() -> None:
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.7")
    assert client_ip(request, trusted_proxy_count=0) == "10.0.0.5"
    assert client_ip(request, trusted_proxy_count=1) == "203.0.113.7"  # appended by our proxy, not the client
    assert client_ip(request, trusted_proxy_count=3) == "10.0.0.5"  # fewer hops than expected: do not guess
