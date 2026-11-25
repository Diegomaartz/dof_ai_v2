"""Graph state and the source records shared by every node."""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

Route = Literal["rag", "mcp", "hybrid"]
SourceKind = Literal["legislacion", "dof"]

REFUSAL_MESSAGE = "No se encontró sustento legal en las fuentes consultadas."


class Source(BaseModel):
    """A piece of retrieved evidence: a law article (Pinecone) or a DOF publication (MCP tools)."""

    id: str = Field(description="Stable identifier, e.g. 'lft#art-2o' or 'dof:5804497'.")
    kind: SourceKind
    citation: str = Field(description="Exact inline citation the answer must use for this source.")
    title: str
    text: str = Field(description="Content given to the LLM and shown as the verified excerpt.")
    url: str | None = None
    date: str | None = Field(default=None, description="Citation date, DD/MM/YYYY.")
    hierarchy: str | None = None
    score: float | None = None
    full_text_available: bool = Field(default=False, description="DOF only: whether the decree text can be fetched.")
    text_is_complete: bool = Field(default=True, description="False when `text` is a summary or was truncated.")
    text_fetched: bool = Field(default=False, description="DOF only: the decree text was already fetched.")
    is_repealed: bool = Field(default=False, description="Law only: the article is repealed ('Se deroga').")


class AgentState(TypedDict, total=False):
    """Mutable state carried through the LangGraph workflow.

    ``candidates`` holds the evidence gathered in the current attempt; ``documents`` accumulates
    the evidence that passed grading across attempts, so a query rewrite never discards it.
    """

    question: str
    query: str
    route: Route
    dof_date: str | None
    candidates: list[Source]
    documents: list[Source]
    sufficient: bool
    retries: int
    answer: str
    refused: bool
    cited_sources: list[Source]
    errors: list[str]
