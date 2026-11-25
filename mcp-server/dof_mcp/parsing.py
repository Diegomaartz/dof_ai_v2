"""Pure functions that turn SIDOF API payloads and DOF URLs into tool outputs.

Nothing here performs I/O, so every function is unit-testable with static fixtures.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any, Final
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup, Tag

from dof_mcp.models import DecreeTextResult, DofEditionResult, DofNote, Edition

# SIDOF groups each day's notes by edition under these keys, in publication order.
EDITION_KEYS: Final[tuple[tuple[Edition, str], ...]] = (
    ("matutina", "NotasMatutinas"),
    ("vespertina", "NotasVespertinas"),
    ("extraordinaria", "NotasExtraordinarias"),
)

ALLOWED_URL_HOSTS: Final = frozenset({"dof.gob.mx", "www.dof.gob.mx", "sidof.segob.gob.mx"})

_SIDOF_NOTE_PATH = re.compile(r"/notas/nota/(\d+)/?$")
_BLOCK_TAGS: Final = ("p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "table", "blockquote", "pre")
_CELL_TAGS: Final = ("td", "th")
_DROP_TAGS: Final = ("head", "style", "script", "title", "meta", "link")


class UpstreamError(Exception):
    """The SIDOF API answered, but not with a usable payload."""


def parse_date(date_str: str) -> date:
    """Parse a ``DD-MM-YYYY`` date (``/`` separators are tolerated), rejecting impossible dates."""
    cleaned = date_str.strip().replace("/", "-")
    try:
        return datetime.strptime(cleaned, "%d-%m-%Y").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date {date_str!r}: expected format DD-MM-YYYY, e.g. 20-11-2026.") from exc


def format_api_date(value: date) -> str:
    """Format a date the way SIDOF expects it in URLs (``DD-MM-YYYY``)."""
    return value.strftime("%d-%m-%Y")


def to_citation_date(sidof_date: str | None) -> str | None:
    """Convert a SIDOF ``DD-MM-YYYY`` date to the ``DD/MM/YYYY`` form used in DOF links and citations."""
    if not sidof_date:
        return None
    try:
        return parse_date(sidof_date).strftime("%d/%m/%Y")
    except ValueError:
        return None


def note_url(public_base_url: str, code: int, citation_date: str | None) -> str:
    """Build the public dof.gob.mx link for a note."""
    url = f"{public_base_url}/nota_detalle.php?codigo={code}"
    return f"{url}&fecha={citation_date}" if citation_date else url


def _check_envelope(payload: Mapping[str, Any]) -> None:
    code = payload.get("messageCode")
    if code is not None and int(code) != 200:
        raise UpstreamError(f"SIDOF returned messageCode={code} ({payload.get('response')!r}).")


def _optional_str(value: Any) -> str | None:
    """Normalize SIDOF optional strings, which may be missing, empty, or the literal string ``"null"``."""
    if value is None:
        return None
    text = str(value).strip()
    return None if not text or text.lower() == "null" else text


def _optional_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _has_full_text(raw: Mapping[str, Any]) -> bool:
    """``existeHtml`` is "S" even for scanned, image-only notes; ``existeDoc`` reflects extractable text."""
    flag = _optional_str(raw.get("existeDoc")) or _optional_str(raw.get("existeHtml"))
    return flag == "S"


def _sort_key(raw: Mapping[str, Any]) -> tuple[float, int]:
    try:
        order = float(raw.get("orden", 0) or 0)
    except (TypeError, ValueError):
        order = 0.0
    return order, int(raw.get("codNota", 0) or 0)


def _parse_notes(raw_notes: Iterable[Mapping[str, Any]], edition: Edition, public_base_url: str) -> list[DofNote]:
    notes: list[DofNote] = []
    # Python's sort is stable, so section order as delivered by SIDOF is preserved within equal `orden`.
    for raw in sorted(raw_notes, key=_sort_key):
        code = _optional_int(raw.get("codNota"))
        if code is None:
            continue
        citation_date = to_citation_date(_optional_str(raw.get("fecha"))) or ""
        title = _optional_str(raw.get("titulo"))
        notes.append(
            DofNote(
                code=code,
                title=" ".join(title.split()) if title else None,
                edition=edition,
                section=_optional_str(raw.get("nombreCodOrgaUno")),
                section_code=_optional_str(raw.get("codOrgaUno")),
                organism=_optional_str(raw.get("codOrgaDos")),
                note_type=_optional_str(raw.get("tipoNota")),
                page=_optional_int(raw.get("pagina")),
                has_full_text=_has_full_text(raw),
                publication_date=citation_date,
                url=note_url(public_base_url, code, citation_date or None),
            )
        )
    return notes


def parse_edition(
    payload: Mapping[str, Any], requested: date, *, public_base_url: str, source: str
) -> DofEditionResult:
    """Flatten a SIDOF ``/notas/{DD-MM-YYYY}`` payload into a :class:`DofEditionResult`."""
    _check_envelope(payload)
    notes: list[DofNote] = []
    per_edition: dict[str, int] = {}
    for edition, key in EDITION_KEYS:
        raw_notes = payload.get(key) or []
        if not isinstance(raw_notes, list):
            raise UpstreamError(f"SIDOF field {key!r} is not a list.")
        parsed = _parse_notes(raw_notes, edition, public_base_url)
        if parsed:
            per_edition[edition] = len(parsed)
            notes.extend(parsed)
    return DofEditionResult(
        date=format_api_date(requested),
        published=bool(notes),
        total_notes=len(notes),
        notes_per_edition=per_edition,
        notes=notes,
        source=source,
    )


def extract_note_code(url: str) -> int:
    """Extract the DOF note code from a dof.gob.mx or SIDOF URL.

    Accepted forms include ``https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026``
    (any ``.php`` page carrying a numeric ``codigo``) and ``https://sidof.segob.gob.mx/dof/sidof/notas/nota/5804497``.
    The URL itself is never fetched: only the code is used, against the fixed SIDOF endpoint.
    """
    candidate = url.strip()
    if candidate.isdigit():
        return int(candidate)
    parts = urlsplit(candidate)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or host not in ALLOWED_URL_HOSTS:
        raise ValueError(
            f"Unsupported URL {url!r}: only dof.gob.mx note links (nota_detalle.php?codigo=...) "
            "or sidof.segob.gob.mx note URLs are accepted."
        )
    codes = parse_qs(parts.query).get("codigo", [])
    if codes and codes[0].strip().isdigit():
        return int(codes[0].strip())
    match = _SIDOF_NOTE_PATH.search(parts.path)
    if match:
        return int(match.group(1))
    raise ValueError(f"URL {url!r} does not identify a DOF note: expected a numeric 'codigo' parameter.")


def html_to_text(markup: str) -> str:
    """Convert DOF note HTML into clean plain text, one paragraph per line.

    Block elements become line breaks while inline formatting (``<b>``, ``<span>``...) is kept on the
    same line, so "Artículo <b>1o.</b>- ..." stays a single line. Table cells are joined with `` | ``.
    """
    if "<" not in markup and "&lt;" in markup:
        # SIDOF sometimes ships the document HTML-escaped inside the JSON string.
        markup = html.unescape(markup)
    soup = BeautifulSoup(markup, "html.parser")
    for tag in soup.find_all(_DROP_TAGS):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        if isinstance(tag, Tag):
            tag.insert_before("\n")
            tag.insert_after("\n")
    for cell in soup.find_all(_CELL_TAGS):
        if isinstance(cell, Tag):
            cell.insert_after(" | ")

    lines: list[str] = []
    for raw_line in soup.get_text().splitlines():
        line = " ".join(raw_line.split())  # also collapses &nbsp; (\xa0)
        line = line.strip(" |").strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def parse_note(
    payload: Mapping[str, Any], requested_code: int, *, public_base_url: str, max_chars: int
) -> DecreeTextResult:
    """Turn a SIDOF ``/notas/nota/{codigo}`` payload into a :class:`DecreeTextResult`."""
    _check_envelope(payload)
    note = payload.get("Nota")
    if not isinstance(note, Mapping):
        raise UpstreamError(f"DOF note {requested_code} was not found.")
    code = _optional_int(note.get("codNota")) or requested_code
    citation_date = to_citation_date(_optional_str(note.get("fecha")))
    public_url = note_url(public_base_url, code, citation_date)
    markup = str(note.get("cadenaContenido") or "")
    if not markup.strip():
        reason = (
            "its text is too large for the DOF text service"
            if payload.get("tamanioExcesivo") is True
            else "it is published only as a scanned image/PDF"
        )
        raise UpstreamError(f"DOF note {code} has no extractable text ({reason}); consult it at {public_url}")

    title = _optional_str(note.get("titulo"))
    text = html_to_text(markup)
    return DecreeTextResult(
        code=code,
        title=" ".join(title.split()) if title else None,
        publication_date=citation_date,
        url=public_url,
        text=text[:max_chars],
        total_chars=len(text),
        truncated=len(text) > max_chars,
    )
