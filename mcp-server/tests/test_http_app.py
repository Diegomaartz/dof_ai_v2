"""Transport tests: stateless Streamable HTTP through the Lambda handler (Function URL events) and Starlette."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from starlette.testclient import TestClient

from dof_mcp import handler
from dof_mcp.config import Settings
from dof_mcp.server import build_server, create_app
from tests.conftest import FakeSidof

HOST = "abc123.lambda-url.us-east-1.on.aws"
HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
    "mcp-protocol-version": "2025-06-18",
}


class LambdaContext:
    aws_request_id = "test-request"
    function_name = "dof-ai-mcp"


def function_url_event(body: dict[str, Any], host: str = HOST) -> dict[str, Any]:
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": "/mcp",
        "rawQueryString": "",
        "headers": {**HEADERS, "host": host},
        "requestContext": {
            "http": {"method": "POST", "path": "/mcp", "sourceIp": "203.0.113.7", "protocol": "HTTP/1.1"},
            "domainName": host,
        },
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }


def rpc(method: str, params: dict[str, Any] | None = None, request_id: int = 1) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}


def test_warm_lambda_serves_repeated_invocations() -> None:
    """Regression: the SDK session manager can only run once, so each invocation needs a fresh app."""
    initialize = rpc(
        "initialize",
        {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}},
    )
    for request in (initialize, rpc("tools/list", request_id=2), rpc("tools/list", request_id=3)):
        response = handler.lambda_handler(function_url_event(request), LambdaContext())
        assert response["statusCode"] == 200
        assert response["headers"]["content-type"].startswith("application/json")
        assert json.loads(response["body"])["id"] == request["id"]

    tools = json.loads(response["body"])["result"]["tools"]
    assert sorted(t["name"] for t in tools) == ["extract_decree_text", "get_dof_today", "search_dof_by_date"]


def test_lambda_tool_call_returns_structured_json(
    monkeypatch: pytest.MonkeyPatch, fake_sidof: FakeSidof, edition_payload: dict[str, Any]
) -> None:
    fake_sidof.json("/notas/20-11-2026", edition_payload)
    server = build_server(Settings(), transport=fake_sidof.transport, today=lambda: date(2026, 11, 20))
    monkeypatch.setattr(handler, "_SERVER", server)

    call = rpc("tools/call", {"name": "search_dof_by_date", "arguments": {"date_str": "20-11-2026"}})
    response = handler.lambda_handler(function_url_event(call), LambdaContext())

    result = json.loads(response["body"])["result"]
    assert result["isError"] is False
    assert result["structuredContent"]["total_notes"] == 6
    assert result["structuredContent"]["notes"][0]["code"] == 5804497


def test_host_validation_when_allowed_hosts_configured() -> None:
    settings = Settings(allowed_hosts=[HOST])
    with TestClient(create_app(settings), base_url=f"https://{HOST}") as client:
        assert client.post("/mcp", json=rpc("tools/list"), headers=HEADERS).status_code == 200
    with TestClient(create_app(settings), base_url="https://attacker.example") as client:
        assert client.post("/mcp", json=rpc("tools/list"), headers=HEADERS).status_code == 421
