"""Data models shared by the chunker, embedder and vector store."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SectionType(StrEnum):
    """Kind of legal unit a chunk represents."""

    ARTICULO = "articulo"
    TRANSITORIO = "transitorio"


class LawMetadata(BaseModel):
    """Document-level metadata extracted from the law header or supplied by the uploader."""

    law_name: str
    law_slug: str
    publication_date: date | None = None
    last_reform_date: date | None = None
    source_url: str | None = None
    source_key: str | None = None

    def missing_citation_fields(self) -> list[str]:
        """Names of the law-level fields required for citations (CLAUDE.md) that are still empty."""
        required = {"publication_date": self.publication_date, "source_url": self.source_url}
        return [name for name, value in required.items() if not value]


class LegalChunk(BaseModel):
    """One structurally intact legal unit (an article or a transitional article).

    Articles are never cut. The only exception is an article longer than
    ``ChunkerConfig.max_chunk_chars``, which is split on fraction boundaries into
    ordered parts that share the same ``article_label`` (see ``part_index``).
    """

    id: str = Field(description="Deterministic, ASCII-only vector ID prefixed by the law slug.")
    law: LawMetadata
    section_type: SectionType
    article_label: str = Field(description='Article designation as cited, e.g. "2o", "22 Bis", "15-A", "Primero".')
    article_number: int | None = Field(default=None, description="Numeric part of the article, for sorting/filtering.")
    hierarchy: dict[str, str] = Field(
        default_factory=dict, description="libro/titulo/capitulo/seccion -> heading text."
    )
    text: str
    reform_dates: list[date] = Field(default_factory=list, description="Dates of DOF reform notes inside the article.")
    is_repealed: bool = False
    decree_title: str | None = None
    decree_date: date | None = None
    transitorio_block: int | None = Field(
        default=None, description="Index of the TRANSITORIOS block (0 = original law)."
    )
    part_index: int = 1
    part_count: int = 1

    @property
    def citation_date(self) -> date | None:
        """Date used in citations.

        Transitorios cite the DOF publication of the decree that contains them. When that
        date is unknown it is omitted rather than borrowed from the law, which would
        attribute a reform decree to the original publication. Body articles cite their
        latest reform, else the law's publication date.
        """
        if self.section_type is SectionType.TRANSITORIO:
            return self.decree_date
        if self.reform_dates:
            return max(self.reform_dates)
        return self.law.publication_date

    @property
    def hierarchy_path(self) -> str:
        """Human-readable breadcrumb, e.g. ``TITULO PRIMERO Principios Generales > CAPITULO I ...``."""
        return " > ".join(v for v in self.hierarchy.values() if v)

    @property
    def citation(self) -> str:
        """Inline citation in the project format ``[Ley X, Art. Y, DOF DD/MM/YYYY]``."""
        prefix = "Transitorio" if self.section_type is SectionType.TRANSITORIO else "Art."
        parts = [self.law.law_name, f"{prefix} {self.article_label}"]
        if self.citation_date:
            parts.append(f"DOF {self.citation_date:%d/%m/%Y}")
        return f"[{', '.join(parts)}]"

    def embedding_text(self) -> str:
        """Text sent to the embedding model: law + structural context + article body."""
        header = [self.law.law_name]
        if self.hierarchy_path:
            header.append(self.hierarchy_path)
        if self.section_type is SectionType.TRANSITORIO and self.decree_title:
            header.append(f"Transitorios: {self.decree_title}")
        return "\n".join([*header, self.text])

    def to_metadata(self) -> dict[str, Any]:
        """Flatten into Pinecone-compatible metadata (str/number/bool/list[str], no nulls)."""
        raw: dict[str, Any] = {
            "law_name": self.law.law_name,
            "law_slug": self.law.law_slug,
            "publication_date": _iso(self.law.publication_date),
            "law_last_reform_date": _iso(self.law.last_reform_date),
            "source_url": self.law.source_url,
            "source_key": self.law.source_key,
            "section_type": self.section_type.value,
            "article_label": self.article_label,
            "article_number": self.article_number,
            "hierarchy_path": self.hierarchy_path,
            **{k: v for k, v in self.hierarchy.items() if v},
            "reform_dates": [d.isoformat() for d in self.reform_dates] or None,
            "citation_date": _iso(self.citation_date),
            "citation": self.citation,
            "is_repealed": self.is_repealed,
            "decree_title": self.decree_title,
            "decree_date": _iso(self.decree_date),
            "transitorio_block": self.transitorio_block,
            "part_index": self.part_index,
            "part_count": self.part_count,
            "text": self.text,
        }
        return {k: v for k, v in raw.items() if v is not None}


class IngestionResult(BaseModel):
    """Outcome of ingesting one document."""

    law_slug: str
    law_name: str
    source_key: str | None = None
    chunks: int
    articles: int
    transitorios: int
    upserted: int
    deleted_stale: int
    seconds: float


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None
