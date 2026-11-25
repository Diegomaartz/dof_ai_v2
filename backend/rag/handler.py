"""AWS Lambda entry point: index laws uploaded to the raw-documents S3 bucket.

Triggered by ``s3:ObjectCreated:*``. Configuration comes from environment
variables (see :class:`rag.config.RagSettings`); credentials come from the
function's IAM role.
"""

from __future__ import annotations

import json
import logging
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import unquote_plus

from rag.config import RagSettings, get_pinecone_api_key
from rag.embeddings import TitanEmbedder
from rag.loaders import SUPPORTED_EXTENSIONS
from rag.service import DocumentSource, IngestionService
from rag.vector_store import PineconeVectorStore

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Reused across warm invocations.
_service: IngestionService | None = None
_s3: Any = None


def _get_service() -> IngestionService:
    global _service
    if _service is None:
        settings = RagSettings.from_env()
        embedder = TitanEmbedder(
            TitanEmbedder.create_client(settings.aws_region, settings.embedding_max_workers),
            model_id=settings.embedding_model_id,
            dimensions=settings.embedding_dimensions,
            max_workers=settings.embedding_max_workers,
        )
        store = PineconeVectorStore.from_settings(
            api_key=get_pinecone_api_key(settings),
            host=settings.pinecone_index_host,
            name=settings.pinecone_index_name,
            namespace=settings.pinecone_namespace,
        )
        from rag.chunker import ChunkerConfig, LegalChunker

        _service = IngestionService(embedder, store, LegalChunker(ChunkerConfig(settings.max_chunk_chars)))
    return _service


def _get_s3() -> Any:
    global _s3
    if _s3 is None:
        import boto3

        _s3 = boto3.client("s3")
    return _s3


def lambda_handler(
    event: dict[str, Any], context: Any, *, service: IngestionService | None = None, s3: Any = None
) -> dict[str, Any]:
    """Process every S3 record; raise at the end if any failed so Lambda retries the event.

    Re-processing is safe: vector IDs are deterministic, so a retry overwrites
    instead of duplicating.
    """
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    skipped: list[str] = []

    for record in event.get("Records", []):
        if record.get("eventSource") != "aws:s3" or not record.get("eventName", "").startswith("ObjectCreated"):
            continue
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        if PurePosixPath(key.lower()).suffix not in SUPPORTED_EXTENSIONS:
            skipped.append(key)
            continue
        try:
            obj = (s3 or _get_s3()).get_object(Bucket=bucket, Key=key)
            source = DocumentSource.from_s3(bucket, key, obj["Body"].read(), obj.get("Metadata", {}))
            result = (service or _get_service()).ingest(source)
            results.append(result.model_dump(mode="json"))
            logger.info(json.dumps({"event": "ingested", **results[-1]}))
        except Exception as exc:  # report every record, then fail the invocation
            logger.exception(json.dumps({"event": "ingestion_failed", "bucket": bucket, "key": key}))
            failures.append({"key": key, "error": f"{type(exc).__name__}: {exc}"})

    summary = {"ingested": results, "skipped": skipped, "failed": failures}
    if failures:
        raise RuntimeError(f"Ingestion failed for {len(failures)} object(s): {json.dumps(failures)}")
    return summary
