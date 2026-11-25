"""End-to-end MCP tests: an in-process MCP client discovers and calls the tools against mocked SIDOF HTTP."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import httpx
import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from dof_mcp.config import Settings
from dof_mcp.server import build_server
from tests.conftest import FakeSidof

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 20)
NOTE_URL = "https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026"


def make_client(fake: FakeSidof, **overrides: Any) -> Client:
    settings = Settings(**overrides)
    return Client(build_server(settings, transport=fake.transport, today=lambda: TODAY))


def error_text(result: CallToolResult) -> str:
    assert result.is_error is True
    return " ".join(block.text for block in result.content if isinstance(block, TextContent))


async def test_discovers_exactly_three_documented_read_only_tools(fake_sidof: FakeSidof) -> None:
    async with make_client(fake_sidof) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
    assert set(tools) == {"get_dof_today", "search_dof_by_date", "extract_decree_text"}
    for tool in tools.values():
        assert tool.description and len(tool.description) > 80
        assert tool.output_schema is not None
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
    assert tools["search_dof_by_date"].input_schema["required"] == ["date_str"]
    assert tools["extract_decree_text"].input_schema["required"] == ["url"]
    assert "required" not in tools["get_dof_today"].input_schema or not tools["get_dof_today"].input_schema["required"]


async def test_get_dof_today_uses_mexico_city_date(fake_sidof: FakeSidof, edition_payload: dict[str, Any]) -> None:
    fake_sidof.json("/notas/20-11-2026", edition_payload)
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("get_dof_today", {})
    assert result.is_error is False
    data = result.structured_content
    assert data is not None
    assert data["date"] == "20-11-2026"
    assert data["total_notes"] == 6
    assert data["notes"][0]["url"] == NOTE_URL
    assert data["source"] == "https://sidof.segob.gob.mx/dof/sidof/notas/20-11-2026"
    # The text content mirrors the structured payload as JSON for clients without structured output support.
    text_blocks = [b for b in result.content if isinstance(b, TextContent)]
    assert json.loads(text_blocks[0].text)["total_notes"] == 6
    assert [str(r.url) for r in fake_sidof.requests] == ["https://sidof.segob.gob.mx/dof/sidof/notas/20-11-2026"]
    assert fake_sidof.requests[0].headers["user-agent"].startswith("dof-ai-mcp/")
    # Live SIDOF returns 406 Not Acceptable to a strict "Accept: application/json" (observed 2026-11-24).
    assert "*/*" in fake_sidof.requests[0].headers["accept"]


async def test_search_dof_by_date(fake_sidof: FakeSidof, edition_payload: dict[str, Any]) -> None:
    fake_sidof.json("/notas/03-11-2026", edition_payload)
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("search_dof_by_date", {"date_str": "03-11-2026"})
    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["date"] == "03-11-2026"
    assert result.structured_content["published"] is True


async def test_search_day_without_edition(fake_sidof: FakeSidof) -> None:
    fake_sidof.json("/notas/15-11-2026", {"messageCode": 200, "response": "OK", "NotasMatutinas": []})
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("search_dof_by_date", {"date_str": "15-11-2026"})
    assert result.structured_content is not None
    assert result.structured_content["published"] is False


@pytest.mark.parametrize(
    ("date_str", "message"),
    [("2026-11-20", "DD-MM-YYYY"), ("31-02-2026", "DD-MM-YYYY"), ("21-11-2026", "future")],
)
async def test_search_rejects_bad_dates_without_calling_upstream(
    fake_sidof: FakeSidof, date_str: str, message: str
) -> None:
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("search_dof_by_date", {"date_str": date_str})
    assert message in error_text(result)
    assert fake_sidof.requests == []


async def test_extract_decree_text(fake_sidof: FakeSidof, note_payload: dict[str, Any]) -> None:
    fake_sidof.json("/notas/nota/5804497", note_payload)
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("extract_decree_text", {"url": NOTE_URL})
    assert result.is_error is False
    data = result.structured_content
    assert data is not None
    assert data["code"] == 5804497
    assert data["url"] == NOTE_URL
    assert "Artículo 1o.- El presente Reglamento es de orden público" in data["text"]
    assert data["truncated"] is False


async def test_extract_decree_text_respects_max_chars(fake_sidof: FakeSidof, note_payload: dict[str, Any]) -> None:
    fake_sidof.json("/notas/nota/5804497", note_payload)
    async with make_client(fake_sidof, max_decree_chars=40) as client:
        result = await client.call_tool("extract_decree_text", {"url": NOTE_URL})
    assert result.structured_content is not None
    assert len(result.structured_content["text"]) == 40
    assert result.structured_content["truncated"] is True


async def test_extract_rejects_foreign_url_without_fetching_it(fake_sidof: FakeSidof) -> None:
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("extract_decree_text", {"url": "http://169.254.169.254/latest/meta-data/"})
    assert "Unsupported URL" in error_text(result)
    assert fake_sidof.requests == []


async def test_unknown_note_is_reported(fake_sidof: FakeSidof) -> None:
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("extract_decree_text", {"url": "123"})
    assert "no record" in error_text(result)


async def test_upstream_http_500_is_a_tool_error(fake_sidof: FakeSidof) -> None:
    fake_sidof.json("/notas/20-11-2026", {"error": "boom"}, status=500)
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("get_dof_today", {})
    assert "unavailable" in error_text(result)


async def test_network_failure_is_a_tool_error(fake_sidof: FakeSidof) -> None:
    fake_sidof.fail("/notas/nota/5804497", httpx.ConnectTimeout("timed out"))
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("extract_decree_text", {"url": NOTE_URL})
    assert "ConnectTimeout" in error_text(result)


async def test_upstream_error_envelope_is_a_tool_error(fake_sidof: FakeSidof) -> None:
    fake_sidof.json("/notas/20-11-2026", {"messageCode": 500, "response": "ERROR"})
    async with make_client(fake_sidof) as client:
        result = await client.call_tool("get_dof_today", {})
    assert "messageCode=500" in error_text(result)
