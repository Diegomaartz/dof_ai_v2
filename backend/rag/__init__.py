"""Structural legal chunking and Pinecone ingestion for Mexican legislation.

The package is framework-agnostic so it can run inside the ingestion Lambda
without Django. The Django backend consumes it through :mod:`rag.service`.
"""

from rag.chunker import ChunkerConfig, LegalChunker
from rag.models import IngestionResult, LawMetadata, LegalChunk, SectionType

__all__ = [
    "ChunkerConfig",
    "IngestionResult",
    "LawMetadata",
    "LegalChunk",
    "LegalChunker",
    "SectionType",
]
