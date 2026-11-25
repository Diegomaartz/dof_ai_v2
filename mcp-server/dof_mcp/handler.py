"""AWS Lambda entry point (Function URL / API Gateway) for the stateless MCP server."""

from __future__ import annotations

from typing import Any

from mangum import Mangum

from dof_mcp.config import Settings
from dof_mcp.server import build_server, create_app

# Built once per container: tool registration and output-schema generation are reused by warm invocations.
_SETTINGS = Settings.from_env()
_SERVER = build_server(_SETTINGS)


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Serve one MCP HTTP request.

    The MCP SDK's ``StreamableHTTPSessionManager.run()`` may only run once per instance, while Mangum
    runs the ASGI lifespan on every invocation. A fresh (cheap) ASGI app, and with it a fresh session
    manager, is therefore created per invocation; the stateless transport keeps nothing between them.
    """
    app = create_app(_SETTINGS, server=_SERVER)
    response: dict[str, Any] = Mangum(app, lifespan="auto")(event, context)
    return response
