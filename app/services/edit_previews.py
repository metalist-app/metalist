"""Previews while editing (docs/ui/content-formatting.md, "Previews while editing").

The editor sends the note it is editing with CARET_MARK where the caret is. The
note is rendered as it is shown, twice, listing its formulas and CSV tables
instead of drawing them: once without the mark and once with it. The formula or
table holding the mark is the one under the caret, provided both renders met the
same ones. When they did not, the mark changed what the renderer reads (the caret
inside a delimiter, or right after a `$` that does not open a formula) and nothing
is previewed. So a preview shows only what the note itself shows, drawn by the
same renderer.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Sequence

from app.security.rendered_html import sanitize_rendered_html
from app.services.content_formatting import FoundTable
from app.services.content_formatting import finding_tables
from app.services.content_formatting import format_note_content_for_view
from app.services.content_formatting import holding_link_fetches
from app.services.latex_rendering import FoundFormula
from app.services.latex_rendering import finding_formulas
from app.services.latex_rendering import render_latex_math_to_html
from app.services.structured_note_renderers import csv_error_message
from app.services.structured_note_renderers import extract_plain_text_from_note_html
from app.utils.not_found import NOT_FOUND

# A Unicode noncharacter: reserved for a program's own use, never in text people write.
CARET_MARK = "\ufdd0"
# A formula worth previewing looks different drawn: a command, a superscript or
# subscript, a group. `$$x$$` or `$$12$$` looks the same as typed.
_CHANGES_HOW_IT_LOOKS_RE = re.compile(r"[\\^_{]")
# latex2mathml draws a command it does not know (`\fra`, half of `\frac`) as its own
# name in an identifier, as the note shows it. While typing that is a command not finished.
_UNKNOWN_COMMAND_RE = re.compile(r"<mi>\\[A-Za-z]")
# A table worth previewing has a row of more than one cell; one column looks as typed.
_SINGLE_CELL = 1

PREVIEW_NONE = "none"
PREVIEW_LATEX = "latex"
PREVIEW_CSV = "csv"


@dataclass(frozen=True, slots=True)
class EditPreview:
    """What to show under the caret: nothing, or a formula or table drawn (or why it cannot be).

    `has_unknown_command` marks a drawing with a command the renderer does not know,
    which the note shows as typed: the browser holds the last good drawing while the
    user types, and shows this one once they pause. `caret_row` is the table row
    (counted from 0) holding the caret, so the browser can keep it in view; NOT_FOUND
    for a formula, or a caret on no row.
    """

    kind: str
    html: str
    error: str
    has_unknown_command: bool
    caret_row: int


_NO_PREVIEW = EditPreview(kind=PREVIEW_NONE, html="", error="", has_unknown_command=False, caret_row=NOT_FOUND)


@dataclass(frozen=True, slots=True)
class _Found:
    formulas: list[FoundFormula]
    tables: list[FoundTable]


def edit_preview_at_caret(*, marked_content_html: str, tags: str) -> EditPreview:
    if not isinstance(marked_content_html, str):
        raise TypeError("marked_content_html must be a string")
    if not isinstance(tags, str):
        raise TypeError("tags must be a string")
    if marked_content_html.count(CARET_MARK) != 1:
        raise ValueError("the content must hold the caret mark exactly once")

    found = _found_in(content_html=marked_content_html.replace(CARET_MARK, ""), tags=tags)
    marked = _found_in(content_html=marked_content_html, tags=tags)
    formula_sources = [(formula.source, formula.display) for formula in found.formulas]
    marked_formula_sources = [(formula.source, formula.display) for formula in marked.formulas]
    table_sources = [(table.source_html, "") for table in found.tables]
    marked_table_sources = [(table.source_html, "") for table in marked.tables]
    if not _same_but_for_mark(formula_sources, marked_formula_sources) or not _same_but_for_mark(table_sources, marked_table_sources):
        return _NO_PREVIEW
    # A formula in a table's cell is drawn with its table, which renders as nothing while
    # tables are found, so the caret is in at most one formula or one table.
    formula_index = _index_holding_mark(marked_formula_sources)
    if formula_index != NOT_FOUND:
        return _formula_preview(found.formulas[formula_index])
    table_index = _index_holding_mark(marked_table_sources)
    if table_index != NOT_FOUND:
        return _table_preview(found.tables[table_index], marked_source_html=marked.tables[table_index].source_html)
    return _NO_PREVIEW


def _found_in(*, content_html: str, tags: str) -> _Found:
    with holding_link_fetches(), finding_formulas() as formulas, finding_tables() as tables:
        format_note_content_for_view(content_html=content_html, tags=tags, redact_credentials=True)
    return _Found(formulas=formulas, tables=tables)


# Whether the render with the mark met the same regions as the one without it.
def _same_but_for_mark(sources: Sequence[tuple[str, str]], marked_sources: Sequence[tuple[str, str]]) -> bool:
    if len(sources) != len(marked_sources):
        return False
    return all(
        marked_source.replace(CARET_MARK, "") == source and marked_kind == kind
        for (source, kind), (marked_source, marked_kind) in zip(sources, marked_sources)
    )


def _index_holding_mark(marked_sources: Sequence[tuple[str, str]]) -> int:
    holding = [index for index, (source, _kind) in enumerate(marked_sources) if CARET_MARK in source]
    assert len(holding) <= 1, "the mark is in one place"
    if not holding:
        return NOT_FOUND
    return holding[0]


def _formula_preview(formula: FoundFormula) -> EditPreview:
    if _CHANGES_HOW_IT_LOOKS_RE.search(formula.source) is None:
        return _NO_PREVIEW
    rendered = render_latex_math_to_html(formula.source, display=formula.display)
    if rendered.has_error:
        return EditPreview(
            kind=PREVIEW_LATEX, html="", error=_error_text("Invalid LaTeX", rendered.error_message),
            has_unknown_command=False, caret_row=NOT_FOUND,
        )
    assert rendered.html != "", "a formula that changes how it looks draws something"
    # Sanitized last, as every rendering the page shows (app/security/rendered_html.py).
    return EditPreview(
        kind=PREVIEW_LATEX, html=sanitize_rendered_html(rendered.html), error="",
        has_unknown_command=_UNKNOWN_COMMAND_RE.search(rendered.html) is not None, caret_row=NOT_FOUND,
    )


def _table_preview(table: FoundTable, *, marked_source_html: str) -> EditPreview:
    marked_rows = _rows_of(marked_source_html)
    if all(len(row) <= _SINGLE_CELL for row in marked_rows):
        return _NO_PREVIEW
    rendered = table.render()
    error = csv_error_message(rendered)
    if error != "":
        return EditPreview(
            kind=PREVIEW_CSV, html="", error=_error_text("Invalid CSV", error),
            has_unknown_command=False, caret_row=NOT_FOUND,
        )
    caret_rows = [index for index, row in enumerate(marked_rows) if any(CARET_MARK in cell for cell in row)]
    caret_row = NOT_FOUND
    if caret_rows:
        caret_row = caret_rows[0]
    return EditPreview(
        kind=PREVIEW_CSV, html=sanitize_rendered_html(rendered), error="",
        has_unknown_command=False, caret_row=caret_row,
    )


# The table's rows as the renderer counts them: rows of nothing but empty cells (the
# caret mark aside) are left out.
def _rows_of(source_html: str) -> list[list[str]]:
    text = extract_plain_text_from_note_html(source_html)
    return [row for row in csv.reader(io.StringIO(text)) if not all(cell.replace(CARET_MARK, "") == "" for cell in row)]


# The badge the note shows, then why, when the renderer said why.
def _error_text(badge: str, message: str) -> str:
    if message.strip() == "":
        return badge
    return f"{badge}: {message.strip()}"
