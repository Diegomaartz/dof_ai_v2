"""McpDofTools over the real MCP protocol, against an in-process stub server (no dependency on mcp-server/)."""

from __future__ import annotations

from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel

from agent.mcp_client import DofToolError, McpDofTools

pytestmark = pytest.mark.anyio


class Edition(BaseModel):
    date: str
    published: bool
    notes: list[dict[str, Any]]


class Decree(BaseModel):
    code: int
    text: str


def stub_server() -> MCPServer:
    server = MCPServer(name="stub-dof")

    @server.tool()
    async def get_dof_today() -> Edition:
        """Stub."""
        return Edition(date="20-11-2026", published=True, notes=[{"code": 1, "title": "DECRETO"}])

    @server.tool()
    async def search_dof_by_date(date_str: str) -> Edition:
        """Stub."""
        if date_str == "99-99-9999":
            raise ToolError("Invalid date '99-99-9999': expected format DD-MM-YYYY.")
        return Edition(date=date_str, published=False, notes=[])

    @server.tool()
    async def extract_decree_text(url: str) -> Decree:
        """Stub."""
        return Decree(code=1, text=f"texto de {url}")

    return server


async def test_calls_return_structured_content() -> None:
    tools = McpDofTools(stub_server())
    today = await tools.get_dof_today()
    assert today["published"] is True and today["notes"][0]["title"] == "DECRETO"
    assert (await tools.search_dof_by_date("03-11-2026"))["date"] == "03-11-2026"
    assert (await tools.extract_decree_text("https://dof.gob.mx/x"))["text"] == "texto de https://dof.gob.mx/x"


async def test_tool_error_becomes_dof_tool_error() -> None:
    with pytest.raises(DofToolError, match="DD-MM-YYYY"):
        await McpDofTools(stub_server()).search_dof_by_date("99-99-9999")


async def test_unreachable_server_becomes_dof_tool_error() -> None:
    tools = McpDofTools("http://127.0.0.1:9/mcp", timeout_seconds=2)
    with pytest.raises(DofToolError, match="No fue posible contactar"):
        await tools.get_dof_today()
