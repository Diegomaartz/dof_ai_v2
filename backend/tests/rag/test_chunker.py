from __future__ import annotations

from datetime import date

import pytest

from rag.chunker import (
    ChunkerConfig,
    LegalChunker,
    _longest_non_decreasing,
    parse_law_header,
    parse_text_date,
    slugify,
)
from rag.models import LawMetadata, LegalChunk, SectionType
from rag.service import DocumentSource, IncompleteLawMetadataError, build_chunks


def chunk(text: str, law: LawMetadata, **cfg: int) -> list[LegalChunk]:
    return LegalChunker(ChunkerConfig(**cfg)).chunk(text, law)


def by_label(chunks: list[LegalChunk], label: str, section: SectionType = SectionType.ARTICULO) -> LegalChunk:
    matches = [c for c in chunks if c.article_label == label and c.section_type is section]
    assert len(matches) == 1, f"expected one {section} {label!r}, got {[c.id for c in matches]}"
    return matches[0]


# --------------------------------------------------------------------------- real law excerpt (LFT)


@pytest.fixture
def lft_chunks(lft_excerpt_bytes: bytes) -> list[LegalChunk]:
    return build_chunks(DocumentSource(filename="LFT.txt", data=lft_excerpt_bytes))


def test_lft_header_metadata(lft_chunks: list[LegalChunk]) -> None:
    law = lft_chunks[0].law
    assert law.law_name == "LEY FEDERAL DEL TRABAJO"
    assert law.law_slug == "lft"
    assert law.publication_date == date(1970, 4, 1)
    assert law.last_reform_date == date(2026, 5, 14)


def test_lft_article_boundaries_are_exact(lft_chunks: list[LegalChunk]) -> None:
    labels = [c.article_label for c in lft_chunks if c.section_type is SectionType.ARTICULO]
    assert labels == [
        "1o", "2o", "3o", "3o Bis", "3o Ter",
        "15", "15-A", "15-B", "15-C", "15-D", "16", "17", "18", "19",
        "20", "21", "22", "22 Bis", "23",
        "164", "165", "166", "167", "168", "169",
        "353-N", "353-Ñ", "353-O",
        "1010",
    ]  # fmt: skip
    for c in lft_chunks:
        assert c.part_count == 1, "no article in the excerpt should be split"


def test_lft_article_text_is_intact_and_excludes_neighbours(lft_chunks: list[LegalChunk]) -> None:
    art2 = by_label(lft_chunks, "2o")
    assert art2.text.startswith("Artículo 2o.- Las normas del trabajo tienden a conseguir el equilibrio")
    assert art2.text.rstrip().endswith("Artículo reformado DOF 30-11-2012")
    assert "Artículo 3o.-" not in art2.text
    # in-text references must not open a new chunk
    art1 = by_label(lft_chunks, "1o")
    assert "artículo 123, Apartado A" in art1.text


def test_lft_hierarchy_path(lft_chunks: list[LegalChunk]) -> None:
    assert by_label(lft_chunks, "1o").hierarchy == {"titulo": "TITULO PRIMERO Principios Generales"}
    art20 = by_label(lft_chunks, "20")
    assert art20.hierarchy == {
        "titulo": "TITULO SEGUNDO Relaciones Individuales de Trabajo",
        "capitulo": "CAPITULO I Disposiciones generales",
    }
    # a new TÍTULO resets the CAPÍTULO
    assert "capitulo" not in by_label(lft_chunks, "164").hierarchy


def test_heading_title_skips_reform_notes(lft_chunks: list[LegalChunk]) -> None:
    titulo = by_label(lft_chunks, "169").hierarchy["titulo"]
    assert titulo == "TITULO QUINTO Trabajo de las Mujeres"


def test_lft_reform_dates_and_citation(lft_chunks: list[LegalChunk]) -> None:
    art2 = by_label(lft_chunks, "2o")
    assert art2.reform_dates == [date(2012, 11, 30), date(2026, 1, 15)]
    assert art2.citation == "[LEY FEDERAL DEL TRABAJO, Art. 2o, DOF 15/01/2026]"
    # unreformed article falls back to the law's publication date
    assert by_label(lft_chunks, "17").citation == "[LEY FEDERAL DEL TRABAJO, Art. 17, DOF 01/04/1970]"


def test_lft_repealed_articles_are_flagged(lft_chunks: list[LegalChunk]) -> None:
    repealed = {c.article_label for c in lft_chunks if c.is_repealed}
    assert repealed == {"15-A", "15-B", "15-C", "15-D", "169"}


