"""Pinecone persistence for legal chunks."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from rag.models import LegalChunk

# Pinecone limits: 40 KB metadata per vector, 2 MB / 1000 vectors per upsert request.
MAX_METADATA_BYTES = 40_000
UPSERT_BATCH_SIZE = 100
UPSERT_MAX_BYTES = 1_500_000
DELETE_BATCH_SIZE = 1000


class PineconeVectorStore:
    """Upserts chunks into a Pinecone serverless index and prunes stale IDs.

    Every vector ID starts with ``"<law_slug>#"``. Re-ingesting a law therefore
    overwrites its vectors in place and :meth:`replace_document` deletes the IDs
    that no longer exist (e.g. after a reform that removed or renumbered articles).
    Serverless indexes do not support delete-by-metadata, which is why the prefix
    convention matters.
    """

    def __init__(self, index: Any, namespace: str = "legislacion") -> None:
        self._index = index
        self.namespace = namespace

    @classmethod
    def from_settings(cls, api_key: str, host: str | None, name: str | None, namespace: str) -> PineconeVectorStore:
        from pinecone import Pinecone

        pc = Pinecone(api_key=api_key)
        if host:
            index = pc.Index(host=host)
        elif name:
            index = pc.Index(name=name)
        else:
            raise RuntimeError("Set PINECONE_INDEX_HOST or PINECONE_INDEX_NAME")
        return cls(index, namespace)

    def replace_document(self, law_slug: str, chunks: Sequence[LegalChunk], vectors: Sequence[list[float]]) -> int:
        """Upsert *chunks* and delete any other vector of the same law. Returns deleted count."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        prefix = f"{law_slug}#"
        if bad := [c.id for c in chunks if not c.id.startswith(prefix)]:
            raise ValueError(f"Chunk IDs outside prefix {prefix!r}: {bad[:3]}")
        self.upsert(chunks, vectors)
        keep = {c.id for c in chunks}
        stale = [vid for vid in self.list_ids(prefix) if vid not in keep]
        self.delete(stale)
        return len(stale)

    def upsert(self, chunks: Sequence[LegalChunk], vectors: Sequence[list[float]]) -> None:
        records = [
            {"id": c.id, "values": v, "metadata": fit_metadata(c.to_metadata())}
            for c, v in zip(chunks, vectors, strict=True)
        ]
        for batch in _batched_by_size(records):
            self._index.upsert(vectors=batch, namespace=self.namespace, show_progress=False)

    def list_ids(self, prefix: str) -> Iterator[str]:
        for page in self._index.list(prefix=prefix, namespace=self.namespace):
            yield from _page_ids(page)

    def delete(self, ids: Sequence[str]) -> None:
        for batch in _batched(list(ids), DELETE_BATCH_SIZE):
            self._index.delete(ids=batch, namespace=self.namespace)


def fit_metadata(metadata: dict[str, Any], limit: int = MAX_METADATA_BYTES) -> dict[str, Any]:
    """Truncate the ``text`` field if the metadata would exceed Pinecone's per-vector limit.

    The chunker keeps chunks well below the limit; this is a last-resort guard so
    one unusual article cannot fail a whole ingestion.
    """
    size = len(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
    if size <= limit or "text" not in metadata:
        return metadata
    text: str = metadata["text"]
    overflow = size - limit + 64
    encoded = text.encode("utf-8")[: max(0, len(text.encode("utf-8")) - overflow)]
    return {**metadata, "text": encoded.decode("utf-8", "ignore"), "text_truncated": True}


def _page_ids(page: Any) -> Iterable[str]:
    """Support both SDK shapes: a list of IDs (<= v6) or a ListResponse with ``.vectors``."""
    items = getattr(page, "vectors", page)
    for item in items:
        vid = item if isinstance(item, str) else getattr(item, "id", None)
        if vid:
            yield vid


def _batched_by_size(records: Sequence[dict[str, Any]]) -> Iterator[list[dict[str, Any]]]:
    """Group records so each request stays under both the count and the payload cap."""
    batch: list[dict[str, Any]] = []
    batch_bytes = 0
    for rec in records:
        # ~20 bytes per JSON-encoded float plus the metadata payload.
        rec_bytes = len(rec["values"]) * 20 + len(json.dumps(rec["metadata"], ensure_ascii=False).encode("utf-8"))
        if batch and (len(batch) >= UPSERT_BATCH_SIZE or batch_bytes + rec_bytes > UPSERT_MAX_BYTES):
            yield batch
            batch, batch_bytes = [], 0
        batch.append(rec)
        batch_bytes += rec_bytes
    if batch:
        yield batch


def _batched(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
