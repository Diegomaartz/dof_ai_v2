"""Server-Sent Events encoding with keep-alive pings and safe cancellation."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator

from api.events import UNAVAILABLE_MESSAGE, ChatEvent

logger = logging.getLogger(__name__)

PING = ": ping\n\n"

_DONE = object()


def encode_event(event: ChatEvent) -> str:
    """One SSE frame. JSON never contains raw newlines, so a single ``data:`` line is always valid."""
    return f"event: {event.name}\ndata: {json.dumps(event.data, ensure_ascii=False)}\n\n"


async def sse_stream(events: AsyncIterator[ChatEvent], keepalive_seconds: float) -> AsyncIterator[str]:
    """Encode ``events`` as SSE frames, emitting a comment ping whenever the agent is silent for a while.

    Grading and query rewriting can take many seconds without output; the pings keep proxies and load
    balancers from closing the connection. An exception in the agent becomes a final ``error`` frame. If the
    client disconnects, the server closes this generator and the agent task is cancelled, so no further
    Bedrock tokens are spent.
    """
    queue: asyncio.Queue[object] = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except Exception:
            logger.exception("Chat agent run failed")
            await queue.put(ChatEvent("error", {"code": "agent_unavailable", "message": UNAVAILABLE_MESSAGE}))
        finally:
            await queue.put(_DONE)

    producer = asyncio.create_task(produce())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive_seconds)
            except TimeoutError:
                yield PING
                continue
            if item is _DONE:
                break
            assert isinstance(item, ChatEvent)
            yield encode_event(item)
    finally:
        producer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await producer