def test_lft_transitorios_blocks_and_decrees(lft_chunks: list[LegalChunk]) -> None:
    trans = [c for c in lft_chunks if c.section_type is SectionType.TRANSITORIO]
    original = [c for c in trans if c.transitorio_block == 0]
    assert [c.article_label for c in original][:3] == ["1o", "2o", "3o"]
    assert all(c.decree_date == date(1970, 4, 1) for c in original)

    unico = by_label(trans, "Único", SectionType.TRANSITORIO)
    assert unico.decree_date == date(1998, 1, 23)
    assert unico.decree_title is not None and unico.decree_title.startswith("DECRETO por el que se reforman diversos")
    assert "Rúbricas" not in unico.text, "signature block must not leak into the transitorio"

    reform_2006 = [c for c in trans if c.transitorio_block == 2]
    assert [c.article_label for c in reform_2006] == ["Primero", "Segundo"]
    assert reform_2006[1].citation == "[LEY FEDERAL DEL TRABAJO, Transitorio Segundo, DOF 17/01/2006]"
    assert reform_2006[1].text.endswith("tendrá vigencia a partir del año 2007.")


def test_decree_bodies_are_not_indexed(lft_chunks: list[LegalChunk]) -> None:
    assert not any("Se reforma el artículo 74 de la Ley Federal del Trabajo, para quedar" in c.text for c in lft_chunks)


def test_ids_are_unique_ascii_and_prefixed(lft_chunks: list[LegalChunk]) -> None:
    ids = [c.id for c in lft_chunks]
    assert len(ids) == len(set(ids))
    assert all(i.isascii() and i.startswith("lft#") for i in ids)
    assert "lft#art-353-nn" in ids and "lft#art-353-n" in ids
    assert "lft#tr002-segundo" in ids


def test_chunking_is_deterministic(lft_excerpt_bytes: bytes) -> None:
    a = build_chunks(DocumentSource(filename="LFT.txt", data=lft_excerpt_bytes))
    b = build_chunks(DocumentSource(filename="LFT.txt", data=lft_excerpt_bytes))
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


# --------------------------------------------------------------------------- synthetic edge cases

EDGE_LAW = """\
LEY DE PRUEBA
LIBRO PRIMERO
Disposiciones Sustantivas
TÍTULO PRIMERO De las Personas
Capítulo Único
Artículo 1.- Las normas de esta Ley se aplican conforme al
Artículo 5o. de esta Ley y demás disposiciones aplicables.
Artículo 2.- Para efectos del presente ordenamiento, se transcribe:
"Artículo 900.- Texto citado de otra ley."
Artículo 2 Bis.- Disposición adicionada.
Artículo 3.- Se considera:
I. Primera fracción;
II. Segunda fracción.
SECCIÓN PRIMERA
De los Plazos
Artículo 4.- Los plazos se computan en días hábiles.
LIBRO SEGUNDO
Disposiciones Adjetivas
Artículo 5.- Disposición del libro segundo.
Artículo 6o.- (Se deroga).
TRANSITORIOS
PRIMERO.- La presente Ley entrará en vigor al día siguiente.
Décimo Primero.- Se derogan las disposiciones que se opongan.
"""


def test_wrapped_reference_with_lowercase_continuation_is_not_a_heading(law: LawMetadata) -> None:
    chunks = chunk(EDGE_LAW, law)
    art1 = by_label(chunks, "1")
    assert "Artículo 5o. de esta Ley" in art1.text
    assert not any(c.article_label == "5o" for c in chunks)


def test_out_of_sequence_quoted_article_is_rejected(law: LawMetadata) -> None:
    chunks = chunk(EDGE_LAW, law)
    assert "900" not in {c.article_label for c in chunks}
    assert '"Artículo 900.- Texto citado de otra ley."' in by_label(chunks, "2").text


def test_quoted_article_without_quotes_is_rejected_by_sequence() -> None:
    text = "Artículo 1.- Uno.\nArtículo 900.- Cita sin comillas.\nArtículo 2.- Dos.\nArtículo 3.- Tres.\n"
    chunks = LegalChunker().chunk(text, LawMetadata(law_name="L", law_slug="l"))
    assert [c.article_label for c in chunks] == ["1", "2", "3"]
    assert "Artículo 900.- Cita sin comillas." in chunks[0].text


def test_hierarchy_levels_reset_and_same_line_titles(law: LawMetadata) -> None:
    chunks = chunk(EDGE_LAW, law)
    assert by_label(chunks, "1").hierarchy == {
        "libro": "LIBRO PRIMERO Disposiciones Sustantivas",
        "titulo": "TÍTULO PRIMERO De las Personas",
        "capitulo": "Capítulo Único",
    }
    assert by_label(chunks, "4").hierarchy["seccion"] == "SECCIÓN PRIMERA De los Plazos"
    assert by_label(chunks, "5").hierarchy == {"libro": "LIBRO SEGUNDO Disposiciones Adjetivas"}
    assert by_label(chunks, "3").text.endswith("II. Segunda fracción.")


