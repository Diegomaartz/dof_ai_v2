"""Ingestion pipeline: document bytes -> structural chunks -> Titan embeddings -> Pinecone."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import PurePosixPath

from rag.chunker import LegalChunker, parse_law_header, slugify
from rag.embeddings import Embedder
from rag.loaders import load_document
from rag.models import IngestionResult, LawMetadata, LegalChunk, SectionType
from rag.vector_store import PineconeVectorStore

logger = logging.getLogger(__name__)


class NoArticlesFoundError(ValueError):
    """The document produced no chunks; existing vectors are left untouched."""


@dataclass(frozen=True)
class DocumentSource:
    """A document to ingest plus optional uploader-supplied overrides.

    Overrides come from S3 user metadata (``x-amz-meta-law-name``, ``x-amz-meta-law-id``,
    ``x-amz-meta-source-url``, ``x-amz-meta-publication-date`` as ``YYYY-MM-DD``) and win
    over values parsed from the document header.
    """

    filename: str
    data: bytes
    source_key: str | None = None
    source_url: str | None = None
    law_name: str | None = None
    law_slug: str | None = None
    publication_date: date | None = None

    @classmethod
    def from_s3(cls, bucket: str, key: str, data: bytes, metadata: Mapping[str, str]) -> DocumentSource:
        meta = {k.lower(): v.strip() for k, v in metadata.items() if v and v.strip()}
        pub = meta.get("publication-date")
        return cls(
            filename=PurePosixPath(key).name,
            data=data,
            source_key=f"s3://{bucket}/{key}",
            source_url=meta.get("source-url"),
            law_name=meta.get("law-name"),
            law_slug=slugify(meta["law-id"]) if "law-id" in meta else None,
            publication_date=date.fromisoformat(pub) if pub else None,
        )


class IngestionService:
    """Coordinates loading, structural chunking, embedding and vector upsert."""

    def __init__(self, embedder: Embedder, store: PineconeVectorStore, chunker: LegalChunker | None = None) -> None:
        self.embedder = embedder
        self.store = store
        self.chunker = chunker or LegalChunker()

    def build_chunks(self, source: DocumentSource) -> list[LegalChunk]:
        """Load and chunk a document without touching AWS or Pinecone."""
        return build_chunks(source, self.chunker)

    def ingest(self, source: DocumentSource) -> IngestionResult:
        """Index *source*, replacing any previous version of the same law."""
        started = time.perf_counter()
        chunks = self.build_chunks(source)
        law = chunks[0].law
        vectors = self.embedder.embed_many([c.embedding_text() for c in chunks])
        deleted = self.store.replace_document(law.law_slug, chunks, vectors)
        result = IngestionResult(
            law_slug=law.law_slug,
            law_name=law.law_name,
            source_key=law.source_key,
            chunks=len(chunks),
            articles=sum(c.section_type is SectionType.ARTICULO and c.part_index == 1 for c in chunks),
            transitorios=sum(c.section_type is SectionType.TRANSITORIO and c.part_index == 1 for c in chunks),
            upserted=len(chunks),
            deleted_stale=deleted,
            seconds=round(time.perf_counter() - started, 2),
        )
        logger.info("ingestion complete", extra={"result": result.model_dump()})
        return result


def build_chunks(source: DocumentSource, chunker: LegalChunker | None = None) -> list[LegalChunk]:
    """Pure function behind :meth:`IngestionService.build_chunks` (used by the CLI dry run)."""
    doc = load_document(source.data, source.filename)
    parsed_name, parsed_pub, last_reform = parse_law_header(doc.first_page)
    law_name = source.law_name or parsed_name or PurePosixPath(source.filename).stem
    law = LawMetadata(
        law_name=law_name,
        # File stems from diputados.gob.mx ("LFT", "LAmp", "CPEUM") are short, unique law codes.
        law_slug=source.law_slug or slugify(PurePosixPath(source.filename).stem) or slugify(law_name),
        publication_date=source.publication_date or parsed_pub,
        last_reform_date=last_reform,
        source_url=source.source_url,
        source_key=source.source_key,
    )
    chunks = (chunker or LegalChunker()).chunk(doc.text, law)
    if not chunks:
        raise NoArticlesFoundError(f"No articles detected in {source.filename!r}; is it a scanned PDF without text?")
    return chunks
