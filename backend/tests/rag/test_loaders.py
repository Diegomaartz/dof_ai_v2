from __future__ import annotations

import pytest

from rag.loaders import (
    UnsupportedDocumentError,
    decode_text,
    load_document,
    normalize_text,
    strip_page_furniture,
)

HEADER = [
    "LEY FEDERAL DEL TRABAJO",
    "CÁMARA DE DIPUTADOS DEL H. CONGRESO DE LA UNIÓN",
    "Secretaría General",
    "Última Reforma DOF 14-05-2026",
]


def page(n: int, total: int, body: list[str]) -> str:
    return "\n".join([*HEADER, f"{n} de {total}", *body])


def test_strip_page_furniture_removes_repeated_headers_and_page_numbers() -> None:
    pages = [
        page(1, 3, ["LEY FEDERAL DEL TRABAJO", "TITULO PRIMERO", "Artículo 1o.- Texto que continúa en la"]),
        page(2, 3, ["siguiente página.", "Artículo reformado DOF 30-11-2012", "Artículo 2o.- Otro."]),
        page(3, 3, ["Artículo 3o.- Último.", "Artículo reformado DOF 30-11-2012"]),
    ]
    lines = strip_page_furniture(pages)
    assert "CÁMARA DE DIPUTADOS DEL H. CONGRESO DE LA UNIÓN" not in lines
    assert not any(ln.endswith("de 3") for ln in lines)
    # the article spanning a page break is contiguous again
    i = lines.index("Artículo 1o.- Texto que continúa en la")
    assert lines[i + 1] == "siguiente página."
    # reform notes are kept even when they repeat at page edges
    assert lines.count("Artículo reformado DOF 30-11-2012") == 2


def test_strip_page_furniture_keeps_short_documents_intact() -> None:
    assert strip_page_furniture(["A\nB", "A\nC"]) == ["A", "B", "A", "C"]


def test_normalize_text_unifies_whitespace_and_unicode() -> None:
    decomposed = "Articulo".replace("i", "í", 1)  # "Artículo" with combining accent
    raw = f"{decomposed} 1o.-  Texto\r\nsoft­hyphen  \r\n"
    assert normalize_text(raw) == "Artículo 1o.- Texto\nsofthyphen\n"


def test_decode_text_utf8_bom_and_cp1252_fallback() -> None:
    assert decode_text("﻿Artículo".encode()) == "Artículo"
    assert decode_text("Artículo".encode("cp1252")) == "Artículo"


def test_load_document_txt() -> None:
    doc = load_document("Artículo 1.- Uno.\n\n\nArtículo 2.- Dos.\n".encode(), "ley.TXT")
    assert doc.text == "Artículo 1.- Uno.\nArtículo 2.- Dos."
    assert doc.first_page.startswith("Artículo 1.-")


def test_load_document_rejects_unknown_extension() -> None:
    with pytest.raises(UnsupportedDocumentError):
        load_document(b"x", "ley.docx")


def test_load_document_pdf_roundtrip() -> None:
    pdfium = pytest.importorskip("pypdfium2")
    raw = pdfium.raw
    pdf = pdfium.PdfDocument.new()
    font = raw.FPDFText_LoadStandardFont(pdf.raw, b"Helvetica")
    page = pdf.new_page(612, 792)
    obj = raw.FPDFPageObj_NewTextObj(pdf.raw, b"Helvetica", 12.0)
    text = "Articulo 1.- Texto de prueba.\x00".encode("utf-16-le")
    import ctypes

    buf = ctypes.create_string_buffer(text)
    raw.FPDFText_SetText(obj, ctypes.cast(buf, ctypes.POINTER(raw.FPDF_WCHAR)))
    raw.FPDFPageObj_Transform(obj, 1, 0, 0, 1, 72, 700)
    raw.FPDFPage_InsertObject(page.raw, obj)
    raw.FPDFPage_GenerateContent(page.raw)
    raw.FPDFFont_Close(font)
    import io

    out = io.BytesIO()
    pdf.save(out)
    doc = load_document(out.getvalue(), "ley.pdf")
    assert "Articulo 1.- Texto de prueba." in doc.text
