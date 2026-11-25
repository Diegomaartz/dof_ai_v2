"""MCP server definition: the three DOF tools and the stateless Streamable HTTP ASGI app."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.applications import Starlette

from dof_mcp.client import SidofClient
from dof_mcp.config import Settings
from dof_mcp.models import DecreeTextResult, DofEditionResult
from dof_mcp.parsing import UpstreamError, extract_note_code, parse_date, parse_edition, parse_note

logger = logging.getLogger(__name__)

INSTRUCTIONS = (
    "Real-time access to the Mexican Diario Oficial de la Federación (DOF). "
    "Use get_dof_today or search_dof_by_date to list what was published on a day, then "
    "extract_decree_text with a note's `url` to read its full text. Cite notes by title, "
    "publication date (DD/MM/YYYY) and url. Data comes from the official SIDOF service."
)

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)
_UNAVAILABLE = "The DOF service is unavailable right now ({error}); try again later."


def build_server(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    today: Callable[[], date] | None = None,
) -> MCPServer:
    """Create the MCP server. ``transport`` and ``today`` are injection points for tests."""
    cfg = settings or Settings.from_env()
    zone = ZoneInfo(cfg.timezone)
    clock = today or (lambda: datetime.now(zone).date())
    server = MCPServer(name="dof-ai-mcp", version="0.1.0", instructions=INSTRUCTIONS)

    async def fetch_edition(day: date) -> DofEditionResult:
        client = SidofClient(cfg, transport)
        try:
            payload = await client.get_edition(day)
            return parse_edition(payload, day, public_base_url=cfg.dof_public_base_url, source=client.edition_url(day))
        except UpstreamError as exc:
            raise ToolError(str(exc)) from exc
        except httpx.HTTPError as exc:
            logger.warning("SIDOF edition request failed for %s: %r", day, exc)
            raise ToolError(_UNAVAILABLE.format(error=type(exc).__name__)) from exc

    @server.tool(title="DOF de hoy", annotations=_READ_ONLY)
    async def get_dof_today() -> DofEditionResult:
        """List every publication in today's Diario Oficial de la Federación (Mexico City date).

        Returns all notes of the matutina, vespertina and extraordinaria editions with their title,
        section (e.g. PODER EJECUTIVO), page and public dof.gob.mx `url`. `published` is false when the
        DOF has not published anything (weekends, holidays, or before the morning edition is out).
        Use extract_decree_text(url) to read a specific note.
        """
        return await fetch_edition(clock())

    @server.tool(title="Buscar DOF por fecha", annotations=_READ_ONLY)
    async def search_dof_by_date(date_str: str) -> DofEditionResult:
        """List every publication in the DOF edition(s) of a past date.

        Args:
            date_str: Publication date in DD-MM-YYYY format, e.g. "20-11-2026".

        Returns the same structure as get_dof_today. `published` is false when the DOF did not
        publish that day.
        """
        try:
            day = parse_date(date_str)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        if day > clock():
            raise ToolError(f"{date_str} is in the future; the DOF can only be searched up to today.")
        return await fetch_edition(day)

    @server.tool(title="Texto de decreto DOF", annotations=_READ_ONLY)
    async def extract_decree_text(url: str) -> DecreeTextResult:
        """Return the clean plain text of a single DOF publication (decree, agreement, notice, ...).

        Args:
            url: The note's dof.gob.mx link as returned by get_dof_today / search_dof_by_date
                (e.g. "https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026").
                A bare numeric note code is also accepted.

        Very long texts are cut to the server limit; `truncated` and `total_chars` report it.
        """
        try:
            code = extract_note_code(url)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        client = SidofClient(cfg, transport)
        try:
            payload = await client.get_note(code)
            return parse_note(payload, code, public_base_url=cfg.dof_public_base_url, max_chars=cfg.max_decree_chars)
        except UpstreamError as exc:
            raise ToolError(str(exc)) from exc
        except httpx.HTTPError as exc:
            logger.warning("SIDOF note request failed for %s: %r", code, exc)
            raise ToolError(_UNAVAILABLE.format(error=type(exc).__name__)) from exc

    return server


def create_app(settings: Settings | None = None, server: MCPServer | None = None) -> Starlette:
    """Build the stateless, JSON-response Streamable HTTP app served at ``/mcp``.

    Stateless mode keeps no session between requests, so each Lambda invocation is independent.
    Host and Origin validation is enabled when ``DOF_MCP_ALLOWED_HOSTS`` is set (e.g. the Function URL host).
    """
    cfg = settings or Settings.from_env()
    if cfg.allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=cfg.allowed_hosts,
            allowed_origins=cfg.allowed_origins,
        )
    else:
        security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    mcp_server = server or build_server(cfg)
    return mcp_server.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
