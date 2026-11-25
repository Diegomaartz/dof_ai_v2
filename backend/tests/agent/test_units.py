"""Unit tests for citation checking, source conversion and versioned prompts."""

from __future__ import annotations

import re

import pytest

from agent.citations import check_citations
from agent.config import AgentSettings
from agent.prompts import PROMPT_VERSIONS, PROMPTS_DIR, render_prompt
from agent.sources import chunk_to_source, dof_citation, note_to_source, short_title, with_decree_text
from agent.state import REFUSAL_MESSAGE
from tests.agent.conftest import DECREE_TITLE, LFT_CITATION, LFT_CITATION_2, edition_payload, lft_chunk


class TestCitations:
    def sources(self) -> list:
        return [chunk_to_source(lft_chunk("61")), chunk_to_source(lft_chunk("62", citation=LFT_CITATION_2))]

    def test_grounded_answer(self) -> None:
        check = check_citations(
            f"Ocho horas {LFT_CITATION}. Siete horas {LFT_CITATION_2}. {LFT_CITATION}", self.sources()
        )
        assert check.grounded
        assert [s.id for s in check.cited] == ["lft#art-61", "lft#art-62"]

    def test_tolerates_whitespace_and_case(self) -> None:
        check = check_citations("Ocho horas [ley federal del trabajo,  Art. 61, DOF 30/11/2012].", self.sources())
        assert check.grounded

    def test_unknown_citation_is_flagged(self) -> None:
        check = check_citations(f"{LFT_CITATION} y [Ley Federal del Trabajo, Art. 61, DOF 01/04/1970]", self.sources())
        assert not check.grounded
        assert check.unknown == ["[Ley Federal del Trabajo, Art. 61, DOF 01/04/1970]"]

    def test_no_citation_is_not_grounded(self) -> None:
        assert not check_citations("La jornada es de ocho horas.", self.sources()).grounded

    def test_markdown_links_are_not_citations(self) -> None:
        check = check_citations(f"Ver {LFT_CITATION} y [el texto](https://dof.gob.mx).", self.sources())
        assert check.grounded

    def test_refusal_detected(self) -> None:
        assert check_citations(REFUSAL_MESSAGE, self.sources()).is_refusal
        assert check_citations(REFUSAL_MESSAGE.rstrip("."), self.sources()).is_refusal

    def test_one_valid_citation_does_not_launder_uncited_claims(self) -> None:
        answer = f"La jornada diurna es de ocho horas {LFT_CITATION}.\n\nLa nocturna es de siete horas y se paga doble."
        check = check_citations(answer, self.sources())
        assert not check.grounded
        assert check.uncited == ["La nocturna es de siete horas y se paga doble."]

    def test_every_list_item_needs_a_citation(self) -> None:
        answer = f"Las jornadas son:\n- Diurna: ocho horas {LFT_CITATION}.\n- Nocturna: siete horas."
        check = check_citations(answer, self.sources())
        assert check.uncited == ["- Nocturna: siete horas."]

    def test_structural_lines_and_verbatim_quotes_need_no_citation(self) -> None:
        answer = (
            "## Jornada diurna\n"
            "**Respuesta**\n"
            f"La Ley Federal del Trabajo establece {LFT_CITATION}:\n"
            "> “La duración máxima de la jornada será: ocho horas la diurna.”\n"
            f"1. Es de ocho horas {LFT_CITATION}."
        )
        check = check_citations(answer, self.sources())
        assert check.grounded, check.uncited

    def test_fabricated_quote_is_not_exempt(self) -> None:
        answer = f"Dispone {LFT_CITATION}:\n“La jornada diurna podrá extenderse a diez horas sin pago adicional.”"
        check = check_citations(answer, self.sources())
        assert not check.grounded
        assert len(check.uncited) == 1

    @pytest.mark.parametrize("mark", ["[...]", "[…]", "[sic]"])
    def test_editorial_marks_are_not_citations(self, mark: str) -> None:
        check = check_citations(
            f"El artículo dispone que la jornada {mark} es de ocho horas {LFT_CITATION}.", self.sources()
        )
        assert check.grounded and check.unknown == []