def test_compound_ordinal_transitorios(law: LawMetadata) -> None:
    trans = [c for c in chunk(EDGE_LAW, law) if c.section_type is SectionType.TRANSITORIO]
    assert [c.article_label for c in trans] == ["Primero", "Décimo Primero"]
    assert trans[0].decree_date == date(2000, 1, 1)
    assert trans[1].id == "lp#tr000-decimo-primero"


REFORM_APPENDIX_LAW = """\
Artículo 1.- Disposición única.
TRANSITORIOS
PRIMERO.- La presente Ley entrará en vigor al día siguiente.
ARTÍCULOS TRANSITORIOS DE DECRETOS DE REFORMA
DECRETO por el que se reforma el artículo 1 de la Ley de Prueba.
Publicado en el Diario Oficial de la Federación el 10 de marzo de 2010
ARTÍCULO ÚNICO.- Se reforma el artículo 1.
TRANSITORIO
ÚNICO.- El presente Decreto entrará en vigor en 2010.
México, D.F., a 1 de febrero de 2010.- Rúbricas.
DECRETO Número 45 que reforma la Ley de Prueba.
ARTÍCULO ÚNICO.- Se reforma el artículo 1.
TRANSITORIO
ÚNICO.- El presente Decreto entrará en vigor sin fecha conocida.
México, D.F., a 1 de enero de 2011.- Rúbricas.
TRANSITORIOS
PRIMERO.- Bloque sin encabezado de decreto.
"""


def transitorios(text: str, law: LawMetadata) -> list[LegalChunk]:
    return [c for c in chunk(text, law) if c.section_type is SectionType.TRANSITORIO]


def test_original_and_dated_reform_transitorios(law: LawMetadata) -> None:
    original, reform_2010, *_ = transitorios(REFORM_APPENDIX_LAW, law)
    assert original.citation == "[LEY DE PRUEBA, Transitorio Primero, DOF 01/01/2000]"
    assert reform_2010.decree_title == "DECRETO por el que se reforma el artículo 1 de la Ley de Prueba."
    assert reform_2010.citation == "[LEY DE PRUEBA, Transitorio Único, DOF 10/03/2010]"


def test_decree_without_publication_line_never_borrows_a_date(law: LawMetadata) -> None:
    undated = transitorios(REFORM_APPENDIX_LAW, law)[2]
    assert undated.transitorio_block == 2
    # "DECRETO Número ..." is recognised as a new decree, and its body does not leak into the title.
    assert undated.decree_title == "DECRETO Número 45 que reforma la Ley de Prueba."
    assert undated.decree_date is None
    assert undated.citation_date is None  # not the law's 2000 publication nor the 2010 decree
    assert undated.citation == "[LEY DE PRUEBA, Transitorio Único]"


def test_transitorios_block_without_decree_heading_does_not_inherit_previous_decree(law: LawMetadata) -> None:
    orphan = transitorios(REFORM_APPENDIX_LAW, law)[3]
    assert orphan.transitorio_block == 3 and orphan.article_label == "Primero"
    assert orphan.decree_title is None and orphan.decree_date is None
    assert "decree_title" not in orphan.to_metadata()


def test_lowercase_decreto_in_transitorio_body_is_not_a_decree_heading(law: LawMetadata) -> None:
    text = (
        "Artículo 1.- Uno.\nTRANSITORIOS\nPRIMERO.- Se abroga el\n"
        "Decreto de 1990 y sus reformas.\nSEGUNDO.- Vigencia.\n"
    )
    first, second = transitorios(text, law)
    assert first.text.endswith("Decreto de 1990 y sus reformas.")
    assert second.decree_date == date(2000, 1, 1)


def test_build_chunks_requires_a_readable_law_name() -> None:
    data = "Artículo 1.- Uno.".encode()
    with pytest.raises(IncompleteLawMetadataError, match="law-name"):
        build_chunks(DocumentSource(filename="LFT.txt", data=data))
    [only] = build_chunks(DocumentSource(filename="LFT.txt", data=data, law_name="LEY FEDERAL DEL TRABAJO"))
    assert only.citation == "[LEY FEDERAL DEL TRABAJO, Art. 1]"


def test_missing_citation_fields(law: LawMetadata) -> None:
    assert law.missing_citation_fields() == ["source_url"]
    full = law.model_copy(update={"source_url": "https://www.dof.gob.mx/x"})
    assert full.missing_citation_fields() == []


