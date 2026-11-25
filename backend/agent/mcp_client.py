"""Client for the DOF MCP server. The backend talks to it only through the MCP protocol (CLAUDE.md)."""

from __future__ import annotations

from typing import Any, Protocol

from mcp import Client
from mcp.types import TextContent


class DofToolError(Exception):
    """An MCP tool call failed (tool-level error or transport failure)."""


class DofTools(Protocol):
    """The three DOF tools, as the agent consumes them. Each returns the tool's structured JSON."""

    async def get_dof_today(self) -> dict[str, Any]: ...

    async def search_dof_by_date(self, date_str: str) -> dict[str, Any]: ...

    async def extract_decree_text(self, url: str) -> dict[str, Any]: ...


class McpDofTools:
    """Calls the DOF MCP server over Streamable HTTP, one short-lived connection per call (stateless server)."""

    def __init__(self, target: str | Any, timeout_seconds: float = 30.0) -> None:
        """``target`` is the server URL (``MCP_SERVER_URL``); tests may pass an in-process MCP server instead."""
        self.target = target
        self.timeout_seconds = timeout_seconds

    async def get_dof_today(self) -> dict[str, Any]:
        return await self._call("get_dof_today", {})

    async def search_dof_by_date(self, date_str: str) -> dict[str, Any]:
        return await self._call("search_dof_by_date", {"date_str": date_str})

    async def extract_decree_text(self, url: str) -> dict[str, Any]:
        return await self._call("extract_decree_text", {"url": url})

    async def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            async with Client(self.target, read_timeout_seconds=self.timeout_seconds) as client:
                result = await client.call_tool(name, arguments)
        except Exception as exc:  # transport errors surface as varied exception (group) types
            raise DofToolError(f"No fue posible contactar el servicio del DOF ({type(exc).__name__}).") from exc
        if result.is_error:
            message = " ".join(b.text for b in result.content if isinstance(b, TextContent)) or "error desconocido"
            raise DofToolError(message)
        if not isinstance(result.structured_content, dict):
            raise DofToolError(f"La herramienta {name} no devolvió datos estructurados.")
        return result.structured_content
