"""Previews while editing (docs/ui/content-formatting.md, "Previews while editing").

The editor sends the note it is editing with CARET_MARK where the caret is. The
note is rendered as it is shown, twice, listing its formulas instead of drawing
them: once without the mark and once with it. The formula holding the mark is the
one under the caret, provided both renders met the same formulas. When they did
not, the mark changed what the renderer reads (the caret inside a delimiter, or
right after a `$` that does not open a formula) and nothing is previewed. So a
preview shows only a formula the note itself shows, drawn by the same renderer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.security.rendered_html import sanitize_rendered_html
from app.services.content_formatting import format_note_content_for_view
from app.services.content_formatting import holding_link_fetches
from app.services.latex_rendering import FoundFormula
from app.services.latex_rendering import finding_formulas
from app.services.latex_rendering import render_latex_math_to_html
from app.utils.not_found import NOT_FOUND

# A Unicode noncharacter: reserved for a program's own use, never in text people write.
CARET_MARK = "\ufdd0"
# A formula worth previewing looks different drawn: a command, a superscript or
# subscript, a group. `$$x$$` or `$$12$$` looks the same as typed.
_CHANGES_HOW_IT_LOOKS_RE = re.compile(r"[\\^_{]")
# latex2mathml draws a command it does not know (`\fra`, half of `\frac`) as its own
# name in an identifier, as the note shows it. While typing that is a command not finished.
_UNKNOWN_COMMAND_RE = re.compile(r"<mi>\\[A-Za-z]")

PREVIEW_NONE = "none"
PREVIEW_LATEX = "latex"


@dataclass(frozen=True, slots=True)
class EditPreview:
    """What to show under the caret: nothing, or a formula drawn (or why it cannot be).

    `has_unknown_command` marks a drawing with a command the renderer does not know,
    which the note shows as typed: the browser holds the last good drawing while the
    user types, and shows this one once they pause.
    """

    kind: str
    html: str
    error: str
    has_unknown_command: bool


_NO_PREVIEW = EditPreview(kind=PREVIEW_NONE, html="", error="", has_unknown_command=False)


def edit_preview_at_caret(*, marked_content_html: str, tags: str) -> EditPreview:
    if not isinstance(marked_content_html, str):
        raise TypeError("marked_content_html must be a string")
    if not isinstance(tags, str):
        raise TypeError("tags must be a string")
    if marked_content_html.count(CARET_MARK) != 1:
        raise ValueError("the content must hold the caret mark exactly once")

    content_html = marked_content_html.replace(CARET_MARK, "")
    formulas = _formulas_in(content_html=content_html, tags=tags)
    marked_formulas = _formulas_in(content_html=marked_content_html, tags=tags)
    under_mark = _formula_under_mark(formulas=formulas, marked_formulas=marked_formulas)
    if under_mark == NOT_FOUND:
        return _NO_PREVIEW
    formula = formulas[under_mark]
    if _CHANGES_HOW_IT_LOOKS_RE.search(formula.source) is None:
        return _NO_PREVIEW
    rendered = render_latex_math_to_html(formula.source, display=formula.display)
    if rendered.has_error:
        return EditPreview(
            kind=PREVIEW_LATEX, html="", error=_error_text(rendered.error_message),
            has_unknown_command=False,
        )
    assert rendered.html != "", "a formula that changes how it looks draws something"
    # Sanitized last, as every rendering the page shows (app/security/rendered_html.py).
    return EditPreview(
        kind=PREVIEW_LATEX, html=sanitize_rendered_html(rendered.html), error="",
        has_unknown_command=_UNKNOWN_COMMAND_RE.search(rendered.html) is not None,
    )


def _formulas_in(*, content_html: str, tags: str) -> list[FoundFormula]:
    with holding_link_fetches(), finding_formulas() as found:
        format_note_content_for_view(content_html=content_html, tags=tags, redact_credentials=True)
    return found


# Where in the list the formula holding the mark is, or NOT_FOUND when there is none or
# the mark changed which formulas the render met.
def _formula_under_mark(*, formulas: list[FoundFormula], marked_formulas: list[FoundFormula]) -> int:
    if len(formulas) != len(marked_formulas):
        return NOT_FOUND
    under_mark = [index for index, formula in enumerate(marked_formulas) if CARET_MARK in formula.source]
    if len(under_mark) != 1:
        return NOT_FOUND
    for formula, marked in zip(formulas, marked_formulas):
        if marked.source.replace(CARET_MARK, "") != formula.source or marked.display != formula.display:
            return NOT_FOUND
    return under_mark[0]


# The badge a broken formula shows in the note, then what the renderer said, when it said anything.
def _error_text(message: str) -> str:
    if message.strip() == "":
        return "Invalid LaTeX"
    return f"Invalid LaTeX: {message.strip()}"
