"""Shared fixtures: SIDOF payload fixtures and a mocked HTTP transport (no network access in tests)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SIDOF = "https://sidof.segob.gob.mx/dof/sidof"


def load_fixture(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def edition_payload() -> dict[str, Any]:
    return load_fixture("edition_20-11-2026.json")


@pytest.fixture
def note_payload() -> dict[str, Any]:
    return load_fixture("nota_5804497.json")


class FakeSidof:
    """Routes mocked SIDOF URLs to canned responses and records every request made."""

    def __init__(self) -> None:
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []

    def json(self, path: str, payload: Any, status: int = 200) -> None:
        self.routes[f"{SIDOF}{path}"] = lambda _req: httpx.Response(status, json=payload)

    def fail(self, path: str, exc: Exception) -> None:
        def raise_exc(_req: httpx.Request) -> httpx.Response:
            raise exc

        self.routes[f"{SIDOF}{path}"] = raise_exc

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(str(request.url))
        return route(request) if route else httpx.Response(404, json={"messageCode": 404, "response": "Not found"})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


@pytest.fixture
def fake_sidof() -> FakeSidof:
    return FakeSidof()
