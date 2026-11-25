"""Fakes for the agent's external dependencies: Bedrock chat models, the legal retriever and the DOF MCP tools.

No test in this package touches AWS, Pinecone or dof.gob.mx.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import date
from typing import Any

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableLambda
from pydantic import Field

from agent.config import AgentSettings
from agent.graph import build_graph
from agent.mcp_client import DofToolError
from agent.nodes import AgentDeps
from agent.sources import dof_citation
from rag.retrieval import RetrievedChunk

TODAY = date(2026, 11, 20)

LFT_CITATION = "[Ley Federal del Trabajo, Art. 61, DOF 30/11/2012]"
LFT_CITATION_2 = "[Ley Federal del Trabajo, Art. 62, DOF 30/11/2012]"


class ScriptedChatModel(BaseChatModel):
    """Chat model returning scripted structured outputs (per schema name) and scripted answers.

    A structured response may be a value or a callable taking the prompt messages, which lets a test
    react to what the node actually sent.
    """

    structured: dict[str, list[Any]] = Field(default_factory=dict)
    answers: list[str] = Field(default_factory=list)
    structured_calls: list[tuple[str, list[BaseMessage]]] = Field(default_factory=list)
    answer_calls: list[list[BaseMessage]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        name = schema.__name__

        def respond(messages: list[BaseMessage]) -> Any:
            self.structured_calls.append((name, messages))
            queue = self.structured.get(name)
            if not queue:
                raise AssertionError(f"No scripted {name} response left")
            item = queue.pop(0) if len(queue) > 1 else queue[0]  # the last response repeats
            value = item(messages) if callable(item) else item
            return schema.model_validate(value) if isinstance(value, dict) else value

        async def arespond(messages: list[BaseMessage]) -> Any:
            return respond(messages)

        return RunnableLambda(respond, afunc=arespond)

    def _next_answer(self, messages: list[BaseMessage]) -> str:
        self.answer_calls.append(messages)
        if not self.answers:
            raise AssertionError("No scripted answer left")
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._next_answer(messages)))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        text = self._next_answer(messages)
        for index, piece in enumerate(text.split(" ")):
            token = piece if index == 0 else f" {piece}"
            chunk = ChatGenerationChunk(message=AIMessageChunk(content=token))
            if run_manager:
                run_manager.on_llm_new_token(token, chunk=chunk)
            yield chunk


class FakeRetriever:
    """Returns scripted chunks; ``by_query`` maps a query to its results, ``default`` covers the rest."""

    def __init__(self, default: Sequence[RetrievedChunk] = (), by_query: dict[str, list[RetrievedChunk]] | None = None):
        self.default = list(default)
        self.by_query = by_query or {}
        self.queries: list[str] = []

    def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        self.queries.append(query)
        return self.by_query.get(query, self.default)[:top_k]


class FakeDofTools:
    """In-memory DOF tools with call recording; set an attribute to an exception to make that tool fail."""

    def __init__(self, edition: dict[str, Any] | None = None, decrees: dict[str, dict[str, Any]] | None = None):
        self.edition = edition or edition_payload()
        self.decrees = decrees or {}
        self.calls: list[tuple[str, Any]] = []
        self.fail: dict[str, Exception] = {}

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise self.fail[name]

    async def get_dof_today(self) -> dict[str, Any]:
        self.calls.append(("get_dof_today", None))
        self._maybe_fail("get_dof_today")
        return self.edition

    async def search_dof_by_date(self, date_str: str) -> dict[str, Any]:
        self.calls.append(("search_dof_by_date", date_str))
        self._maybe_fail("search_dof_by_date")
        return {**self.edition, "date": date_str}

    async def extract_decree_text(self, url: str) -> dict[str, Any]:
        self.calls.append(("extract_decree_text", url))
        self._maybe_fail("extract_decree_text")
        if url not in self.decrees:
            raise DofToolError(f"no decree for {url}")
        return self.decrees[url]


def lft_chunk(label: str = "61", citation: str = LFT_CITATION, score: float = 0.82, **extra: Any) -> RetrievedChunk:
    extra.setdefault("text", f"Artículo {label}.- La duración máxima de la jornada será: ocho horas la diurna.")
    return RetrievedChunk(
        id=f"lft#art-{label}",
        score=score,
        citation=citation,
        law_name="Ley Federal del Trabajo",
        article_label=label,
        section_type="articulo",
        hierarchy_path="TITULO TERCERO Condiciones de Trabajo > CAPITULO II Jornada de trabajo",
        citation_date="2012-11-30",
        source_url="https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf",
        **extra,
    )


DECREE_URL = "https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026"
DECREE_TITLE = "DECRETO por el que se expide el Reglamento de la Ley Federal de Armas de Fuego y Explosivos."
DECREE_CITATION = dof_citation(DECREE_TITLE, "20/11/2026")


def edition_payload(published: bool = True) -> dict[str, Any]:
    """Structured output of get_dof_today / search_dof_by_date, as the MCP server returns it."""
    notes = [
        {
            "code": 5804497,
            "title": DECREE_TITLE,
            "edition": "matutina",
            "section": "PODER EJECUTIVO",
            "section_code": "PE",
            "organism": "SECRETARIA DE LA DEFENSA NACIONAL",
            "note_type": None,
            "page": 2,
            "has_full_text": True,
            "publication_date": "20/11/2026",
            "url": DECREE_URL,
        },
        {
            "code": 5804498,
            "title": None,  # scanned note without title: must be skipped
            "edition": "matutina",
            "section": "PODER EJECUTIVO",
            "section_code": "PE",
            "organism": None,
            "note_type": None,
            "page": 14,
            "has_full_text": False,
            "publication_date": "20/11/2026",
            "url": "https://dof.gob.mx/nota_detalle.php?codigo=5804498&fecha=20/11/2026",
        },
        {
            "code": 5804601,
            "title": "TIPO de cambio para solventar obligaciones denominadas en moneda extranjera.",
            "edition": "vespertina",
            "section": "PODER EJECUTIVO",
            "section_code": "PE",
            "organism": "BANCO DE MEXICO",
            "note_type": None,
            "page": 2,
            "has_full_text": True,
            "publication_date": "20/11/2026",
            "url": "https://dof.gob.mx/nota_detalle.php?codigo=5804601&fecha=20/11/2026",
        },
    ]
    return {
        "date": "20-11-2026",
        "published": published,
        "total_notes": len(notes) if published else 0,
        "notes_per_edition": {"matutina": 2, "vespertina": 1} if published else {},
        "notes": notes if published else [],
        "source": "https://sidof.segob.gob.mx/dof/sidof/notas/20-11-2026",
    }


def decree_payload(
    text: str = "Artículo 1.- El presente Reglamento tiene por objeto regular la portación.",
) -> dict[str, Any]:
    return {
        "code": 5804497,
        "title": DECREE_TITLE,
        "publication_date": "20/11/2026",
        "url": DECREE_URL,
        "text": text,
        "total_chars": len(text),
        "truncated": False,
    }


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class Harness:
    """A compiled graph wired to fakes, plus handles on each fake for assertions."""

    def __init__(
        self,
        *,
        route: dict[str, Any] | Callable[..., Any],
        grades: list[Any],
        answers: Sequence[str] = (),
        rewrites: list[Any] | None = None,
        retriever: FakeRetriever | None = None,
        dof_tools: FakeDofTools | None = None,
        settings: AgentSettings | None = None,
    ) -> None:
        self.fast = ScriptedChatModel(
            structured={
                "RouteDecision": [route],
                "GradeDecision": grades,
                "RewrittenQuery": rewrites or [{"query": "consulta reformulada"}],
            }
        )
        self.main = ScriptedChatModel(answers=list(answers))
        self.retriever = retriever or FakeRetriever([lft_chunk()])
        self.dof_tools = dof_tools or FakeDofTools(decrees={DECREE_URL: decree_payload()})
        self.deps = AgentDeps(
            fast_llm=self.fast,
            main_llm=self.main,
            retriever=self.retriever,
            dof_tools=self.dof_tools,
            settings=settings or AgentSettings(chat_model_id="fake"),
            today=lambda: TODAY,
        )
        self.graph = build_graph(self.deps)

    async def run(self, question: str = "¿Cuál es la duración máxima de la jornada diurna?") -> dict[str, Any]:
        """Run the graph; returns the final state plus the ordered list of visited nodes under ``_path``."""
        path: list[str] = []
        final: dict[str, Any] = {}
        async for mode, chunk in self.graph.astream({"question": question}, stream_mode=["updates", "values"]):
            if mode == "updates":
                path.extend(chunk.keys())
            else:
                final = chunk
        return {**final, "_path": path}

    def grader_prompts(self) -> list[str]:
        return [str(msgs[0].content) for name, msgs in self.fast.structured_calls if name == "GradeDecision"]
