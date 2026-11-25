"""Text extraction for legal documents (PDF/TXT) and removal of page furniture.

PDFs published by the Cámara de Diputados repeat a header block on every page
("LEY FEDERAL DEL TRABAJO", "CÁMARA DE DIPUTADOS...", "Última Reforma DOF ...",
"12 de 457"). Left in place, those lines would be glued into whatever article
spans the page break, so they are detected statistically and removed.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

SUPPORTED_EXTENSIONS = frozenset({".pdf", ".txt"})

_PAGE_NUMBER_RE = re.compile(r"^\s*(?:p[áa]gina\s+)?\d{1,4}\s+de\s+\d{1,4}\s*$", re.IGNORECASE)
_MULTISPACE_RE = re.compile(r"[ \t  -​ ]+")
_REFORM_NOTE_RE = re.compile(r"\b(?:reformad|adicionad|derogad|recorrid)[oa]s?\b.*\bDOF\b", re.IGNORECASE)
_FURNITURE_WINDOW = 8
_FURNITURE_MIN_SHARE = 0.5


class UnsupportedDocumentError(ValueError):
    """Raised for file types the ingestion pipeline does not handle."""


@dataclass(frozen=True)
class LoadedDocument:
    """Raw page texts plus the page-furniture-free text ready for chunking."""

    pages: list[str]
    text: str

    @property
    def first_page(self) -> str:
        return self.pages[0] if self.pages else ""


def load_document(data: bytes, filename: str) -> LoadedDocument:
    """Extract text from a PDF or TXT payload and strip repeated page headers/footers."""
    ext = PurePosixPath(filename.lower()).suffix
    if ext == ".pdf":
        pages = extract_pdf_pages(data)
    elif ext == ".txt":
        pages = [decode_text(data)]
    else:
        raise UnsupportedDocumentError(f"Unsupported file type {ext!r}; expected one of {sorted(SUPPORTED_EXTENSIONS)}")
    pages = [normalize_text(p) for p in pages]
    return LoadedDocument(pages=pages, text="\n".join(strip_page_furniture(pages)))


def extract_pdf_pages(data: bytes) -> list[str]:
    """Extract per-page text with PDFium (~15x faster than pure-Python parsers on 400+ page laws)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        pages: list[str] = []
        for page in pdf:
            textpage = page.get_textpage()
            try:
                pages.append(textpage.get_text_range())
            finally:
                textpage.close()
                page.close()
        return pages
    finally:
        pdf.close()


def decode_text(data: bytes) -> str:
    """Decode TXT uploads: UTF-8 (with or without BOM), falling back to Windows-1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def normalize_text(text: str) -> str:
    """NFC-normalize, unify line endings, collapse inner whitespace and strip each line."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("­", "").replace("﻿", "")
    return "\n".join(_MULTISPACE_RE.sub(" ", line).strip() for line in text.split("\n"))


def strip_page_furniture(pages: list[str]) -> list[str]:
    """Remove page numbers and header/footer lines repeated across most pages.

    A line is header furniture when it appears within the first
    ``_FURNITURE_WINDOW`` non-empty lines of at least half of the pages (footer
    furniture likewise for the last lines). Only those edge positions are
    cleaned, so the same text inside the body (e.g. the law name before
    ``TÍTULO PRIMERO``) is preserved. DOF reform notes are never furniture.
    Empty lines are dropped.
    """
    page_lines = [[ln for ln in page.split("\n") if ln.strip()] for page in pages]
    header: set[str] = set()
    footer: set[str] = set()
    if len(page_lines) >= 3:
        threshold = max(2, int(len(page_lines) * _FURNITURE_MIN_SHARE))
        header = _frequent((lines[:_FURNITURE_WINDOW] for lines in page_lines), threshold)
        footer = _frequent((lines[-_FURNITURE_WINDOW:] for lines in page_lines), threshold)

    cleaned: list[str] = []
    for lines in page_lines:
        tail_start = len(lines) - _FURNITURE_WINDOW
        for i, line in enumerate(lines):
            if _PAGE_NUMBER_RE.match(line):
                continue
            if (i < _FURNITURE_WINDOW and line in header) or (i >= tail_start and line in footer):
                continue
            cleaned.append(line)
    return cleaned


def _frequent(windows: Iterable[list[str]], threshold: int) -> set[str]:
    counts: Counter[str] = Counter()
    for window in windows:
        counts.update(set(window))
    return {ln for ln, n in counts.items() if n >= threshold and not _REFORM_NOTE_RE.search(ln)}
