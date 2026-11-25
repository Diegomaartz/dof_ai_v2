"""Conversions from retrieval results (Pinecone chunks, MCP tool JSON) into :class:`Source` records."""

from __future__ import annotations

from datetime import date
from typing import Any

from agent.state import Source
from rag.retrieval import RetrievedChunk

_TITLE_CITATION_CHARS = 120
# Words a shortened title must not end on ("... Armas de Fuego y...").
_DANGLING = frozenset(
    {
        "a",
        "al",
        "con",
        "de",
        "del",
        "e",
        "el",
        "en",
        "la",
        "las",
        "lo",
        "los",
        "o",
        "para",
        "por",
        "que",
        "se",
        "u",
        "y",
    }
)


def _iso_to_citation_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value).strftime("%d/%m/%Y")
    except ValueError:
        return None


def chunk_to_source(chunk: RetrievedChunk) -> Source:
    """Wrap a retrieved law article; its citation was computed at ingestion time and is used verbatim."""
    prefix = "Transitorio" if chunk.section_type == "transitorio" else "Art."
    return Source(
        id=chunk.id,
        kind="legislacion",
        citation=chunk.citation,
        title=f"{chunk.law_name}, {prefix} {chunk.article_label}",
        text=chunk.text,
        url=chunk.source_url,
        date=_iso_to_citation_date(chunk.citation_date),
        hierarchy=chunk.hierarchy_path,
        score=chunk.score,
        text_is_complete=not chunk.text_truncated,
        is_repealed=chunk.is_repealed,
    )


def short_title(title: str, limit: int = _TITLE_CITATION_CHARS) -> str:
    """Shorten a DOF title on a word boundary so it can be copied verbatim into a citation."""
    clean = " ".join(title.split()).rstrip(".")
    if len(clean) <= limit:
        return clean
    words = clean[:limit].rsplit(" ", 1)[0].split(" ")
    while len(words) > 1 and words[-1].casefold().rstrip(",;:") in _DANGLING:
        words.pop()
    return " ".join(words).rstrip(",;:") + "..."


def dof_citation(title: str, publication_date: str | None) -> str:
    """Inline citation for a DOF publication: ``[<título abreviado>, DOF DD/MM/YYYY]``."""
    parts = [short_title(title)]
    if publication_date:
        parts.append(f"DOF {publication_date}")
    return f"[{', '.join(parts)}]"


def note_to_source(note: dict[str, Any]) -> Source | None:
    """Wrap one note listed by get_dof_today / search_dof_by_date. Untitled notes cannot be cited and are skipped."""
    title = note.get("title")
    if not title:
        return None
    details = [
        f"Sección: {note['section']}" if note.get("section") else None,
        f"Emisor: {note['organism']}" if note.get("organism") else None,
        f"Edición {note['edition']}" if note.get("edition") else None,
        f"página {note['page']}" if note.get("page") else None,
    ]
    publication_date = note.get("publication_date") or None
    return Source(
        id=f"dof:{note['code']}",
        kind="dof",
        citation=dof_citation(title, publication_date),
        title=" ".join(str(title).split()),
        text="\n".join([str(title), "; ".join(d for d in details if d)]).strip(),
        url=note.get("url"),
        date=publication_date,
        full_text_available=bool(note.get("has_full_text")),
        text_is_complete=False,  # only the title and listing data until the decree text is fetched
    )


def with_decree_text(source: Source, decree: dict[str, Any], max_chars: int) -> Source:
    """Replace a DOF listing summary with (a prefix of) the decree's full text."""
    text = str(decree.get("text") or "")
    complete = not decree.get("truncated") and len(text) <= max_chars
    return source.model_copy(update={"text": text[:max_chars], "text_is_complete": complete, "text_fetched": True})
