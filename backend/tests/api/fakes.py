"""Agent stand-ins for the API tests, selected through ``settings.DOF_AGENT_FACTORY``."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from tests.agent.conftest import Harness


class _Holder:
    graph: Any = None


current = _Holder()


def build_fake_agent() -> Any:
    """Factory referenced by ``core.settings_test.DOF_AGENT_FACTORY``; returns the graph a test installed."""
    if current.graph is None:
        raise RuntimeError("No fake agent installed for this test")
    return current.graph


def install(harness_or_graph: Harness | Any) -> Any:
    current.graph = harness_or_graph.graph if isinstance(harness_or_graph, Harness) else harness_or_graph
    return harness_or_graph


def build_failing_factory() -> Any:
    raise RuntimeError("BEDROCK_CHAT_MODEL_ID is not set (secret detail that must not reach clients)")


class ExplodingGraph:
    """Streams a status and two tokens, then fails like a Bedrock throttling error mid-answer."""

    async def astream(self, state: dict[str, Any], stream_mode: list[str]) -> AsyncIterator[tuple[str, Any]]:
        yield "tasks", {"name": "generate_node", "input": state}
        for text in ("La jornada", " diurna"):
            yield "messages", (_Chunk(text), {"langgraph_node": "generate_node"})
        raise RuntimeError("ThrottlingException: internal detail")


class SlowGraph:
    """Stays silent for a while before answering, to exercise SSE keep-alive pings."""

    def __init__(self, delay: float) -> None:
        self.delay = delay

    async def astream(self, state: dict[str, Any], stream_mode: list[str]) -> AsyncIterator[tuple[str, Any]]:
        await asyncio.sleep(self.delay)
        yield "values", {"answer": "No se encontró sustento legal en las fuentes consultadas.", "refused": True}


class _Chunk:
    def __init__(self, text: str) -> None:
        self.text = text
