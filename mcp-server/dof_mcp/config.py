"""Environment-driven configuration for the DOF MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _csv(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Every field can be overridden through an environment variable."""

    sidof_base_url: str = "https://sidof.segob.gob.mx/dof/sidof"
    """Base URL of the public SIDOF JSON API that backs dof.gob.mx."""

    dof_public_base_url: str = "https://dof.gob.mx"
    """Host used to build human-facing note links (the ``www.`` host serves a mismatched TLS certificate)."""

    http_timeout_seconds: float = 20.0
    max_decree_chars: int = 60_000
    """Upper bound on decree text returned to the LLM; longer texts are truncated and flagged."""

    timezone: str = "America/Mexico_City"
    """Timezone that defines "today" for the DOF publication calendar."""

    user_agent: str = "dof-ai-mcp/0.1 (+legal research assistant)"

    allowed_hosts: list[str] = field(default_factory=list)
    """Host headers accepted by the HTTP transport (DNS-rebinding protection). Empty disables the check."""

    allowed_origins: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from ``DOF_MCP_*`` environment variables, falling back to defaults."""
        default = cls()
        return cls(
            sidof_base_url=os.getenv("DOF_MCP_SIDOF_BASE_URL", default.sidof_base_url).rstrip("/"),
            dof_public_base_url=os.getenv("DOF_MCP_PUBLIC_BASE_URL", default.dof_public_base_url).rstrip("/"),
            http_timeout_seconds=float(os.getenv("DOF_MCP_HTTP_TIMEOUT", default.http_timeout_seconds)),
            max_decree_chars=int(os.getenv("DOF_MCP_MAX_DECREE_CHARS", default.max_decree_chars)),
            timezone=os.getenv("DOF_MCP_TIMEZONE", default.timezone),
            user_agent=os.getenv("DOF_MCP_USER_AGENT", default.user_agent),
            allowed_hosts=_csv(os.getenv("DOF_MCP_ALLOWED_HOSTS")),
            allowed_origins=_csv(os.getenv("DOF_MCP_ALLOWED_ORIGINS")),
        )
