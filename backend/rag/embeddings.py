"""Amazon Bedrock Titan Text Embeddings v2 client."""

from __future__ import annotations

import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Protocol

TITAN_V2_MAX_CHARS = 50_000
TITAN_V2_DIMENSIONS = frozenset({256, 512, 1024})


class Embedder(Protocol):
    """Anything that turns texts into dense vectors."""

    dimensions: int

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]: ...


class TitanEmbedder:
    """Embeds texts with ``amazon.titan-embed-text-v2:0`` via ``bedrock-runtime:InvokeModel``.

    Titan v2 accepts one text per request, so ``embed_many`` fans requests out on a
    thread pool (boto3 clients are thread-safe). Throttling is absorbed by botocore's
    adaptive retry mode configured in :meth:`create_client`.
    """

    def __init__(
        self,
        client: Any,
        model_id: str = "amazon.titan-embed-text-v2:0",
        dimensions: int = 1024,
        normalize: bool = True,
        max_workers: int = 8,
    ) -> None:
        if dimensions not in TITAN_V2_DIMENSIONS:
            raise ValueError(f"Titan v2 supports dimensions {sorted(TITAN_V2_DIMENSIONS)}, got {dimensions}")
        self._client = client
        self.model_id = model_id
        self.dimensions = dimensions
        self.normalize = normalize
        self.max_workers = max_workers

    @staticmethod
    def create_client(region: str | None = None, max_workers: int = 8) -> Any:
        """Build a ``bedrock-runtime`` client sized for concurrent embedding calls."""
        import boto3
        from botocore.config import Config

        config = Config(
            retries={"max_attempts": 10, "mode": "adaptive"},
            max_pool_connections=max(10, max_workers * 2),
        )
        return boto3.client("bedrock-runtime", region_name=region, config=config)

    def embed(self, text: str) -> list[float]:
        """Embed a single text."""
        if not text.strip():
            raise ValueError("Cannot embed empty text")
        if len(text) > TITAN_V2_MAX_CHARS:
            raise ValueError(f"Text has {len(text)} chars; Titan v2 accepts at most {TITAN_V2_MAX_CHARS}")
        body = json.dumps({"inputText": text, "dimensions": self.dimensions, "normalize": self.normalize})
        response = self._client.invoke_model(
            modelId=self.model_id, body=body, contentType="application/json", accept="application/json"
        )
        payload = json.loads(response["body"].read())
        embedding: list[float] = payload["embedding"]
        if len(embedding) != self.dimensions:
            raise RuntimeError(f"Expected {self.dimensions}-d embedding, got {len(embedding)}")
        return embedding

    def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts concurrently, preserving input order."""
        if not texts:
            return []
        if self.max_workers <= 1 or len(texts) == 1:
            return [self.embed(t) for t in texts]
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            return list(pool.map(self.embed, texts))
