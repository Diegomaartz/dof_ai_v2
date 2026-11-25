"""Query-time retrieval over the legislation index: the service interface the agent depends on.

The agent never talks to Pinecone directly (CLAUDE.md boundary); it receives any object that
satisfies :class:`LegalRetriever`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel, Field

from rag.config import RagSettings, get_pinecone_api_key
from rag.embeddings import Embedder, TitanEmbedder


class RetrievedChunk(BaseModel):
    """One legal unit returned for a query, carrying everything needed to cite it."""

    id: str
    score: float
    citation: str = Field(description="Ready-made inline citation, e.g. '[Ley Federal del Trabajo, Art. 2o, DOF ...]'.")
    law_name: str
    article_label: str
    section_type: str
    hierarchy_path: str | None = None
    citation_date: str | None = Field(default=None, description="ISO date used in the citation, if known.")
    source_url: str | None = None
    is_repealed: bool = False
    text: str
    text_truncated: bool = False


class LegalRetriever(Protocol):
    """Anything that returns the legal chunks most relevant to a natural-language query."""

    def search(self, query: str, top_k: int) -> list[RetrievedChunk]: ...


class PineconeRetriever:
    """Embeds the query with the ingestion embedder (Titan v2) and runs a Pinecone similarity query."""

    def __init__(self, embedder: Embedder, index: Any, namespace: str = "legislacion", min_score: float = 0.0) -> None:
        self._embedder = embedder
        self._index = index
        self.namespace = namespace
        self.min_score = min_score

    @classmethod
    def from_settings(cls, settings: RagSettings | None = None, min_score: float = 0.0) -> PineconeRetriever:
        """Build the production retriever (Bedrock Titan v2 + Pinecone) from environment settings."""
        from pinecone import Pinecone

        cfg = settings or RagSettings.from_env()
        embedder = TitanEmbedder(
            TitanEmbedder.create_client(cfg.aws_region, max_workers=1),
            model_id=cfg.embedding_model_id,
            dimensions=cfg.embedding_dimensions,
            max_workers=1,
        )
        pc = Pinecone(api_key=get_pinecone_api_key(cfg))
        if cfg.pinecone_index_host:
            index = pc.Index(host=cfg.pinecone_index_host)
        elif cfg.pinecone_index_name:
            index = pc.Index(name=cfg.pinecone_index_name)
        else:
            raise RuntimeError("Set PINECONE_INDEX_HOST or PINECONE_INDEX_NAME")
        return cls(embedder, index, cfg.pinecone_namespace, min_score)

    def search(self, query: str, top_k: int) -> list[RetrievedChunk]:
        """Return up to ``top_k`` chunks ordered by similarity, skipping matches without citable metadata."""
        if not query.strip():
            return []
        vector = self._embedder.embed_many([query])[0]
        response = self._index.query(vector=vector, top_k=top_k, namespace=self.namespace, include_metadata=True)
        chunks: list[RetrievedChunk] = []
        for match in _matches(response):
            chunk = _to_chunk(match)
            if chunk is not None and chunk.score >= self.min_score:
                chunks.append(chunk)
        return chunks


def _field(obj: Any, name: str) -> Any:
    return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)


def _matches(response: Any) -> list[Any]:
    return list(_field(response, "matches") or [])


def _to_chunk(match: Any) -> RetrievedChunk | None:
    metadata: Mapping[str, Any] = _field(match, "metadata") or {}
    citation, text = metadata.get("citation"), metadata.get("text")
    if not citation or not text:
        return None  # a chunk that cannot be cited must never reach the generator
    return RetrievedChunk(
        id=str(_field(match, "id")),
        score=float(_field(match, "score") or 0.0),
        citation=str(citation),
        law_name=str(metadata.get("law_name", "")),
        article_label=str(metadata.get("article_label", "")),
        section_type=str(metadata.get("section_type", "")),
        hierarchy_path=metadata.get("hierarchy_path") or None,
        citation_date=metadata.get("citation_date") or None,
        source_url=metadata.get("source_url") or None,
        is_repealed=bool(metadata.get("is_repealed", False)),
        text=str(text),
        text_truncated=bool(metadata.get("text_truncated", False)),
    )
