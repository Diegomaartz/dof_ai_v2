"""Structured tool outputs. These schemas are published to MCP clients as each tool's output schema."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Edition = Literal["matutina", "vespertina", "extraordinaria"]


class DofNote(BaseModel):
    """One publication (decree, agreement, notice, ...) listed in a DOF edition."""

    code: int = Field(description="DOF note identifier (codigo); pass `url` to extract_decree_text for full text.")
    title: str | None = Field(description="Official title of the publication, when the DOF provides one.")
    edition: Edition = Field(description="Edition of the day the note was published in.")
    section: str | None = Field(description="Top-level section, e.g. 'PODER EJECUTIVO' or 'ORGANISMOS AUTONOMOS'.")
    section_code: str | None = Field(description="Short section code (PE, PL, PJ, OA, AV, ...).")
    organism: str | None = Field(description="Issuing body, e.g. 'SECRETARIA DE GOBERNACION', if reported.")
    note_type: str | None = Field(description="Note type reported by the DOF (e.g. 'AVISO'), if any.")
    page: int | None = Field(description="Starting page within the printed edition.")
    has_full_text: bool = Field(
        description="Whether extract_decree_text can return text; false for scanned image/PDF-only notes."
    )
    publication_date: str = Field(description="Publication date, DD/MM/YYYY.")
    url: str = Field(description="Public dof.gob.mx link to the note.")


class DofEditionResult(BaseModel):
    """All notes published in the DOF on a given date, across its editions."""

    date: str = Field(description="Requested date, DD-MM-YYYY.")
    published: bool = Field(description="False when the DOF published nothing that day (weekends, holidays).")
    total_notes: int
    notes_per_edition: dict[str, int] = Field(description="Number of notes in each edition that was published.")
    notes: list[DofNote] = Field(description="Notes ordered by edition, section and position in the gazette.")
    source: str = Field(description="Upstream endpoint the data was obtained from.")


class DecreeTextResult(BaseModel):
    """Clean plain text of a single DOF publication."""

    code: int
    title: str | None
    publication_date: str | None = Field(description="Publication date, DD/MM/YYYY.")
    url: str = Field(description="Public dof.gob.mx link to the note; cite this as the source.")
    text: str = Field(description="Plain text of the publication, paragraphs separated by newlines.")
    total_chars: int = Field(description="Length of the full text before any truncation.")
    truncated: bool = Field(description="True when `text` was cut to the server's maximum length.")
