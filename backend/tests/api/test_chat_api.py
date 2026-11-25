"""``/api/v2/chat/`` and ``/api/v2/health/`` with a fake agent (no Bedrock, Pinecone or MCP)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from django.test import AsyncClient, Client, override_settings

from agent.state import REFUSAL_MESSAGE
from api.serializers import ChatResponseSerializer
from tests.agent.conftest import LFT_CITATION, FakeRetriever, Harness
from tests.api import fakes
from tests.api.conftest import parse_sse

pytestmark = pytest.mark.anyio

URL = "/api/v2/chat/"
QUESTION = "¿Cuál es la duración máxima de la jornada diurna?"
ANSWER = f"La jornada diurna tiene una duración máxima de ocho horas {LFT_CITATION}."
SSE = {"headers": {"Accept": "text/event-stream"}}


def grounded_harness(answer: str = ANSWER, **kwargs: Any) -> Harness:
    return fakes.install(
        Harness(
            route={"route": "rag", "dof_date": None},
            grades=[{"relevant_ids": ["lft#art-61"], "sufficient": True}],
            answers=[answer],
            **kwargs,
        )
    )


async def post(client: AsyncClient, body: Any = None, raw: bytes | None = None, **extra: Any) -> Any:
    import json

    data = raw if raw is not None else json.dumps(body if body is not None else {"question": QUESTION})
    return await client.post(URL, data=data, content_type="application/json", **extra)


async def read_stream(response: Any) -> str:
    return b"".join([chunk async for chunk in response.streaming_content]).decode("utf-8")


# --- JSON mode ---------------------------------------------------------------------------------------------------


async def test_json_answer_with_verified_sources() -> None:
    grounded_harness()
    response = await post(AsyncClient())
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == ANSWER
    assert data["refused"] is False
    assert data["route"] == "rag"
    source = data["sources"][0]
    assert source["citation"] == LFT_CITATION
    assert "ocho horas la diurna" in source["excerpt"]
    assert source["url"] == "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf"
    assert set(data) == set(ChatResponseSerializer().fields)
    assert set(source) == set(ChatResponseSerializer().fields["sources"].child.fields)


async def test_json_refusal_when_nothing_is_found() -> None:
    grounded_harness(retriever=FakeRetriever([]))
    data = (await post(AsyncClient())).json()
    assert data == {"answer": REFUSAL_MESSAGE, "refused": True, "route": "rag", "retries": 2, "sources": []}


async def test_question_is_trimmed_before_reaching_the_agent() -> None:
    harness = grounded_harness()
    await post(AsyncClient(), {"question": f"   {QUESTION}  \n"})
    assert harness.retriever.queries[0] == QUESTION


# --- SSE mode ----------------------------------------------------------------------------------------------------


async def test_sse_streams_status_tokens_and_final() -> None:
    grounded_harness()
    response = await post(AsyncClient(), **SSE)
    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream; charset=utf-8"
    assert response["Cache-Control"] == "no-cache"
    events = parse_sse(await read_stream(response))

    statuses = [data["node"] for name, data in events if name == "status"]
    assert statuses == ["router_node", "retrieve_node", "grade_documents_node", "generate_node"]
    assert events[0] == ("status", {"node": "router_node", "label": "Analizando la consulta"})
    tokens = "".join(data["text"] for name, data in events if name == "token")
    assert tokens == ANSWER
    name, final = events[-1]
    assert name == "final"
    assert final["answer"] == ANSWER and final["refused"] is False
    assert [s["citation"] for s in final["sources"]] == [LFT_CITATION]
    assert [n for n, _ in events].count("final") == 1


async def test_sse_final_event_overrides_a_rejected_draft() -> None:
    """Tokens of an ungrounded draft are streamed, but the authoritative final event carries the refusal."""
    hallucinated = "La jornada diurna es de ocho horas [Ley Federal del Trabajo, Art. 999, DOF 01/01/1970]."
    grounded_harness(answer=hallucinated)
    events = parse_sse(await read_stream(await post(AsyncClient(), **SSE)))
    assert "Art. 999" in "".join(d["text"] for n, d in events if n == "token")
    assert events[-1] == (
        "final",
        {"answer": REFUSAL_MESSAGE, "refused": True, "route": "rag", "retries": 0, "sources": []},
    )


async def test_sse_sends_keepalive_pings_while_the_agent_is_silent() -> None:
    fakes.install(fakes.SlowGraph(delay=0.2))
    with override_settings(CHAT_KEEPALIVE_SECONDS=0.05):
        events = parse_sse(await read_stream(await post(AsyncClient(), **SSE)))
    assert (":", "ping") in events
    assert events[-1][0] == "final"


# --- Failures ----------------------------------------------------------------------------------------------------


async def test_agent_failure_mid_stream_ends_with_an_error_event() -> None:
    fakes.install(fakes.ExplodingGraph())
    raw = await read_stream(await post(AsyncClient(), **SSE))
    events = parse_sse(raw)
    assert [n for n, _ in events] == ["status", "token", "token", "error"]
    assert events[-1][1]["code"] == "agent_unavailable"
    assert "ThrottlingException" not in raw  # internal details stay in the server log


async def test_agent_failure_in_json_mode_is_a_503_without_details() -> None:
    fakes.install(fakes.ExplodingGraph())
    response = await post(AsyncClient())
    assert response.status_code == 503
    assert response.json()["code"] == "agent_unavailable"
    assert "Throttling" not in response.content.decode()


@override_settings(DOF_AGENT_FACTORY="tests.api.fakes.build_failing_factory")
async def test_unconfigured_agent_is_a_503_without_details() -> None:
    response = await post(AsyncClient())
    assert response.status_code == 503
    assert "BEDROCK" not in response.content.decode()


# --- Validation and limits ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "code", "message"),
    [
        (b"{no es json", "invalid_json", None),
        (b"{}", "invalid_request", "Indique la pregunta en el campo 'question'."),
        (b'{"question": "   "}', "invalid_request", "La pregunta no puede estar vacía."),
        (b'["lista"]', "invalid_request", "Indique la pregunta en el campo 'question'."),
        (b'{"question": 42}', "invalid_request", "La pregunta debe ser texto."),
    ],
)
async def test_invalid_requests_are_rejected_before_the_agent(raw: bytes, code: str, message: str | None) -> None:
    harness = grounded_harness()
    response = await post(AsyncClient(), raw=raw)
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == code
    if message:
        assert data["errors"]["question"] == [message]
    assert harness.fast.structured_calls == []


@override_settings(CHAT_MAX_QUESTION_CHARS=10)
async def test_question_length_is_capped() -> None:
    grounded_harness()
    response = await post(AsyncClient(), {"question": "x" * 11})
    assert response.status_code == 400
    assert response.json()["errors"]["question"] == ["La pregunta no puede exceder 10 caracteres."]


@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=512)
async def test_oversized_body_is_a_json_400_before_the_agent() -> None:
    harness = grounded_harness()
    response = await post(AsyncClient(), {"question": "x" * 600})
    assert response.status_code == 400
    assert response.json() == {"code": "invalid_request", "detail": "La solicitud excede el tamaño permitido."}
    assert harness.fast.structured_calls == []


async def test_only_post_is_allowed() -> None:
    response = await AsyncClient().get(URL)
    assert response.status_code == 405
    assert response["Allow"] == "POST"


def via_proxy(client_address: str) -> dict[str, Any]:
    return {"headers": {"X-Forwarded-For": client_address}}


@override_settings(CHAT_RATE_LIMIT="2/minute", CHAT_TRUSTED_PROXY_COUNT=1)
async def test_rate_limit_per_client_ip() -> None:
    grounded_harness()
    client = AsyncClient()
    assert (await post(client, **via_proxy("203.0.113.1"))).status_code == 200
    assert (await post(client, **via_proxy("203.0.113.1"))).status_code == 200
    blocked = await post(client, **via_proxy("203.0.113.1"))
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "rate_limited"
    assert 1 <= int(blocked["Retry-After"]) <= 60
    assert (await post(client, **via_proxy("198.51.100.9"))).status_code == 200  # another client is unaffected


@override_settings(CHAT_RATE_LIMIT="1/minute")
async def test_spoofed_forwarded_for_does_not_bypass_the_limit_by_default() -> None:
    grounded_harness()
    client = AsyncClient()
    assert (await post(client, **via_proxy("203.0.113.1"))).status_code == 200
    assert (await post(client, **via_proxy("203.0.113.2"))).status_code == 429


# --- Health and CORS ---------------------------------------------------------------------------------------------


def test_health_does_not_build_the_agent() -> None:
    response = Client().get("/api/v2/health/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert fakes.current.graph is None


def test_cors_preflight_for_the_spa_origin() -> None:
    allowed = Client().options(URL, HTTP_ORIGIN="http://localhost:5173", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert allowed["Access-Control-Allow-Origin"] == "http://localhost:5173"
    denied = Client().options(URL, HTTP_ORIGIN="https://evil.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
    assert "Access-Control-Allow-Origin" not in denied


def setup_django(**overrides: str) -> subprocess.CompletedProcess[str]:
    """Run ``django.setup()`` with ``core.settings`` in a fresh interpreter."""
    env = {k: v for k, v in os.environ.items() if k not in {"DJANGO_SECRET_KEY", "DJANGO_DEBUG", "CHAT_RATE_LIMIT"}}
    env.update(DJANGO_SETTINGS_MODULE="core.settings", **overrides)
    return subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_production_settings_require_a_secret_key() -> None:
    result = setup_django()
    assert result.returncode != 0
    assert "Set DJANGO_SECRET_KEY" in result.stderr


def test_invalid_rate_limit_fails_at_startup() -> None:
    result = setup_django(DJANGO_DEBUG="true", CHAT_RATE_LIMIT="diez por minuto")
    assert result.returncode != 0
    assert "CHAT_RATE_LIMIT" in result.stderr
