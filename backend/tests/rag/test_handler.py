from __future__ import annotations

import io
from datetime import date
from typing import Any

import pytest

from rag.handler import lambda_handler
from rag.service import DocumentSource, IngestionService, NoArticlesFoundError
from rag.vector_store import PineconeVectorStore
from tests.rag.conftest import FakeEmbedder, FakeIndex


class FakeS3:
    def __init__(self, objects: dict[str, tuple[bytes, dict[str, str]]]) -> None:
        self.objects = objects
        self.requested: list[tuple[str, str]] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.requested.append((Bucket, Key))
        data, meta = self.objects[Key]
        return {"Body": io.BytesIO(data), "Metadata": meta}


def s3_event(*keys: str, event_name: str = "ObjectCreated:Put") -> dict[str, Any]:
    return {
        "Records": [
            {
                "eventSource": "aws:s3",
                "eventName": event_name,
                "s3": {"bucket": {"name": "raw-laws"}, "object": {"key": k}},
            }
            for k in keys
        ]
    }


@pytest.fixture
def service(fake_embedder: FakeEmbedder, fake_index: FakeIndex) -> IngestionService:
    return IngestionService(fake_embedder, PineconeVectorStore(fake_index, namespace="leyes"))


def test_handler_ingests_url_encoded_key_with_metadata_overrides(
    service: IngestionService, fake_index: FakeIndex, fake_embedder: FakeEmbedder, lft_excerpt_bytes: bytes
) -> None:
    key = "leyes/Ley Federal del Trabajo.txt"
    s3 = FakeS3(
        {
            key: (
                lft_excerpt_bytes,
                {"law-id": "LFT", "source-url": "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf"},
            )
        }
    )

    summary = lambda_handler(s3_event("leyes/Ley+Federal+del+Trabajo.txt"), None, service=service, s3=s3)

    assert s3.requested == [("raw-laws", key)]
    [result] = summary["ingested"]
    assert result["law_slug"] == "lft"
    assert result["articles"] == 29 and result["transitorios"] == 16
    assert result["source_key"] == f"s3://raw-laws/{key}"
    ids = fake_index.ids("leyes")
    assert len(ids) == result["chunks"] and all(i.startswith("lft#") for i in ids)
    meta = fake_index.vectors[("leyes", "lft#art-2o")]["metadata"]
    assert meta["source_url"] == "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf"
    assert meta["citation"] == "[LEY FEDERAL DEL TRABAJO, Art. 2o, DOF 15/01/2026]"
    assert fake_embedder.texts[0].startswith("LEY FEDERAL DEL TRABAJO\nTITULO PRIMERO")


def test_handler_reingest_is_idempotent(
    service: IngestionService, fake_index: FakeIndex, lft_excerpt_bytes: bytes
) -> None:
    s3 = FakeS3({"LFT.txt": (lft_excerpt_bytes, {})})
    lambda_handler(s3_event("LFT.txt"), None, service=service, s3=s3)
    first = fake_index.ids("leyes")
    summary = lambda_handler(s3_event("LFT.txt"), None, service=service, s3=s3)
    assert fake_index.ids("leyes") == first
    assert summary["ingested"][0]["deleted_stale"] == 0


def test_handler_skips_unsupported_and_non_create_events(service: IngestionService) -> None:
    s3 = FakeS3({})
    summary = lambda_handler(s3_event("notas/readme.md"), None, service=service, s3=s3)
    assert summary["skipped"] == ["notas/readme.md"]
    summary = lambda_handler(s3_event("LFT.pdf", event_name="ObjectRemoved:Delete"), None, service=service, s3=s3)
    assert summary == {"ingested": [], "skipped": [], "failed": []}
    assert s3.requested == []


def test_handler_raises_after_processing_all_records(
    service: IngestionService, fake_index: FakeIndex, lft_excerpt_bytes: bytes
) -> None:
    s3 = FakeS3({"vacio.txt": (b"Documento sin articulos.", {}), "LFT.txt": (lft_excerpt_bytes, {})})
    with pytest.raises(RuntimeError, match=r"vacio.txt"):
        lambda_handler(s3_event("vacio.txt", "LFT.txt"), None, service=service, s3=s3)
    assert any(i.startswith("lft#") for i in fake_index.ids("leyes")), "valid record still ingested"


def test_empty_document_never_wipes_existing_vectors(service: IngestionService, fake_index: FakeIndex) -> None:
    service.ingest(DocumentSource(filename="LP.txt", data="Artículo 1.- Uno.".encode()))
    with pytest.raises(NoArticlesFoundError):
        service.ingest(DocumentSource(filename="LP.txt", data=b"   "))
    assert fake_index.ids("leyes") == {"lp#art-1"}


def test_document_source_from_s3_metadata() -> None:
    src = DocumentSource.from_s3(
        "b", "dir/LAmp.pdf", b"", {"Law-Name": "LEY DE AMPARO", "publication-date": "2013-04-02", "source-url": " "}
    )
    assert src.filename == "LAmp.pdf"
    assert src.law_name == "LEY DE AMPARO"
    assert src.publication_date == date(2013, 4, 2)
    assert src.source_url is None
    assert src.source_key == "s3://b/dir/LAmp.pdf"
