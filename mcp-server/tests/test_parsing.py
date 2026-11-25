"""Unit tests for the pure SIDOF/DOF parsing helpers."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from dof_mcp.parsing import (
    UpstreamError,
    extract_note_code,
    html_to_text,
    parse_date,
    parse_edition,
    parse_note,
)

PUBLIC = "https://dof.gob.mx"
DAY = date(2026, 11, 20)


class TestParseDate:
    def test_accepts_dd_mm_yyyy(self) -> None:
        assert parse_date("20-11-2026") == DAY

    def test_tolerates_slashes_and_whitespace(self) -> None:
        assert parse_date(" 20/11/2026 ") == DAY

    @pytest.mark.parametrize("bad", ["2026-11-20", "31-02-2026", "20-13-2026", "hoy", ""])
    def test_rejects_invalid(self, bad: str) -> None:
        with pytest.raises(ValueError, match="DD-MM-YYYY"):
            parse_date(bad)


class TestExtractNoteCode:
    @pytest.mark.parametrize(
        "url",
        [
            "https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026",
            "http://www.dof.gob.mx/nota_detalle.php?fecha=20/11/2026&codigo=5804497",
            "https://www.dof.gob.mx/nota_detalle_popup.php?codigo=5804497",
            "https://sidof.segob.gob.mx/dof/sidof/notas/nota/5804497",
            "5804497",
        ],
    )
    def test_accepts_dof_links(self, url: str) -> None:
        assert extract_note_code(url) == 5804497

    @pytest.mark.parametrize(
        "url",
        [
            "https://evil.example.com/nota_detalle.php?codigo=5804497",
            "https://dof.gob.mx.evil.com/nota_detalle.php?codigo=5804497",
            "file:///etc/passwd",
            "ftp://dof.gob.mx/nota_detalle.php?codigo=1",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    def test_rejects_foreign_hosts(self, url: str) -> None:
        with pytest.raises(ValueError, match="Unsupported URL"):
            extract_note_code(url)

    @pytest.mark.parametrize("url", ["https://dof.gob.mx/index.php", "https://dof.gob.mx/nota_detalle.php?codigo=abc"])
    def test_rejects_links_without_numeric_code(self, url: str) -> None:
        with pytest.raises(ValueError, match="does not identify"):
            extract_note_code(url)


class TestHtmlToText:
    def test_blocks_become_lines_and_inline_tags_stay_inline(self) -> None:
        text = html_to_text("<div class='Texto'><b>Artículo 1o.-</b>&nbsp;El presente   Reglamento.</div><p>Otro</p>")
        assert text.splitlines() == ["Artículo 1o.- El presente Reglamento.", "Otro"]

    def test_br_splits_lines(self) -> None:
        assert html_to_text("<div>CAPÍTULO I<br>Disposiciones Generales</div>") == (
            "CAPÍTULO I\nDisposiciones Generales"
        )

    def test_drops_head_style_and_script(self) -> None:
        markup = "<html><head><title>T</title><style>.a{}</style></head><body>Texto<script>x()</script></body></html>"
        assert html_to_text(markup) == "Texto"

    def test_tables_are_pipe_separated(self) -> None:
        assert html_to_text("<table><tr><td>A</td><td>B</td></tr></table>") == "A | B"

    def test_unescapes_escaped_documents(self) -> None:
        assert html_to_text("&lt;div&gt;Uno&lt;/div&gt;&lt;div&gt;Dos&lt;/div&gt;") == "Uno\nDos"


class TestParseEdition:
    def test_flattens_editions_in_order(self, edition_payload: dict[str, Any]) -> None:
        result = parse_edition(edition_payload, DAY, public_base_url=PUBLIC, source="src")
        assert result.date == "20-11-2026"
        assert result.published is True
        assert result.total_notes == 6
        assert result.notes_per_edition == {"matutina": 5, "vespertina": 1}
        assert [n.code for n in result.notes] == [5804497, 5804498, 5804520, 5804530, 5804540, 5804601]
        assert [n.edition for n in result.notes][-1] == "vespertina"

    def test_note_fields(self, edition_payload: dict[str, Any]) -> None:
        notes = {n.code: n for n in parse_edition(edition_payload, DAY, public_base_url=PUBLIC, source="s").notes}
        decree = notes[5804497]
        assert decree.title == "DECRETO por el que se reforman diversas disposiciones del Reglamento de Ejemplo."
        assert decree.section == "PODER EJECUTIVO"
        assert decree.section_code == "PE"
        assert decree.note_type is None  # SIDOF sends the string "null"
        assert decree.page == 2
        assert decree.has_full_text is True
        assert decree.publication_date == "20/11/2026"
        assert decree.url == "https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026"

    def test_missing_optional_fields(self, edition_payload: dict[str, Any]) -> None:
        notes = {n.code: n for n in parse_edition(edition_payload, DAY, public_base_url=PUBLIC, source="s").notes}
        assert notes[5804498].title is None
        assert notes[5804498].has_full_text is False  # existeHtml "S" but existeDoc "N": scanned only
        assert notes[5804497].organism == "SECRETARIA DE GOBERNACION"
        aviso = notes[5804540]
        assert aviso.note_type == "AVISO"
        assert aviso.organism is None
        assert aviso.page is None

    def test_day_without_publication(self) -> None:
        payload = {"messageCode": 200, "response": "OK", "NotasMatutinas": [], "NotasVespertinas": []}
        result = parse_edition(payload, DAY, public_base_url=PUBLIC, source="s")
        assert result.published is False
        assert result.total_notes == 0
        assert result.notes == []

    def test_error_envelope(self) -> None:
        with pytest.raises(UpstreamError, match="messageCode=500"):
            parse_edition({"messageCode": 500, "response": "ERROR"}, DAY, public_base_url=PUBLIC, source="s")

    def test_malformed_group(self) -> None:
        with pytest.raises(UpstreamError, match="not a list"):
            parse_edition({"NotasMatutinas": {"a": 1}}, DAY, public_base_url=PUBLIC, source="s")


class TestParseNote:
    def test_extracts_clean_text(self, note_payload: dict[str, Any]) -> None:
        result = parse_note(note_payload, 5804497, public_base_url=PUBLIC, max_chars=100_000)
        assert result.code == 5804497
        assert result.title == "DECRETO por el que se reforman diversas disposiciones del Reglamento de Ejemplo."
        assert result.publication_date == "20/11/2026"
        assert result.url == "https://dof.gob.mx/nota_detalle.php?codigo=5804497&fecha=20/11/2026"
        lines = result.text.splitlines()
        assert lines[0] == "SECRETARIA DE GOBERNACION"
        assert "Artículo 1o.- El presente Reglamento es de orden público y de observancia general." in lines
        assert "I. Secretaría: la Secretaría de Gobernación, y" in lines
        assert "Derecho | $1,000.00" in lines
        assert "TRANSITORIOS" in lines
        assert "trackView" not in result.text
        assert ".Texto" not in result.text
        assert result.truncated is False
        assert result.total_chars == len(result.text)

    def test_truncates_long_text(self, note_payload: dict[str, Any]) -> None:
        result = parse_note(note_payload, 5804497, public_base_url=PUBLIC, max_chars=50)
        assert len(result.text) == 50
        assert result.truncated is True
        assert result.total_chars > 50

    def test_missing_title_is_not_guessed(self, note_payload: dict[str, Any]) -> None:
        # The first heading is the issuing body, not the title: never present it as one.
        del note_payload["Nota"]["titulo"]
        result = parse_note(note_payload, 5804497, public_base_url=PUBLIC, max_chars=100_000)
        assert result.title is None

    def test_scanned_note_points_to_public_link(self) -> None:
        # Shape observed live for an image-only note: no cadenaContenido, tamanioExcesivo false.
        payload = {"messageCode": 200, "tamanioExcesivo": False, "Nota": {"codNota": 5804496, "fecha": "20-11-2026"}}
        with pytest.raises(UpstreamError, match="scanned image/PDF") as info:
            parse_note(payload, 5804496, public_base_url=PUBLIC, max_chars=10)
        assert "https://dof.gob.mx/nota_detalle.php?codigo=5804496&fecha=20/11/2026" in str(info.value)

    def test_oversized_note(self) -> None:
        payload = {"messageCode": 200, "tamanioExcesivo": True, "Nota": {"codNota": 9, "cadenaContenido": ""}}
        with pytest.raises(UpstreamError, match="too large"):
            parse_note(payload, 9, public_base_url=PUBLIC, max_chars=10)

    def test_missing_note(self) -> None:
        with pytest.raises(UpstreamError, match="not found"):
            parse_note({"messageCode": 200, "response": "OK"}, 7, public_base_url=PUBLIC, max_chars=10)
