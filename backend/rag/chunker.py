"""Structural chunker for Mexican federal legislation.

Splits a law into its natural legal units instead of fixed-size windows:

* **Articles** of the body (``Artículo 1o.-``, ``Artículo 22 Bis.``, ``Artículo 15-A.``),
  each tagged with its LIBRO / TÍTULO / CAPÍTULO / SECCIÓN path.
* **Transitional articles** of the original law and of every reform decree
  (``TRANSITORIOS`` -> ``PRIMERO.-``, ``Artículo Segundo.-``, ``ÚNICO.-``), each tagged
  with the decree title and DOF publication date.

Robustness rules:

* Matching is accent- and case-insensitive, but a heading must start with an
  uppercase letter and be followed by a separator (``.``, ``.-``, ``-``) and an
  uppercase body, so in-text references such as "el artículo 5o. de esta Ley"
  wrapped onto a new line are not mistaken for headings.
* Body article numbers must form a non-decreasing sequence. Among all
  candidate headings the longest such subsequence is kept, which discards
  stray matches without letting one bad match swallow the rest of the law.
* Decree bodies ("ARTÍCULO ÚNICO.- Se reforman ...") and promulgation/signature
  blocks of reform decrees are skipped: the amended text already lives in the
  body articles, and signatures carry no legal content.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, auto

from rag.models import LawMetadata, LegalChunk, SectionType

# --------------------------------------------------------------------------- folding

_ACCENTS = str.maketrans("ÁÉÍÓÚÜáéíóúü", "AEIOUUaeiouu")


def fold(text: str) -> str:
    """Upper-case and strip Spanish accents while preserving string length (so spans stay valid)."""
    folded = text.translate(_ACCENTS).upper()
    return folded if len(folded) == len(text) else text.upper()


def slugify(text: str) -> str:
    """ASCII slug for vector IDs (Pinecone ID prefixes must be ASCII)."""
    text = text.replace("Ñ", "Nn").replace("ñ", "nn")  # keep "353-Ñ" distinct from "353-N"
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


# --------------------------------------------------------------------------- patterns (on folded text)

_UNITS = r"PRIMER[OA]?|SEGUND[OA]|TERCER[OA]?|CUART[OA]|QUINT[OA]|SEXT[OA]|SEPTIM[OA]|OCTAV[OA]|NOVEN[OA]"
_TENS = r"DECIM[OA]|VIGESIM[OA]|TRIGESIM[OA]|CUADRAGESIM[OA]|QUINCUAGESIM[OA]"
_CARDINALS = r"ONCE|DOCE|TRECE|CATORCE|QUINCE|DIECI[A-Z]+|VEINTI[A-Z]+|VEINTE|TREINTA"
# Compound ordinals ("DÉCIMO PRIMERO") must be tried before their bare prefixes.
ORDINAL = (
    rf"(?:(?:{_TENS})\s*(?:{_UNITS})|UNDECIM[OA]|DUODECIM[OA]|(?:{_TENS})|(?:{_UNITS})"
    rf"|UNIC[OA]|PRELIMINAR|{_CARDINALS})"
)
_LATIN = r"BIS|TER|QUATER|QUINQUIES|SEXIES|SEPTIES|OCTIES|NONIES|DECIES"
_SEP = r"(?P<sep>\.\s*-|\.|-|–|:)"

HEADING_RE = re.compile(
    rf"^(?P<kind>LIBRO|TITULO|CAPITULO|SECCION)\s+"
    rf"(?P<ord>(?:{ORDINAL}|[IVXLC]+|\d+)(?:\s+(?:{_LATIN}))?)(?![A-Z0-9])"
    r"\s*[.:\-–]?\s*(?P<rest>.*)$"
)
ARTICLE_RE = re.compile(
    r"^ARTICULO\s+(?P<num>\d{1,4})"
    r"(?:-(?P<letter>[A-ZÑ])(?![A-ZÑ]))?"
    r"(?P<ord>\s*[Oº°](?![A-Z]))?"
    rf"(?:\.?\s+(?P<suffix>{_LATIN})(?:\s+(?P<sufnum>\d+))?)?"
    rf"\s*(?:{_SEP}(?P<body>.*))?$"
)
TRANSITORIO_ART_RE = re.compile(rf"^(?:ARTICULO\s+)?(?P<ord>{ORDINAL})\s*{_SEP}(?P<body>.*)$")
TRANSITORIOS_RE = re.compile(r"^(?:ARTICULOS?\s+)?TRANSITORIOS?\s*\.?$")
APPENDIX_RE = re.compile(r"^(?:ARTICULOS\s+)?TRANSITORIOS\s+DE\s+(?:LOS\s+)?DECRETOS?\s+DE\s+REFORMAS?")
DECREE_RE = re.compile(r"^DECRETO\s+(?:POR|MEDIANTE|QUE|EN)\b")
PUBLISHED_RE = re.compile(r"^PUBLICAD[OA]\s+EN\s+EL\s+DIARIO\s+OFICIAL\s+DE\s+LA\s+FEDERACION\s+EL\s+(?P<date>.+)$")
SIGNATURE_RE = re.compile(
    r"^(?:(?:MEXICO|CIUDAD DE MEXICO)(?:,?\s*D\.\s*F\.)?,?\s+A\s+(?:\d{1,2}|LOS?\b)"
    r"|EN CUMPLIMIENTO DE LO DISPUESTO|SALON DE SESIONES)"
)
REFORM_NOTE_RE = re.compile(r"\b(?:REFORMAD|ADICIONAD|DEROGAD|RECORRID|ABROGAD)[OA]S?\b.*\bDOF\b")
DOF_DATE_RE = re.compile(r"\bDOF\s+\d{2}-\d{2}-\d{4}")
REPEALED_RE = re.compile(r"^\(?\s*SE\s+DEROGA", re.IGNORECASE)
NUMERIC_DATE_RE = re.compile(r"\b(\d{2})-(\d{2})-(\d{4})\b")
FRACTION_START_RE = re.compile(r"^(?:[IVXLC]+|[A-Za-z]|\d{1,2})\s*[.)]\s*-?\s*\S")
_DOTS_RE = re.compile(r"^[.\s…]+$")

_MONTHS = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
    "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}  # fmt: skip
TEXT_DATE_RE = re.compile(
    rf"(?P<d>\d{{1,2}})\s*(?:O|º|°)?\.?\s+DE\s+(?P<m>{'|'.join(_MONTHS)})\s+(?:(?:DE|DEL)\s+)?(?P<y>\d{{4}})"
)
_PUBLICATION_RE = re.compile(r"PUBLICAD[OA]\s+EN\s+EL\s+DIARIO\s+OFICIAL\s+DE\s+LA\s+FEDERACION\s+EL\s+(?P<date>.+)")
_LAST_REFORM_RE = re.compile(r"ULTIMA\s+REFORMA\s+(?:PUBLICADA\s+)?(?:DOF\s+)?(?P<date>\d{2}-\d{2}-\d{4})")
_LAW_TITLE_RE = re.compile(r"\b(?:LEY|CODIGO|CONSTITUCION|REGLAMENTO|ESTATUTO|ACUERDO|DECRETO|NORMA)\b")
_PAGE_OF_RE = re.compile(r"^\d{1,4}\s+de\s+\d{1,4}$", re.IGNORECASE)
_HEADER_NOISE_RE = re.compile(r"CAMARA DE DIPUTADOS|SECRETARIA (?:GENERAL|DE SERVICIOS)|ULTIMA REFORMA|TEXTO VIGENTE")

_HIERARCHY_ORDER = ("libro", "titulo", "capitulo", "seccion")


def parse_text_date(text: str) -> date | None:
    """Parse Spanish long dates such as ``1º de abril de 1970`` (input may be unfolded)."""
    if m := TEXT_DATE_RE.search(fold(text)):
        return _safe_date(int(m["y"]), _MONTHS[m["m"]], int(m["d"]))
    return None


def parse_numeric_dates(text: str) -> list[date]:
    """Parse every ``DD-MM-YYYY`` date in *text*."""
    found = (_safe_date(int(y), int(m), int(d)) for d, m, y in NUMERIC_DATE_RE.findall(text))
    return [d for d in found if d]


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_law_header(first_page: str) -> tuple[str | None, date | None, date | None]:
    """Extract (law name, original publication date, last reform date) from the first page."""
    name: str | None = None
    publication: date | None = None
    last_reform: date | None = None
    name_open = False  # titles often wrap: "LEY DE AMPARO, ... DE LOS" / "ESTADOS UNIDOS MEXICANOS"
    for line in (ln.strip() for ln in first_page.split("\n")):
        if not line:
            continue
        f = fold(line)
        is_title_line = line.isupper() and not _HEADER_NOISE_RE.search(f) and not _PAGE_OF_RE.match(line)
        if name is None and is_title_line and _LAW_TITLE_RE.search(f):
            name, name_open = line, True
            continue
        if name_open:
            if is_title_line and name is not None and fold(line) not in fold(name):
                name = f"{name} {line}"
            else:
                name_open = False
        if publication is None and (m := _PUBLICATION_RE.search(f)):
            publication = parse_text_date(m["date"])
        if last_reform is None and (m := _LAST_REFORM_RE.search(f)):
            dates = parse_numeric_dates(m["date"])
            last_reform = dates[0] if dates else None
    return name, publication, last_reform


# --------------------------------------------------------------------------- chunker


@dataclass(frozen=True)
class ChunkerConfig:
    """Tuning knobs for :class:`LegalChunker`.

    Attributes:
        max_chunk_chars: Articles longer than this are split on fraction boundaries
            (Titan v2 accepts ~50k chars; Pinecone metadata is capped at 40 KB).
        max_title_lines: Lines after a heading that are folded into its title.
    """

    max_chunk_chars: int = 8000
    max_title_lines: int = 3


class _State(Enum):
    PREAMBLE = auto()
    BODY = auto()
    TRANSITORIOS = auto()
    SKIP = auto()  # decree bodies, signature blocks, appendix intro


@dataclass
class _Draft:
    section_type: SectionType
    label: str
    number: int | None
    lines: list[str]
    hierarchy: dict[str, str] = field(default_factory=dict)
    decree_title: str | None = None
    decree_date: date | None = None
    block: int | None = None
    body: str = ""  # text following the heading separator on the first line


@dataclass
class _HeadingState:
    kind: str
    text: str
    title_lines: list[str] = field(default_factory=list)


class LegalChunker:
    """Turn the cleaned text of a Mexican law into :class:`LegalChunk` objects."""

    def __init__(self, config: ChunkerConfig | None = None) -> None:
        self.config = config or ChunkerConfig()

    def chunk(self, text: str, law: LawMetadata) -> list[LegalChunk]:
        """Split *text* (already free of page furniture) into structural chunks."""
        lines = [ln.strip() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln and not _DOTS_RE.match(ln)]
        folded = [fold(ln) for ln in lines]

        body_end = self._find_body_end(lines, folded)
        accepted = self._accepted_body_articles(lines, folded, body_end)
        drafts = self._walk(lines, folded, body_end, accepted, law)
        return self._finalize(drafts, law)

    # ----------------------------------------------------------------- pass 1

    def _find_body_end(self, lines: list[str], folded: list[str]) -> int:
        """Index of the first TRANSITORIOS / reform-appendix heading after the first article."""
        seen_article = False
        for i, f in enumerate(folded):
            if not seen_article:
                seen_article = self._article_match(lines[i], f) is not None
                continue
            if _starts_upper(lines[i]) and (TRANSITORIOS_RE.match(f) or APPENDIX_RE.match(f)):
                return i
        return len(lines)

    def _accepted_body_articles(self, lines: list[str], folded: list[str], body_end: int) -> set[int]:
        """Keep the longest non-decreasing run of article numbers among body candidates."""
        candidates: list[tuple[int, int]] = []
        for i in range(body_end):
            if m := self._article_match(lines[i], folded[i]):
                candidates.append((i, int(m["num"])))
        return {candidates[k][0] for k in _longest_non_decreasing([n for _, n in candidates])}

    # ----------------------------------------------------------------- pass 2

    def _walk(
        self, lines: list[str], folded: list[str], body_end: int, accepted: set[int], law: LawMetadata
    ) -> list[_Draft]:
        drafts: list[_Draft] = []
        current: _Draft | None = None
        state = _State.PREAMBLE
        hierarchy: dict[str, _HeadingState] = {}
        open_heading: _HeadingState | None = None
        block = -1
        decree_title: str | None = None
        decree_date: date | None = None
        decree_title_open = False

        def close() -> None:
            nonlocal current
            if current is not None:
                drafts.append(current)
                current = None

        for i, (line, f) in enumerate(zip(lines, folded, strict=True)):
            if i < body_end:
                # ---------------- body: headings and articles
                heading = self._heading_match(line, f)
                if heading:
                    close()
                    state = _State.BODY
                    kind = heading["kind"].lower()
                    level = _HIERARCHY_ORDER.index(kind)
                    for k in _HIERARCHY_ORDER[level:]:
                        hierarchy.pop(k, None)
                    rest = line[heading.start("rest") :].strip()
                    head_text = line[: heading.start("rest")].strip().rstrip(".:-– ")
                    open_heading = _HeadingState(kind, head_text, [rest] if rest else [])
                    hierarchy[kind] = open_heading
                    continue
                if i in accepted:
                    close()
                    state = _State.BODY
                    open_heading = None
                    m = self._article_match(line, f)
                    assert m is not None
                    current = _Draft(
                        SectionType.ARTICULO,
                        _article_label(m),
                        int(m["num"]),
                        [line],
                        hierarchy={k: _heading_text(h) for k, h in hierarchy.items()},
                        body=_match_body(line, m),
                    )
                    continue
                if open_heading is not None:
                    is_note = REFORM_NOTE_RE.search(f) or DOF_DATE_RE.search(f)
                    if not is_note and len(open_heading.title_lines) < self.config.max_title_lines:
                        open_heading.title_lines.append(line)
                    continue
                if current is not None:
                    current.lines.append(line)
                continue

            # ---------------- transitorios region (original law + reform decrees)
            upper = _starts_upper(line)
            if upper and APPENDIX_RE.match(f):
                close()
                state = _State.SKIP
                continue
            if upper and TRANSITORIOS_RE.match(f):
                close()
                state = _State.TRANSITORIOS
                block += 1
                decree_title_open = False
                if block == 0 and decree_title is None:
                    decree_date = law.publication_date
                continue
            if upper and DECREE_RE.match(f):
                close()
                state = _State.SKIP
                decree_title, decree_date, decree_title_open = line, None, True
                continue
            if m := PUBLISHED_RE.match(f):
                decree_date = parse_text_date(m["date"]) or decree_date
                decree_title_open = False
                continue
            if upper and SIGNATURE_RE.match(f):
                close()
                state = _State.SKIP
                continue
            if decree_title_open and state is _State.SKIP:
                if decree_title is not None and len(decree_title) < 600:
                    decree_title = f"{decree_title} {line}"
                continue
            if state is not _State.TRANSITORIOS:
                continue
            if found := self._transitorio_label(line, f):
                close()
                label, body = found
                current = _Draft(
                    SectionType.TRANSITORIO,
                    label,
                    None,
                    [line],
                    decree_title=decree_title,
                    decree_date=decree_date,
                    block=block,
                    body=body,
                )
                continue
            if current is not None:
                current.lines.append(line)

        close()
        return drafts

    # ----------------------------------------------------------------- matching helpers

    @staticmethod
    def _article_match(line: str, f: str) -> re.Match[str] | None:
        if not _starts_upper(line) or not (m := ARTICLE_RE.match(f)):
            return None
        body = _match_body(line, m)
        if m["sep"] is None and body:
            return None
        if body and not _starts_body(body):
            return None
        return m

    @staticmethod
    def _heading_match(line: str, f: str) -> re.Match[str] | None:
        if len(line) > 200 or not _starts_upper(line) or not (m := HEADING_RE.match(f)):
            return None
        rest = line[m.start("rest") :].strip()
        if rest and not _starts_body(rest):
            return None
        return m

    def _transitorio_label(self, line: str, f: str) -> tuple[str, str] | None:
        """Return (label, body) when *line* opens a transitional article."""
        if not _starts_upper(line):
            return None
        if m := self._article_match(line, f):
            return _article_label(m), _match_body(line, m)
        if m := TRANSITORIO_ART_RE.match(f):
            body = _match_body(line, m)
            if not body or _starts_body(body):
                return " ".join(line[m.start("ord") : m.end("ord")].split()).title(), body
        return None

    # ----------------------------------------------------------------- finalize

    def _finalize(self, drafts: list[_Draft], law: LawMetadata) -> list[LegalChunk]:
        chunks: list[LegalChunk] = []
        seen_ids: dict[str, int] = {}
        for d in drafts:
            text = "\n".join(d.lines).strip()
            notes = [ln for ln in d.lines[1:] if REFORM_NOTE_RE.search(fold(ln))]
            reform_dates = sorted({dt for ln in notes for dt in parse_numeric_dates(ln)})
            lead = d.body or (d.lines[1] if len(d.lines) > 1 else "")
            is_repealed = len(text) < 300 and bool(REPEALED_RE.match(lead))
            base_id = _chunk_id(law.law_slug, d)
            n = seen_ids.get(base_id, 0)
            seen_ids[base_id] = n + 1
            if n:
                base_id = f"{base_id}~{n + 1}"
            parts = _split_oversized(d.lines, self.config.max_chunk_chars)
            for idx, part in enumerate(parts, start=1):
                chunks.append(
                    LegalChunk(
                        id=base_id if len(parts) == 1 else f"{base_id}#p{idx}",
                        law=law,
                        section_type=d.section_type,
                        article_label=d.label,
                        article_number=d.number,
                        hierarchy=d.hierarchy,
                        text=part,
                        reform_dates=reform_dates,
                        is_repealed=is_repealed,
                        decree_title=d.decree_title,
                        decree_date=d.decree_date,
                        transitorio_block=d.block,
                        part_index=idx,
                        part_count=len(parts),
                    )
                )
        return chunks


# --------------------------------------------------------------------------- module helpers


def _starts_upper(line: str) -> bool:
    return bool(line) and line[0].isupper()


def _starts_body(text: str) -> bool:
    """A heading's trailing text must look like the start of a sentence or a title."""
    ch = text[0]
    return ch.isupper() or ch.isdigit() or ch in "(\"'“«¿¡[-–"