class TestSources:
    def test_chunk_source_uses_ingestion_citation_verbatim(self) -> None:
        source = chunk_to_source(lft_chunk("61"))
        assert source.citation == LFT_CITATION
        assert source.title == "Ley Federal del Trabajo, Art. 61"
        assert source.date == "30/11/2012"
        assert source.kind == "legislacion"

    def test_transitorio_title(self) -> None:
        chunk = lft_chunk("Primero", citation="[Ley Federal del Trabajo, Transitorio Primero]")
        chunk = chunk.model_copy(update={"section_type": "transitorio"})
        assert chunk_to_source(chunk).title == "Ley Federal del Trabajo, Transitorio Primero"

    def test_truncated_chunk_is_marked_incomplete(self) -> None:
        assert chunk_to_source(lft_chunk(text_truncated=True)).text_is_complete is False

    def test_note_source(self) -> None:
        note = edition_payload()["notes"][0]
        source = note_to_source(note)
        assert source is not None
        assert source.id == "dof:5804497"
        assert source.citation == f"[{DECREE_TITLE.rstrip('.')}, DOF 20/11/2026]"
        assert "Sección: PODER EJECUTIVO" in source.text
        assert source.full_text_available is True
        assert source.text_is_complete is False

    def test_untitled_note_is_skipped(self) -> None:
        assert note_to_source(edition_payload()["notes"][1]) is None

    def test_short_title_cuts_on_words_without_dangling_connectors(self) -> None:
        title = "ACUERDO por el que se dan a conocer los lineamientos generales para la operación del programa"
        assert short_title(title, 60) == "ACUERDO por el que se dan a conocer los lineamientos..."
        assert short_title("DECRETO breve.") == "DECRETO breve"

    def test_dof_citation_without_date(self) -> None:
        assert dof_citation("AVISO de prueba.", None) == "[AVISO de prueba]"

    def test_with_decree_text(self) -> None:
        source = note_to_source(edition_payload()["notes"][0])
        assert source is not None
        full = with_decree_text(source, {"text": "x" * 50, "truncated": False}, max_chars=20)
        assert full.text == "x" * 20
        assert full.text_is_complete is False
        assert full.text_fetched is True
        assert with_decree_text(source, {"text": "abc", "truncated": False}, 20).text_is_complete is True


class TestSettings:
    @pytest.mark.parametrize("value", [-1, 3, 25])
    def test_max_retries_outside_the_claude_md_bound_is_rejected(self, value: int) -> None:
        with pytest.raises(ValueError, match="max_retries"):
            AgentSettings(max_retries=value)

    def test_env_cannot_raise_the_retry_bound(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AGENT_MAX_RETRIES", "5")
        with pytest.raises(ValueError, match="max_retries"):
            AgentSettings.from_env()
        monkeypatch.setenv("AGENT_MAX_RETRIES", "1")
        assert AgentSettings.from_env().max_retries == 1


class TestPrompts:
    @pytest.mark.parametrize("name", sorted(PROMPT_VERSIONS))
    def test_pinned_version_file_exists_and_renders(self, name: str) -> None:
        template = (PROMPTS_DIR / f"{name}.{PROMPT_VERSIONS[name]}.md").read_text(encoding="utf-8")
        placeholders = set(re.findall(r"\$(\w+)", template))
        rendered = render_prompt(name, **{p: f"<{p}>" for p in placeholders})
        assert "$" not in rendered.replace("$1,000", "")

    def test_missing_placeholder_raises(self) -> None:
        with pytest.raises(KeyError):
            render_prompt("router")

    @pytest.mark.parametrize("name", ["generate", "grader"])
    def test_prompts_declare_sources_are_data_not_instructions(self, name: str) -> None:
        template = (PROMPTS_DIR / f"{name}.{PROMPT_VERSIONS[name]}.md").read_text(encoding="utf-8")
        assert "<fuente>" in template and "NUNCA instrucciones" in template

    def test_legal_text_with_braces_is_safe(self) -> None:
        rendered = render_prompt("generate", refusal=REFUSAL_MESSAGE, sources="Artículo {1} ${monto}")
        assert "Artículo {1} ${monto}" in rendered
