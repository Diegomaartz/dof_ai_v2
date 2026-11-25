"""Runtime configuration read from environment variables (never hard-coded secrets)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"


@dataclass(frozen=True)
class RagSettings:
    """Settings for embedding and vector storage.

    Attributes:
        aws_region: Region for Bedrock/SSM clients.
        embedding_model_id: Bedrock embedding model ID (``BEDROCK_EMBEDDING_MODEL_ID``).
        embedding_dimensions: Titan v2 output size: 256, 512 or 1024.
        embedding_max_workers: Concurrent Bedrock requests during ingestion.
        pinecone_index_host: Index host URL; preferred over the name (saves a control-plane call).
        pinecone_index_name: Index name, used when no host is configured.
        pinecone_namespace: Namespace holding legislation vectors.
        pinecone_api_key_param: SSM SecureString name holding the API key (cloud).
        max_chunk_chars: Articles longer than this are split on fraction boundaries.
    """

    aws_region: str | None
    embedding_model_id: str
    embedding_dimensions: int
    embedding_max_workers: int
    pinecone_index_host: str | None
    pinecone_index_name: str | None
    pinecone_namespace: str
    pinecone_api_key_param: str | None
    max_chunk_chars: int

    @classmethod
    def from_env(cls) -> RagSettings:
        return cls(
            aws_region=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
            embedding_model_id=os.getenv("BEDROCK_EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID),
            embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1024")),
            embedding_max_workers=int(os.getenv("EMBEDDING_MAX_WORKERS", "8")),
            pinecone_index_host=os.getenv("PINECONE_INDEX_HOST") or None,
            pinecone_index_name=os.getenv("PINECONE_INDEX_NAME") or None,
            pinecone_namespace=os.getenv("PINECONE_NAMESPACE", "legislacion"),
            pinecone_api_key_param=os.getenv("PINECONE_API_KEY_PARAM") or None,
            max_chunk_chars=int(os.getenv("MAX_CHUNK_CHARS", "8000")),
        )


@lru_cache(maxsize=1)
def get_pinecone_api_key(settings: RagSettings) -> str:
    """Resolve the Pinecone API key: ``PINECONE_API_KEY`` locally, SSM SecureString in AWS."""
    if key := os.getenv("PINECONE_API_KEY"):
        return key
    if settings.pinecone_api_key_param:
        import boto3

        ssm = boto3.client("ssm", region_name=settings.aws_region)
        resp = ssm.get_parameter(Name=settings.pinecone_api_key_param, WithDecryption=True)
        return str(resp["Parameter"]["Value"])
    raise RuntimeError("Set PINECONE_API_KEY (local) or PINECONE_API_KEY_PARAM (SSM parameter name).")
