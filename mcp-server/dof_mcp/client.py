"""Thin async HTTP client for the public SIDOF JSON API (the data source behind dof.gob.mx)."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from dof_mcp.config import Settings
from dof_mcp.parsing import UpstreamError, format_api_date

ACCEPT_HEADER = "application/json, */*;q=0.8"


class SidofClient:
    """Fetches DOF editions and notes. One instance per tool call keeps the server stateless."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def edition_url(self, day: date) -> str:
        return f"{self._settings.sidof_base_url}/notas/{format_api_date(day)}"

    def note_url(self, code: int) -> str:
        return f"{self._settings.sidof_base_url}/notas/nota/{code}"

    async def get_edition(self, day: date) -> dict[str, Any]:
        """Return the raw SIDOF payload listing every note published on ``day``."""
        return await self._get_json(self.edition_url(day))

    async def get_note(self, code: int) -> dict[str, Any]:
        """Return the raw SIDOF payload for one note, including its HTML body."""
        return await self._get_json(self.note_url(code))

    async def _get_json(self, url: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self._settings.http_timeout_seconds,
            # SIDOF answers 406 to a strict "Accept: application/json"; the wildcard is required.
            headers={"User-Agent": self._settings.user_agent, "Accept": ACCEPT_HEADER},
            transport=self._transport,
            follow_redirects=True,
        ) as http:
            response = await http.get(url)
        if response.status_code == 404:
            raise UpstreamError("The DOF has no record for this request (HTTP 404).")
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise UpstreamError("SIDOF returned a non-JSON response.") from exc
        if not isinstance(payload, dict):
            raise UpstreamError("SIDOF returned an unexpected JSON structure.")
        return payload
