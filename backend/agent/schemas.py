"""Structured outputs requested from the LLM (Bedrock Converse tool use under the hood)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.state import Route


class RouteDecision(BaseModel):
    """Where the evidence for a question has to come from."""

    route: Route = Field(
        description=(
            "'rag' for questions about the content of federal laws; 'mcp' for questions about what the "
            "Diario Oficial de la Federación published on a given day; 'hybrid' when both are needed."
        )
    )
    dof_date: str | None = Field(
        default=None,
        description="DD-MM-YYYY date of the DOF edition to consult, resolved from the question; null means today.",
    )


class GradeDecision(BaseModel):
    """Relevance verdict over a batch of candidate sources."""

    relevant_ids: list[str] = Field(description="IDs of the sources that are directly relevant to the question.")
    sufficient: bool = Field(
        description="True only if the relevant sources, taken together, are enough to answer the question."
    )


class RewrittenQuery(BaseModel):
    """A better retrieval query produced after insufficient evidence."""

    query: str = Field(description="Reformulated search query in Spanish, using formal legal terminology.")
    dof_date: str | None = Field(
        default=None, description="Corrected DD-MM-YYYY DOF date, if the previous date was wrong; else null."
    )