def _match_body(line: str, m: re.Match[str]) -> str:
    return line[m.start("body") :].strip() if m["body"] is not None else ""


def _article_label(m: re.Match[str]) -> str:
    label = m["num"]
    if m["letter"]:
        label += f"-{m['letter']}"
    if m["ord"]:
        label += "o"
    if m["suffix"]:
        label += f" {m['suffix'].title()}"
        if m["sufnum"]:
            label += f" {m['sufnum']}"
    return label


def _heading_text(h: _HeadingState) -> str:
    return " ".join([h.text, *h.title_lines]).strip()


def _chunk_id(law_slug: str, d: _Draft) -> str:
    if d.section_type is SectionType.TRANSITORIO:
        return f"{law_slug}#tr{d.block or 0:03d}-{slugify(d.label)}"
    return f"{law_slug}#art-{slugify(d.label)}"


def _longest_non_decreasing(values: list[int]) -> list[int]:
    """Indices of one longest non-decreasing subsequence (O(n log n) patience sorting)."""
    if not values:
        return []
    tails: list[int] = []  # values at the end of each candidate run length
    tail_idx: list[int] = []
    prev = [-1] * len(values)
    for i, v in enumerate(values):
        pos = bisect.bisect_right(tails, v)
        if pos == len(tails):
            tails.append(v)
            tail_idx.append(i)
        else:
            tails[pos] = v
            tail_idx[pos] = i
        prev[i] = tail_idx[pos - 1] if pos else -1
    out: list[int] = []
    k = tail_idx[-1]
    while k != -1:
        out.append(k)
        k = prev[k]
    return out[::-1]


