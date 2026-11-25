from __future__ import annotations

import json

import pytest

from rag.embeddings import TitanEmbedder
from tests.rag.conftest import FakeBedrock


def test_embed_sends_titan_v2_payload() -> None:
    client = FakeBedrock()
    embedder = TitanEmbedder(client, dimensions=256, max_workers=1)
    vector = embedder.embed("Artículo 1.- Texto")
    assert len(vector) == 256
    call = client.calls[0]
    assert call["modelId"] == "amazon.titan-embed-text-v2:0"
    assert call["contentType"] == "application/json"
    assert json.loads(call["body"]) == {"inputText": "Artículo 1.- Texto", "dimensions": 256, "normalize": True}


def test_embed_many_preserves_order_with_concurrency() -> None:
    embedder = TitanEmbedder(FakeBedrock(), dimensions=256, max_workers=4)
    texts = ["a" * n for n in range(1, 30)]
    vectors = embedder.embed_many(texts)
    assert [v[0] for v in vectors] == [float(len(t)) for t in texts]


def test_embed_many_empty() -> None:
    assert TitanEmbedder(FakeBedrock()).embed_many([]) == []


@pytest.mark.parametrize("bad", ["", "   ", "x" * 50_001])
def test_embed_rejects_invalid_input(bad: str) -> None:
    with pytest.raises(ValueError):
        TitanEmbedder(FakeBedrock()).embed(bad)


def test_rejects_unsupported_dimensions() -> None:
    with pytest.raises(ValueError):
        TitanEmbedder(FakeBedrock(), dimensions=768)


def test_dimension_mismatch_from_model_is_an_error() -> None:
    client = FakeBedrock()
    embedder = TitanEmbedder(client, dimensions=512)
    embedder.dimensions = 1024  # simulate a misconfigured model
    original = client.invoke_model

    def wrong_size(**kwargs: object) -> dict[str, object]:
        body = json.loads(str(kwargs["body"]))
        body["dimensions"] = 512
        return original(**{**kwargs, "body": json.dumps(body)})

    client.invoke_model = wrong_size  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="Expected 1024-d"):
        embedder.embed("texto")
