"""Translate an agent run into the chat event stream (framework-agnostic: no Django imports).

Event contract (also the SSE ``event:`` names):

- ``status`` ``{"node": str, "label": str}``: a graph node started (Spanish label for the UI).
- ``token`` ``{"text": str}``: a piece of the answer being generated.
- ``final`` ``{"answer", "refused", "route", "retries", "sources"}``: the validated result. It is authoritative:
  the grounding check runs after generation, so the client MUST replace the streamed text with ``answer``
  (it differs when the draft was rejected and replaced by the refusal message).
- ``error`` ``{"code": str, "message": str}``: the run failed. Any streamed text must be discarded.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal

from agent.graph import initial_state
from agent.state import AgentState, Source

logger = logging.getLogger(__name__)

EventName = Literal["status", "token", "final", "error"]

GENERATE_NODE = "generate_node"

STATUS_LABELS: dict[str, str] = {
    "router_node": "Analizando la consulta",
    "retrieve_node": "Buscando en la legislación federal",
    "mcp_node": "Consultando el Diario Oficial de la Federación",
    "grade_documents_node": "Verificando la relevancia de las fuentes",
    "transform_query_node": "Reformulando la búsqueda",
    "generate_node": "Redactando la respuesta",
}

UNAVAILABLE_MESSAGE = "No fue posible completar la consulta en este momento. Intente de nuevo más tarde."


@dataclass(frozen=True)
class ChatEvent:
    name: EventName
    data: dict[str, Any]


class AgentRunError(Exception):
    """The agent finished without producing an answer."""


def source_payload(source: Source) -> dict[str, Any]:
    """Public shape of a verified source, rendered in the "Fuentes Verificadas" panel."""
    return {
        "id": source.id,
        "kind": source.kind,
        "citation": source.citation,
        "title": source.title,
        "excerpt": source.text,
        "excerpt_is_complete": source.text_is_complete,
        "url": source.url,
        "date": source.date,
        "hierarchy": source.hierarchy,
        "is_repealed": source.is_repealed,
    }


def final_payload(state: AgentState) -> dict[str, Any]:
    if "answer" not in state:
        raise AgentRunError("The agent finished without an answer.")
    return {
        "answer": state["answer"],
        "refused": bool(state.get("refused", False)),
        "route": state.get("route"),
        "retries": state.get("retries", 0),
        "sources": [source_payload(s) for s in state.get("cited_sources", [])],
    }


async def agent_events(graph: Any, question: str) -> AsyncIterator[ChatEvent]:
    """Run ``graph`` on ``question`` and yield ``status`` / ``token`` events, then exactly one ``final`` event.

    Exceptions from the agent (Bedrock, Pinecone, MCP transport) propagate to the caller, which turns them
    into an ``error`` event or an HTTP 503.
    """
    final_state: AgentState = {}
    async for mode, payload in graph.astream(initial_state(question), stream_mode=["tasks", "messages", "values"]):
        if mode == "tasks":
            if "input" in payload:  # task start (task results carry "result" instead)
                node = payload.get("name", "")
                if label := STATUS_LABELS.get(node):
                    yield ChatEvent("status", {"node": node, "label": label})
        elif mode == "messages":
            message, metadata = payload
            # Router/grader/rewrite calls also emit LLM chunks; only the answer is streamed to the user.
            if metadata.get("langgraph_node") == GENERATE_NODE and (text := message.text):
                yield ChatEvent("token", {"text": text})
        elif mode == "values":
            final_state = payload
    if errors := final_state.get("errors"):
        # The question itself is not logged: legal queries may contain personal data.
        logger.info("Agent notes (question of %d chars): %s", len(question), errors)
    yield ChatEvent("final", final_payload(final_state))