def _split_oversized(lines: list[str], max_chars: int) -> list[str]:
    """Return the article text, split on fraction boundaries only if it exceeds *max_chars*."""
    text = "\n".join(lines).strip()
    if len(text) <= max_chars:
        return [text]

    segments: list[list[str]] = [[]]
    for ln in lines:
        if segments[-1] and FRACTION_START_RE.match(ln):
            segments.append([])
        segments[-1].append(ln)

    pieces: list[str] = []
    for seg in segments:
        seg_text = "\n".join(seg)
        if len(seg_text) <= max_chars:
            pieces.append(seg_text)
        else:  # a single fraction longer than the limit: fall back to line/word boundaries
            pieces.extend(_hard_wrap(seg, max_chars))

    parts: list[str] = []
    buf = ""
    for piece in pieces:
        candidate = f"{buf}\n{piece}" if buf else piece
        if len(candidate) > max_chars and buf:
            parts.append(buf)
            buf = piece
        else:
            buf = candidate
    if buf:
        parts.append(buf)
    return parts


def _hard_wrap(lines: list[str], max_chars: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for ln in lines:
        while len(ln) > max_chars:
            cut = ln.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            if buf:
                out.append(buf)
                buf = ""
            out.append(ln[:cut])
            ln = ln[cut:].lstrip()
        candidate = f"{buf}\n{ln}" if buf else ln
        if len(candidate) > max_chars:
            out.append(buf)
            buf = ln
        else:
            buf = candidate
    if buf:
        out.append(buf)
    return out
