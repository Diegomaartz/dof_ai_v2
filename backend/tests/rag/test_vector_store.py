from __future__ import annotations

import json

import pytest

from rag.chunker import LegalChunker
from rag.models import LawMetadata, LegalChunk
from rag.vector_store import MAX_METADATA_BYTES, PineconeVectorStore, fit_metadata
from tests.rag.conftest import FakeIndex


def make_chunks(text: str, slug: str = "lp") -> list[LegalChunk]:
    return LegalChunker().chunk(text, LawMetadata(law_name="LEY DE PRUEBA", law_slug=slug))


def vectors(n: int) -> list[list[float]]:
    return [[0.1, 0.2, 0.3, 0.4] for _ in range(n)]


def test_replace_document_upserts_and_prunes_stale_ids(fake_index: FakeIndex) -> None:
    store = PineconeVectorStore(fake_index, namespace="leyes")
    v1 = make_chunks("Artículo 1.- Uno.\nArtículo 2.- Dos.\nArtículo 3.- Tres.\nArtículo 4.- Cuatro.")
    assert store.replace_document("lp", v1, vectors(len(v1))) == 0
    assert fake_index.ids("leyes") == {"lp#art-1", "lp#art-2", "lp#art-3", "lp#art-4"}

    # another law sharing a slug prefix must not be touched
    other = make_chunks("Artículo 1.- Otra ley.", slug="lp2")
    store.replace_document("lp2", other, vectors(1))

    v2 = make_chunks("Artículo 1.- Uno reformado.\nArtículo 2.- Dos.")
    assert store.replace_document("lp", v2, vectors(len(v2))) == 2
    assert fake_index.ids("leyes") == {"lp#art-1", "lp#art-2", "lp2#art-1"}
    assert fake_index.vectors[("leyes", "lp#art-1")]["metadata"]["text"] == "Artículo 1.- Uno reformado."


def test_replace_document_validates_inputs(fake_index: FakeIndex) -> None:
    store = PineconeVectorStore(fake_index)
    chunks = make_chunks("Artículo 1.- Uno.")
    with pytest.raises(ValueError, match="vectors"):
        store.replace_document("lp", chunks, [])
    with pytest.raises(ValueError, match="prefix"):
        store.replace_document("otra", chunks, vectors(1))


def test_upsert_batches_respect_payload_cap(fake_index: FakeIndex) -> None:
    store = PineconeVectorStore(fake_index)
    text = "\n".join(f"Artículo {i}.- {'Texto largo del artículo. ' * 300}" for i in range(1, 121))
    chunks = make_chunks(text)
    store.upsert(chunks, [[0.0] * 1024 for _ in chunks])
    assert sum(fake_index.upsert_calls) == 120
    assert max(fake_index.upsert_calls) < 100, "large records must produce smaller batches"


def test_metadata_has_no_nulls_and_carries_citation(fake_index: FakeIndex) -> None:
    store = PineconeVectorStore(fake_index)
    chunks = make_chunks("Artículo 1.- Uno.")
    store.upsert(chunks, vectors(1))
    meta = fake_index.vectors[("legislacion", "lp#art-1")]["metadata"]
    assert None not in meta.values()
    assert meta["citation"] == "[LEY DE PRUEBA, Art. 1]"
    assert meta["section_type"] == "articulo"


def test_fit_metadata_truncates_oversized_text() -> None:
    meta = {"law_name": "L", "text": "á" * 30_000}
    fitted = fit_metadata(meta)
    assert len(json.dumps(fitted, ensure_ascii=False).encode()) <= MAX_METADATA_BYTES
    assert fitted["text_truncated"] is True
    assert fit_metadata({"text": "corto"}) == {"text": "corto"}


def test_list_ids_accepts_plain_string_pages() -> None:
    class LegacyIndex:
        def list(self, **_: object) -> object:
            yield ["lp#art-1", "lp#art-2"]

    assert list(PineconeVectorStore(LegacyIndex()).list_ids("lp#")) == ["lp#art-1", "lp#art-2"]