def test_repealed_in_parentheses(law: LawMetadata) -> None:
    assert by_label(chunk(EDGE_LAW, law), "6o").is_repealed


def test_preamble_is_not_indexed(law: LawMetadata) -> None:
    chunks = chunk("LEY DE PRUEBA\nAl margen un sello.\nDECRETO\nArtículo 1.- Texto.\n", law)
    assert len(chunks) == 1 and chunks[0].text == "Artículo 1.- Texto."


def test_oversized_article_splits_on_fraction_boundaries(law: LawMetadata) -> None:
    fractions = "\n".join(f"{r}. {'texto de la fracción ' * 10}".strip() for r in ["I", "II", "III", "IV", "V", "VI"])
    text = f"Artículo 1.- Son obligaciones:\n{fractions}\nArtículo 2.- Breve."
    chunks = chunk(text, law, max_chunk_chars=500)
    parts = [c for c in chunks if c.article_label == "1"]
    assert len(parts) > 1
    assert [p.part_index for p in parts] == list(range(1, len(parts) + 1))
    assert all(p.part_count == len(parts) for p in parts)
    assert all(len(p.text) <= 500 for p in parts)
    assert all(p.text.split("\n")[0].startswith(("Artículo 1.-", "I", "V")) for p in parts)
    assert [p.id for p in parts] == [f"lp#art-1#p{i}" for i in range(1, len(parts) + 1)]
    assert "\n".join(p.text for p in parts) == f"Artículo 1.- Son obligaciones:\n{fractions}"
    assert by_label(chunks, "2").part_count == 1


def test_embedding_text_includes_structural_context(law: LawMetadata) -> None:
    art4 = by_label(chunk(EDGE_LAW, law), "4")
    lines = art4.embedding_text().split("\n")
    assert lines[0] == "LEY DE PRUEBA"
    assert "SECCIÓN PRIMERA De los Plazos" in lines[1]
    assert lines[2] == "Artículo 4.- Los plazos se computan en días hábiles."


def test_metadata_is_pinecone_compatible(law: LawMetadata) -> None:
    for c in chunk(EDGE_LAW, law):
        meta = c.to_metadata()
        assert None not in meta.values()
        for value in meta.values():
            assert isinstance(value, str | int | float | bool) or (
                isinstance(value, list) and all(isinstance(v, str) for v in value)
            )


# --------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1º de abril de 1970", date(1970, 4, 1)),
        ("el 1o. de mayo de 1970", date(1970, 5, 1)),
        ("23 de enero de 1998", date(1998, 1, 23)),
        ("13 de marzo 2025", date(2025, 3, 13)),
        ("31 de febrero de 2020", None),
        ("sin fecha", None),
    ],
)
def test_parse_text_date(text: str, expected: date | None) -> None:
    assert parse_text_date(text) == expected


def test_parse_law_header_handles_wrapped_titles() -> None:
    page = (
        "LEY DE AMPARO, REGLAMENTARIA DE LOS ARTÍCULOS 103 Y 107 DE LA CONSTITUCIÓN POLÍTICA DE LOS\n"
        "ESTADOS UNIDOS MEXICANOS\n"
        "CÁMARA DE DIPUTADOS DEL H. CONGRESO DE LA UNIÓN\n"
        "Última Reforma DOF 16-10-2025\n"
        "1 de 119\n"
        "Nueva Ley publicada en el Diario Oficial de la Federación el 2 de abril de 2013\n"
    )
    name, pub, last = parse_law_header(page)
    assert name == (
        "LEY DE AMPARO, REGLAMENTARIA DE LOS ARTÍCULOS 103 Y 107 DE LA CONSTITUCIÓN POLÍTICA DE LOS "
        "ESTADOS UNIDOS MEXICANOS"
    )
    assert pub == date(2013, 4, 2)
    assert last == date(2025, 10, 16)


def test_slugify() -> None:
    assert slugify("Ley Federal del Trabajo") == "ley-federal-del-trabajo"
    assert slugify("353-Ñ") == "353-nn"
    assert slugify("LAmp") == "lamp"


@pytest.mark.parametrize(
    ("values", "expected_len"),
    [([], 0), ([1, 2, 3], 3), ([1, 900, 2, 3], 3), ([5, 1, 2, 2, 3], 4), ([3, 2, 1], 1)],
)
def test_longest_non_decreasing(values: list[int], expected_len: int) -> None:
    idx = _longest_non_decreasing(values)
    assert len(idx) == expected_len
    picked = [values[i] for i in idx]
    assert picked == sorted(picked)
    assert idx == sorted(idx)
