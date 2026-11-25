"""Versioned prompt templates stored as ``<name>.<version>.md`` files next to this module.

Templates use ``string.Template`` placeholders (``$question``) so legal text containing braces
never breaks formatting. Bump the version (new file) instead of editing a prompt in place.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).parent

PROMPT_VERSIONS: dict[str, str] = {
    "router": "v1",
    "grader": "v2",
    "rewrite": "v1",
    "generate": "v2",
}


@cache
def _template(name: str, version: str) -> Template:
    path = PROMPTS_DIR / f"{name}.{version}.md"
    return Template(path.read_text(encoding="utf-8"))


def render_prompt(name: str, version: str | None = None, **values: str) -> str:
    """Render prompt ``name`` (at its pinned version unless ``version`` is given) with ``values``.

    Raises ``KeyError`` if the template references a placeholder that was not supplied.
    """
    return _template(name, version or PROMPT_VERSIONS[name]).substitute(values)
