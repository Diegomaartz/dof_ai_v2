from __future__ import annotations

import io
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from rag.models import LawMetadata

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def lft_excerpt_bytes() -> bytes:
    """Real excerpt of the Ley Federal del Trabajo (public-domain legal text, LFDA art. 14 fr. VIII)."""
    return (FIXTURES / "lft_excerpt.txt").read_bytes()


@pytest.fixture
def law() -> LawMetadata:
    return LawMetadata(law_name="LEY DE PRUEBA", law_slug="lp", publication_date=date(2000, 1, 1))


class FakeBedrock:
    """Minimal bedrock-runtime stand-in returning deterministic embeddings."""

    def __init__(self, dimensions: int = 8) -> None:
        self.dimensions = dimensions
        self.calls: list[dict[str, Any]] = []

    def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        body = json.loads(kwargs["body"])
        seed = float(len(body["inputText"]))
        payload = {"embedding": [seed] * body["dimensions"], "inputTextTokenCount": 1}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


class FakeEmbedder:
    dimensions = 4

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts.extend(texts)
        return [[float(i)] * self.dimensions for i, _ in enumerate(texts)]


class FakeIndex:
    """In-memory Pinecone index supporting upsert/list/delete with prefixes and namespaces."""

    def __init__(self, page_size: int = 3) -> None:
        self.vectors: dict[tuple[str, str], dict[str, Any]] = {}
        self.upsert_calls: list[int] = []
        self.page_size = page_size

    def upsert(self, *, vectors: list[dict[str, Any]], namespace: str = "", **_: Any) -> None:
        self.upsert_calls.append(len(vectors))
        for v in vectors:
            self.vectors[(namespace, v["id"])] = v

    def list(self, *, prefix: str | None = None, namespace: str = "", **_: Any) -> Any:
        ids = sorted(vid for ns, vid in self.vectors if ns == namespace and vid.startswith(prefix or ""))
        for i in range(0, len(ids), self.page_size):
            yield type("Page", (), {"vectors": [type("Item", (), {"id": x})() for x in ids[i : i + self.page_size]]})()

    def delete(self, *, ids: list[str], namespace: str = "", **_: Any) -> None:
        for vid in ids:
            self.vectors.pop((namespace, vid), None)

    def ids(self, namespace: str) -> set[str]:
        return {vid for ns, vid in self.vectors if ns == namespace}


@pytest.fixture
def fake_index() -> FakeIndex:
    return FakeIndex()


@pytest.fixture
def fake_embedder() -> FakeEmbedder:
    return FakeEmbedder()
