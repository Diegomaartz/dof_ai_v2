"""Assembly of the Self-RAG LangGraph state machine.

Flow:
- ``START -> router_node``.
- ``router_node`` (and every ``transform_query_node`` retry) gathers evidence by route: ``rag`` -> ``retrieve_node``,
  ``mcp`` -> ``mcp_node``, ``hybrid`` -> ``retrieve_node`` then ``mcp_node``.
- Gathering ends in ``grade_documents_node``, which goes to ``generate_node`` when the evidence is sufficient,
  to ``transform_query_node`` while retries remain (``AGENT_MAX_RETRIES``, 0-2, default 2), and otherwise to
  ``generate_node``, which refuses without calling the LLM because grounding still failed (CLAUDE.md).
- ``generate_node -> END``.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from langgraph.graph import END, START, StateGraph

from agent.nodes import AgentDeps, make_nodes
from agent.state import AgentState

GATHER_NODES = ("retrieve_node", "mcp_node")


def _after_routing(state: AgentState) -> Literal["retrieve_node", "mcp_node"]:
    """Both the first attempt and every rewrite gather evidence according to the route."""
    return "mcp_node" if state["route"] == "mcp" else "retrieve_node"


def _after_retrieve(state: AgentState) -> Literal["mcp_node", "grade_documents_node"]:
    return "mcp_node" if state["route"] == "hybrid" else "grade_documents_node"


def make_grade_router(max_retries: int) -> Any:
    def _after_grading(state: AgentState) -> Literal["generate_node", "transform_query_node"]:
        if state.get("sufficient"):
            return "generate_node"
        if state.get("retries", 0) < max_retries:
            return "transform_query_node"
        return "generate_node"

    return _after_grading


def build_graph(deps: AgentDeps) -> Any:
    """Compile the agent graph bound to ``deps``. The result supports ``ainvoke`` and ``astream``."""
    nodes = make_nodes(deps)
    graph = StateGraph(AgentState)
    for name, node in nodes.items():
        graph.add_node(name, cast(Any, node))

    graph.add_edge(START, "router_node")
    graph.add_conditional_edges("router_node", _after_routing, list(GATHER_NODES))
    graph.add_conditional_edges("retrieve_node", _after_retrieve, ["mcp_node", "grade_documents_node"])
    graph.add_edge("mcp_node", "grade_documents_node")
    graph.add_conditional_edges(
        "grade_documents_node",
        make_grade_router(deps.settings.max_retries),
        ["generate_node", "transform_query_node"],
    )
    graph.add_conditional_edges("transform_query_node", _after_routing, list(GATHER_NODES))
    graph.add_edge("generate_node", END)
    return graph.compile()


def initial_state(question: str) -> AgentState:
    """State for a new question."""
    return {"question": question.strip()}
