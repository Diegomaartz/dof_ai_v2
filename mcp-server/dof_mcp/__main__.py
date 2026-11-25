"""Run the MCP server locally: ``python -m dof_mcp [--host 127.0.0.1] [--port 8001]``.

Endpoint: ``http://127.0.0.1:8001/mcp`` (connect MCP Inspector with transport "Streamable HTTP").
"""

from __future__ import annotations

import argparse
import dataclasses

import uvicorn

from dof_mcp.config import Settings
from dof_mcp.server import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DOF-AI MCP server over Streamable HTTP.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    settings = Settings.from_env()
    if not settings.allowed_hosts and args.host in ("127.0.0.1", "localhost"):
        settings = dataclasses.replace(
            settings,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        )
    uvicorn.run(create_app(settings), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
