"""``/api/v2/chat/`` (JSON or SSE) and ``/api/v2/health/``.

The chat view is a native async Django view because Django REST Framework has no async views and SSE
needs an async generator served over ASGI. DRF still provides request validation and the response
schema (``api.serializers``); the health check is a regular DRF view.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponseBase, JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from api.events import UNAVAILABLE_MESSAGE, agent_events
from api.runtime import get_agent
from api.serializers import ChatRequestSerializer, ChatResponseSerializer
from api.sse import sse_stream
from api.throttle import Rate, check_rate, client_ip

logger = logging.getLogger(__name__)


def _error(status: int, code: str, detail: str, **extra: Any) -> JsonResponse:
    return JsonResponse({"code": code, "detail": detail, **extra}, status=status)


def _wants_stream(request: HttpRequest) -> bool:
    return "text/event-stream" in request.headers.get("Accept", "")


@require_POST
async def chat_view(request: HttpRequest) -> HttpResponseBase:
    """Answer a legal question.

    Request: ``POST {"question": "..."}``. With ``Accept: text/event-stream`` the answer is streamed as SSE
    (``status`` / ``token`` / ``final`` | ``error``, see ``api.events``); otherwise a single JSON document
    with the ``final`` shape is returned.
    """
    try:
        body = json.loads(request.body or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error(400, "invalid_json", "El cuerpo de la solicitud debe ser JSON válido.")
    serializer = ChatRequestSerializer(data=body if isinstance(body, dict) else {})
    if not serializer.is_valid():
        return _error(400, "invalid_request", "Solicitud inválida.", errors=serializer.errors)
    question: str = serializer.validated_data["question"]

    retry_after = await check_rate(
        client_ip(request, settings.CHAT_TRUSTED_PROXY_COUNT), Rate.parse(settings.CHAT_RATE_LIMIT)
    )
    if retry_after is not None:
        response = _error(429, "rate_limited", "Ha excedido el límite de consultas. Intente de nuevo en unos minutos.")
        response["Retry-After"] = str(retry_after)
        return response

    try:
        graph = await get_agent()
    except Exception:
        logger.exception("Could not build the chat agent")
        return _error(503, "agent_unavailable", UNAVAILABLE_MESSAGE)

    if _wants_stream(request):
        stream = StreamingHttpResponse(
            sse_stream(agent_events(graph, question), settings.CHAT_KEEPALIVE_SECONDS),
            content_type="text/event-stream; charset=utf-8",
        )
        stream["Cache-Control"] = "no-cache"
        stream["X-Accel-Buffering"] = "no"  # disable buffering in nginx-style proxies
        return stream

    try:
        final: dict[str, Any] | None = None
        async for event in agent_events(graph, question):
            if event.name == "final":
                final = event.data
    except Exception:
        logger.exception("Chat agent run failed")
        return _error(503, "agent_unavailable", UNAVAILABLE_MESSAGE)
    if final is None:
        return _error(503, "agent_unavailable", UNAVAILABLE_MESSAGE)
    return JsonResponse(ChatResponseSerializer(final).data, json_dumps_params={"ensure_ascii": False})


class HealthView(APIView):
    """Liveness probe for the load balancer / ECS. Does not call Bedrock, Pinecone or the MCP server."""

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})
