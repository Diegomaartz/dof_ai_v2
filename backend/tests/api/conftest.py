from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import cache

from api.runtime import reset_agents
from tests.api import fakes


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate() -> Iterator[None]:
    """Fresh agent cache, fake slot and rate-limit counters for every test."""
    reset_agents()
    cache.clear()
    fakes.current.graph = None
    yield
    reset_agents()
    cache.clear()


def parse_sse(raw: str) -> list[tuple[str, Any]]:
    """Split an SSE body into ``(event, data)`` pairs; comment frames become ``(":", text)``."""
    events: list[tuple[str, Any]] = []
    for frame in raw.split("\n\n"):
        if not frame.strip():
            continue
        if frame.startswith(":"):
            events.append((":", frame[1:].strip()))
            continue
        fields = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events
