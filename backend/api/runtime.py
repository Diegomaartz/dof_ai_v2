"""Process-wide agent instance, built lazily from ``settings.DOF_AGENT_FACTORY``."""

from __future__ import annotations

import asyncio
from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

_agents: dict[str, Any] = {}


async def get_agent() -> Any:
    """Return the compiled graph, built once per process off the event loop (building may read SSM).

    Two concurrent first requests may both build it; the graph is stateless, so that only costs a little time.
    """
    path = settings.DOF_AGENT_FACTORY
    if path not in _agents:
        factory = import_string(path)
        _agents[path] = await asyncio.to_thread(factory)
    return _agents[path]


def reset_agents() -> None:
    """Drop cached agents (tests, or after a configuration change)."""
    _agents.clear()
