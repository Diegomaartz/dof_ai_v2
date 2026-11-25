"""Post-generation grounding check.

An answer is accepted only when:

* every bracketed citation belongs to a retrieved source (no invented laws, articles or dates), and
* every line that makes a claim carries at least one such citation, so a single valid citation cannot
  launder uncited prose from the model's prior knowledge.

Lines that make no claim are exempt: Markdown headings, list introductions ending in ``:``, short
labels without terminal punctuation, and quotations whose text appears verbatim in a retrieved source.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from agent.state import REFUSAL_MESSAGE, Source

# A bracketed span that is not a Markdown link target ("[texto](url)").
_CITATION = re.compile(r"\[([^\[\]\n]{2,600})\](?!\()")
# Editorial marks inside transcriptions that are not citations.
_EDITORIAL_MARKS = frozenset({"...", "…", "sic", "sic.", "énfasis añadido"})
_HEADING = re.compile(r"^#{1,6}\s")
_LIST_MARKER = re.compile(r"^(?:[-*•]|\d{1,2}[.)])\s+")
_QUOTE_CHARS = "\"'“”«»‘’"
_MAX_LABEL_WORDS = 6
_MIN_QUOTE_CHARS = 20


def normalize_citation(text: str) -> str:
    """Compare citations ignoring case, surrounding brackets and whitespace differences."""
    return " ".join(text.strip().strip("[]").split()).casefold()


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).casefold()


@dataclass
class CitationCheck:
    """Outcome of validating one generated answer."""

    is_refusal: bool
    cited: list[Source] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    uncited: list[str] = field(default_factory=list)
    """Claim lines without any citation to a retrieved source."""

    @property
    def grounded(self) -> bool:
        """Grounded: cites at least one source, nothing outside the sources, and no claim line is uncited."""
        return not self.is_refusal and bool(self.cited) and not self.unknown and not self.uncited


def _is_verbatim_quote(body: str, sources: Sequence[Source]) -> bool:
    """A line that only quotes source text (``"Artículo 61.- ..."``) needs no citation of its own."""
    if not body or body[0] not in _QUOTE_CHARS + ">":
        return False
    quoted = _normalize_text(body.lstrip(">").strip().strip(_QUOTE_CHARS + ".,;… "))
    if len(quoted) < _MIN_QUOTE_CHARS:
        return False
    return any(quoted in _normalize_text(s.text) for s in sources)


def _claim_body(line: str) -> str | None:
    """Return the text of a line that makes a claim, or ``None`` for structural lines."""
    text = line.strip()
    if not text or _HEADING.match(text):
        return None
    body = _LIST_MARKER.sub("", text).strip().strip("*_").strip()
    if not body or body.endswith(":"):
        return None
    if len(body.split()) <= _MAX_LABEL_WORDS and not body.endswith((".", ";", "”", '"', ")")):
        return None  # a short label such as "Jornada diurna" or "**Respuesta**"
    return body


def check_citations(answer: str, sources: Sequence[Source]) -> CitationCheck:
    """Match the citations in ``answer`` against ``sources`` and find claim lines without citations.

    Returns the cited sources (in order of first appearance), any bracketed citation that does not
    correspond to a source, and the uncited claim lines; the caller must treat the last two as
    hallucinations.
    """
    if normalize_citation(REFUSAL_MESSAGE.rstrip(".")) in normalize_citation(answer):
        return CitationCheck(is_refusal=True)
    by_citation = {normalize_citation(s.citation): s for s in sources}
    cited: list[Source] = []
    unknown: list[str] = []
    uncited: list[str] = []
    for line in answer.splitlines():
        line_has_citation = False
        for match in _CITATION.finditer(line):
            key = normalize_citation(match.group(1))
            if key in _EDITORIAL_MARKS:
                continue
            source = by_citation.get(key)
            if source is None:
                unknown.append(match.group(0))
                continue
            line_has_citation = True
            if source not in cited:
                cited.append(source)
        body = _claim_body(line)
        if body is not None and not line_has_citation and not _is_verbatim_quote(body, sources):
            uncited.append(line.strip())
    return CitationCheck(is_refusal=False, cited=cited, unknown=unknown, uncited=uncited)
