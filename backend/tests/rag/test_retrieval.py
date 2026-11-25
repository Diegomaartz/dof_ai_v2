"""PineconeRetriever with a fake embedder and a fake Pinecone index."""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from rag.retrieval import PineconeRetriever


class FakeEmbedder:
    dimensions = 4

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]


class FakeIndex:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


METADATA = {
    "law_name": "Ley Federal del Trabajo",
    "article_label": "61",
    "section_type": "articulo",
    "hierarchy_path": "TITULO TERCERO > CAPITULO II",
    "citation_date": "2012-11-30",
    "citation": "[Ley Federal del Trabajo, Art. 61, DOF 30/11/2012]",
    "source_url": "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf",
    "text": "Artículo 61.- La duración máxima de la jornada será: ocho horas la diurna...",
}


def test_query_maps_sdk_objects_to_chunks() -> None:
    response = SimpleNamespace(matches=[SimpleNamespace(id="lft#art-61", score=0.87, metadata=METADATA)])
    index, embedder = FakeIndex(response), FakeEmbedder()
    chunks = PineconeRetriever(embedder, index, namespace="legislacion").search("jornada diurna", top_k=5)

    assert embedder.texts == ["jornada diurna"]
    assert index.calls == [
        {"vector": [0.1, 0.2, 0.3, 0.4], "top_k": 5, "namespace": "legislacion", "include_metadata": True}
    ]
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.id == "lft#art-61"
    assert chunk.citation == METADATA["citation"]
    assert chunk.hierarchy_path == "TITULO TERCERO > CAPITULO II"
    assert chunk.text_truncated is False


def test_dict_responses_and_uncitable_matches() -> None:
    response = {
        "matches": [
            {"id": "a", "score": 0.9, "metadata": {**METADATA, "text_truncated": True}},
            {"id": "b", "score": 0.8, "metadata": {"law_name": "sin cita", "text": "x"}},  # no citation: dropped
            {"id": "c", "score": 0.7, "metadata": None},
        ]
    }
    chunks = PineconeRetriever(FakeEmbedder(), FakeIndex(response)).search("q", top_k=3)
    assert [c.id for c in chunks] == ["a"]
    assert chunks[0].text_truncated is True


def test_min_score_filters_weak_matches() -> None:
    response = {"matches": [{"id": "a", "score": 0.2, "metadata": METADATA}]}
    assert PineconeRetriever(FakeEmbedder(), FakeIndex(response), min_score=0.3).search("q", top_k=3) == []


def test_blank_query_skips_embedding() -> None:
    embedder = FakeEmbedder()
    assert PineconeRetriever(embedder, FakeIndex({"matches": []})).search("   ", top_k=3) == []
    assert embedder.texts == []
