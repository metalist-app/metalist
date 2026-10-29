"""Previews while editing (docs/ui/content-formatting.md, "Previews while editing")."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

import app.services.content_formatting as content_formatting_module
from app.security.rendered_html import sanitize_rendered_html
from app.services.content_formatting import format_note_content_for_view
from app.services.edit_previews import CARET_MARK, PREVIEW_CSV, PREVIEW_JSON, PREVIEW_LATEX, PREVIEW_MERMAID, PREVIEW_NONE, edit_preview_at_caret
from app.utils.not_found import NOT_FOUND
from app.services.latex_rendering import FoundFormula, finding_formulas, render_latex_math_to_html, render_latex_to_html

MARKDOWN = "@markdown"
LATEX = "@LaTeX"


def _preview(content_html: str, tags: str):
    return edit_preview_at_caret(marked_content_html=content_html.replace("|", CARET_MARK), tags=tags)


# As the note draws it: rendered, then sanitized as every rendering the page shows.
def _drawn(source: str, display: str) -> str:
    return sanitize_rendered_html(render_latex_math_to_html(source, display=display).html)


@pytest.mark.parametrize(
    ("content_html", "tags", "source", "display"),
    [
        ("<div>A half: $$\\frac{1}{|2}$$ done</div>", MARKDOWN, "\\frac{1}{2}", "block"),
        ("<div>Inline $a^|2 + b^2$ here.</div>", MARKDOWN, "a^2 + b^2", "inline"),
        ("<div>\\(a^|2\\) and \\[b_1\\]</div>", MARKDOWN, "a^2", "inline"),
        ("<div>\\(a^2\\) and \\[b_|1\\]</div>", MARKDOWN, "b_1", "block"),
        # The caret right inside either delimiter is in the formula.
        ("<div>$$|\\frac{1}{2}$$</div>", MARKDOWN, "\\frac{1}{2}", "block"),
        ("<div>$$\\frac{1}{2}|$$</div>", MARKDOWN, "\\frac{1}{2}", "block"),
        # A formula over several lines of the editor.
        ("<div>$$\\begin{pmatrix} a \\\\</div><div>b| \\end{pmatrix}$$</div>", MARKDOWN,
         "\\begin{pmatrix} a \\\\\nb \\end{pmatrix}", "block"),
        # An @LaTeX note with no delimiters is one formula, the whole note.
        ("<div>x^2 + |y^2 = z^2</div>", LATEX, "x^2 + y^2 = z^2", "block"),
        # With delimiters, only the formula the caret is in.
        ("<div>Area $A = \\pi r^|2$ and $C = 2\\pi r$.</div>", LATEX, "A = \\pi r^2", "inline"),
        ("<div>Area $A = \\pi r^2$ and $C = 2\\pi| r$.</div>", LATEX, "C = 2\\pi r", "inline"),
        ("<div>The ratio (((\\frac{1 + \\sqrt|{5}}{2}))) or so</div>", "(((@LaTeX)))", "\\frac{1 + \\sqrt{5}}{2}", "block"),
    ],
)
def test_the_formula_under_the_caret_is_drawn_as_the_note_draws_it(content_html: str, tags: str, source: str, display: str) -> None:
    preview = _preview(content_html, tags)

    assert preview.kind == PREVIEW_LATEX
    assert preview.error == ""
    assert preview.has_unknown_command is False
    assert preview.html == _drawn(source, display)


@pytest.mark.parametrize(
    ("content_html", "tags"),
    [
        # Outside the delimiters, or on one.
        ("<div>A half: |$$\\frac{1}{2}$$ done</div>", MARKDOWN),
        ("<div>A half: $$\\frac{1}{2}$$| done</div>", MARKDOWN),
        ("<div>A half: $|$\\frac{1}{2}$$ done</div>", MARKDOWN),
        ("<div>A half: $$\\frac{1}{2}$|$ done</div>", MARKDOWN),
        ("<div>\\|(a^2\\)</div>", MARKDOWN),
        ("<div>Area |$A = \\pi r^2$ and $C$.</div>", LATEX),
        ("<div>Area $A = \\pi r^2$ an|d $C$.</div>", LATEX),
        ("<div>See (((\\sqrt{2}))) |here</div>", "(((@LaTeX)))"),
        # Only the opening delimiter: no region.
        ("<div>only $$\\frac|{1}{2}</div>", MARKDOWN),
        # Not a formula to the renderer: dollars, code, a note that is not Markdown or LaTeX.
        ("<div>costs $5 and |$6</div>", MARKDOWN),
        ("<div>costs $5 and $|6</div>", MARKDOWN),
        ("<div>`$a^|2$`</div>", MARKDOWN),
        ("<div>$$\\frac{1}{|2}$$</div>", ""),
        ("<div>$$\\frac{1}{|2}$$</div>", "@red"),
        # Drawn, it would look as typed.
        ("<div>Plain $$x|$$ here</div>", MARKDOWN),
        ("<div>Plain $$12|$$ here</div>", MARKDOWN),
        ("<div>x + |y = z</div>", LATEX),
    ],
)
def test_nothing_is_previewed_outside_a_formula_or_for_one_that_looks_as_typed(content_html: str, tags: str) -> None:
    preview = _preview(content_html, tags)

    assert preview.kind == PREVIEW_NONE
    assert (preview.html, preview.error, preview.has_unknown_command) == ("", "", False)


def test_a_broken_formula_says_so_as_its_badge_does() -> None:
    preview = _preview("<div>$$\\frac{1}{2}^|$$</div>", MARKDOWN)

    assert (preview.kind, preview.html, preview.error) == (PREVIEW_LATEX, "", "Invalid LaTeX")
    assert render_latex_to_html("$$\\frac{1}{2}^$$").has_error


def test_a_command_not_finished_is_drawn_as_typed_and_marked() -> None:
    preview = _preview("<div>$$\\frac{1}{2} + \\fra|$$</div>", MARKDOWN)

    assert preview.kind == PREVIEW_LATEX
    assert preview.error == ""
    assert preview.html == _drawn("\\frac{1}{2} + \\fra", "block")
    assert "<mi>\\fra</mi>" in preview.html
    assert preview.has_unknown_command is True


def test_a_broken_formula_before_the_caret_does_not_hide_the_one_under_it() -> None:
    preview = _preview("<div>Area $A = r^$ and $C = 2\\pi| r$.</div>", LATEX)

    assert preview.kind == PREVIEW_LATEX
    assert preview.html == _drawn("C = 2\\pi r", "inline")


@pytest.mark.parametrize("marks", [0, 2])
def test_the_content_must_hold_the_caret_mark_once(marks: int) -> None:
    with pytest.raises(ValueError, match="exactly once"):
        edit_preview_at_caret(marked_content_html="<div>$$a^2$$</div>" + CARET_MARK * marks, tags=MARKDOWN)


def test_a_preview_fetches_no_link_title_or_icon(monkeypatch: pytest.MonkeyPatch) -> None:
    fetched: list[str] = []
    monkeypatch.setattr(content_formatting_module.link_title_store, "maybe_enqueue_fetch", fetched.append)
    monkeypatch.setattr(content_formatting_module.link_icon_store, "maybe_enqueue_fetch", fetched.append)
    content_html = "<div>https://half-typed.example.org/pa</div><div>$$a^|2$$</div>"

    assert _preview(content_html, MARKDOWN).kind == PREVIEW_LATEX
    assert _preview(content_html, "").kind == PREVIEW_NONE
    assert fetched == []
    # Showing the note itself still asks for the link's title.
    format_note_content_for_view(content_html=content_html.replace("|", ""), tags="", redact_credentials=True)
    assert fetched == ["https://half-typed.example.org/pa"]


def test_finding_formulas_lists_them_in_order_without_drawing_them() -> None:
    with finding_formulas() as found:
        rendered = render_latex_to_html("Text $a^$ then $$\\frac{1}{2}$$")

    assert found == [FoundFormula(source="a^", display="inline"), FoundFormula(source="\\frac{1}{2}", display="block")]
    assert rendered.has_error is False
    assert "<math" not in rendered.html
    with pytest.raises(AssertionError, match="does not nest"):
        with finding_formulas(), finding_formulas():
            pass
    assert "<math" in render_latex_to_html("$$\\frac{1}{2}$$").html


def test_http_route_answers_with_the_preview(tmp_path: Path) -> None:
    script = '''
from fastapi.testclient import TestClient
from app.main import app
from app.config import API_PREFIX
from app.services.edit_previews import CARET_MARK
from app.security.rendered_html import sanitize_rendered_html
from app.services.latex_rendering import render_latex_math_to_html
from app.services.tokens import token_service

token = token_service.create_token(client_info="fixture", owner_tab_id="tab", dek=None)
headers = {"Authorization": "Bearer " + token, "X-Metalist-Tab-Id": "tab", "Origin": "http://localhost"}
path = API_PREFIX + "/notes/edit-preview"
with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
    answer = client.post(path, headers=headers, json={
        "marked_content_html": "<div>$$\\\\frac{1}{" + CARET_MARK + "2}$$</div>", "tags_text": "@markdown",
    })
    assert answer.status_code == 200, answer.text
    assert answer.json() == {
        "kind": "latex", "html": sanitize_rendered_html(render_latex_math_to_html("\\\\frac{1}{2}", display="block").html),
        "error": "", "hasUnknownCommand": False, "caretRow": -1, "diagramSource": "",
    }, answer.json()
    outside = client.post(path, headers=headers, json={"marked_content_html": "<div>" + CARET_MARK + "$$x^2$$</div>", "tags_text": "@markdown"})
    assert outside.json() == {"kind": "none", "html": "", "error": "", "hasUnknownCommand": False, "caretRow": -1, "diagramSource": ""}, outside.json()
    missing = client.post(path, headers=headers, json={"marked_content_html": "<div>$$x^2$$</div>"})
    assert missing.status_code == 422, missing.text
    unauthenticated = client.post(path, headers={"Origin": "http://localhost"}, json={"marked_content_html": CARET_MARK, "tags_text": ""})
    assert unauthenticated.status_code == 401, unauthenticated.text
print("ROUTE OK")
'''
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run([sys.executable, "-c", script], env=environment, capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, (result.stdout[-2000:], result.stderr[-3000:])
    assert "ROUTE OK" in result.stdout


PEOPLE = ['Name,Role,City', 'Ada,Analyst,London', '"Smith, John",Engineer,"Portland, OR"', 'Linus,Maintainer,Portland']


def _lines(lines: list[str]) -> str:
    return "".join(f"<div>{line}</div>" for line in lines)


# The table as the note draws it.
def _note_shows(content_html: str, tags: str) -> str:
    return format_note_content_for_view(content_html=content_html.replace("|", ""), tags=tags, redact_credentials=True)


@pytest.mark.parametrize(
    ("lines", "row"),
    [
        (["Na|me,Role,City", *PEOPLE[1:]], 0),
        ([PEOPLE[0], "Ada,Ana|lyst,London", *PEOPLE[2:]], 1),
        ([*PEOPLE[:2], '"Smith,| John",Engineer,"Portland, OR"', PEOPLE[3]], 2),
        # On an empty line after the table: no row of it.
        ([*PEOPLE, "|"], NOT_FOUND),
    ],
)
def test_the_whole_csv_note_is_its_table_with_the_caret_row(lines: list[str], row: int) -> None:
    content_html = _lines(lines)
    preview = _preview(content_html, "@csv")

    assert preview.kind == PREVIEW_CSV
    assert preview.error == ""
    assert preview.caret_row == row
    assert preview.html != "" and preview.html in _note_shows(content_html, "@csv")


def test_a_csv_region_previews_only_inside_it_as_the_note_shows_it() -> None:
    content_html = "<div>Groceries ((Item,Qty</div><div>Mi|lk,2)) and $$E = mc^2$$ here.</div>"
    tags = "@markdown ((@csv))"

    inside = _preview(content_html, tags)
    assert (inside.kind, inside.caret_row) == (PREVIEW_CSV, 1)
    assert inside.html in _note_shows(content_html, tags)
    assert _preview(content_html.replace("|", "").replace("Groceries", "Groc|eries"), tags).kind == PREVIEW_NONE
    assert _preview(content_html.replace("|", "").replace("((Item", "(|(Item"), tags).kind == PREVIEW_NONE
    formula = _preview(content_html.replace("|", "").replace("mc^2", "mc^|2"), tags)
    assert formula.kind == PREVIEW_LATEX


def test_one_column_shows_nothing() -> None:
    assert _preview("<div>Milk</div><div>Eg|gs</div>", "@csv").kind == PREVIEW_NONE


def test_a_broken_table_says_why_as_its_badge_does() -> None:
    preview = _preview(_lines(["Item,Qty", "Milk,2,ex|tra"]), "@csv")

    assert (preview.kind, preview.html, preview.caret_row) == (PREVIEW_CSV, "", NOT_FOUND)
    assert preview.error == "Invalid CSV: Row 2 has 3 columns, expected 2"


FENCE = ["Release steps:", "```mermaid", "flowchart LR", "A[Write] --> B[Review]", "```", "Done."]


@pytest.mark.parametrize(
    ("lines", "tags", "source"),
    [
        ([*FENCE[:3], "A[Wr|ite] --> B[Review]", *FENCE[4:]], MARKDOWN, "flowchart LR\nA[Write] --> B[Review]"),
        (["flowchart TD", "A --> |B"], "@mermaid", "flowchart TD\nA --> B"),
        (["See ((flowchart LR", "A --> B|)) here"], "((@mermaid))", "flowchart LR\nA --> B"),
    ],
)
def test_a_diagram_under_the_caret_comes_with_its_source_for_the_browser_to_draw(lines: list[str], tags: str, source: str) -> None:
    preview = _preview(_lines(lines), tags)

    assert (preview.kind, preview.html, preview.error, preview.diagram_source) == (PREVIEW_MERMAID, "", "", source)


@pytest.mark.parametrize(
    ("lines", "tags"),
    [
        # On the fence's lines, before or after it.
        ([FENCE[0], "```mer|maid", *FENCE[2:]], MARKDOWN),
        ([*FENCE[:4], "``|`", FENCE[5]], MARKDOWN),
        (["Release| steps:", *FENCE[1:]], MARKDOWN),
        # A fence without its closing ``` is still being written.
        ([*FENCE[:3], "A[Write] --> |B[Review]"], MARKDOWN),
        (["See| ((flowchart LR", "A --> B)) here"], "((@mermaid))"),
        # Fenced, but no diagram in it.
        ([FENCE[0], "```mermaid", "|", "```"], MARKDOWN),
    ],
)
def test_no_diagram_outside_one_or_in_an_open_fence(lines: list[str], tags: str) -> None:
    assert _preview(_lines(lines), tags).kind == PREVIEW_NONE


def test_compact_json_shows_as_the_note_draws_it() -> None:
    content_html = _lines(['{"name": "MetaList", "tags": ["no|tes"], "port": 8443}'])
    preview = _preview(content_html, "@json")

    assert (preview.kind, preview.error) == (PREVIEW_JSON, "")
    assert preview.html != "" and preview.html in _note_shows(content_html, "@json")
    region = _preview(_lines(['Settings ((({"debug": true,| "port": 8080}))) saved']), "@markdown (((@json)))")
    assert region.kind == PREVIEW_JSON
    assert region.html in _note_shows(_lines(['Settings ((({"debug": true, "port": 8080}))) saved']), "@markdown (((@json)))")


def test_json_laid_out_as_the_note_draws_it_shows_nothing() -> None:
    assert _preview(_lines(["{", '  "a": 1,|', '  "b": 2', "}"]), "@json").kind == PREVIEW_NONE
    # Laid out another way (four spaces), it shows.
    assert _preview(_lines(["{", '    "a": 1|', "}"]), "@json").kind == PREVIEW_JSON


def test_broken_json_says_why_and_where() -> None:
    preview = _preview(_lines(['{"a": 1 "b|": 2}']), "@json")

    assert (preview.kind, preview.html) == (PREVIEW_JSON, "")
    assert preview.error == "Invalid JSON: Expecting ',' delimiter: line 1 column 9 (char 8)"
    assert _preview(_lines(['Settings| ((({"debug": true}))) saved']), "@markdown (((@json)))").kind == PREVIEW_NONE
