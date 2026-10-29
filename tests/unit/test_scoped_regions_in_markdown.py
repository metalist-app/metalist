"""A scoped region in a Markdown note is drawn as in any other note (docs/ui/content-formatting.md,
"Markdown meta tags"). Fixed 2026-10-29: only `(((@LaTeX)))` survived the Markdown pass; a
`((@csv))` table showed as run-together text, `((@diff))` as a bullet list."""

from __future__ import annotations

import pytest

from app.security.rendered_html import sanitize_rendered_html
from app.services.content_formatting import format_note_content_for_view

BEFORE = "<div>Before "
AFTER = " after</div>"
CHESS_START = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

BLOCK_REGIONS = [
    ("((@csv))", "((a,b</div><div>1,2))"),
    ("((@json))", '(({"a": 1}))'),
    ("((@diff))", "((- old</div><div>+ new))"),
    ("((@code=python))", "((x = 1))"),
    ("((@mermaid))", "((flowchart TD</div><div>A --&gt; B))"),
    ("((@shell))", "((ls -la))"),
    ("((@markdown))", "((**bold**))"),
]
INLINE_REGIONS = [
    ("((@chess))", f"(({CHESS_START}))"),
    ("(((@LaTeX)))", "(((\\frac{1}{2})))"),
]


# The region as a note without @markdown draws it, between "Before " and " after".
def _drawn_alone(tag: str, body: str) -> str:
    plain = format_note_content_for_view(content_html=f"{BEFORE}{body}{AFTER}", tags=tag, redact_credentials=False)
    assert plain.startswith(BEFORE) and plain.endswith(AFTER), plain
    return plain[len(BEFORE):-len(AFTER)]


def _drawn_in_markdown(tag: str, body: str) -> str:
    return format_note_content_for_view(content_html=f"{BEFORE}{body}{AFTER}", tags=f"@markdown {tag}", redact_credentials=False)


@pytest.mark.parametrize(("tag", "body"), BLOCK_REGIONS)
def test_a_block_region_stands_between_the_paragraphs_around_it(tag: str, body: str) -> None:
    region = _drawn_alone(tag, body)
    rendered = _drawn_in_markdown(tag, body)

    assert f"<p>Before </p>{region}<p> after</p>" in rendered, rendered
    # Nothing for the sanitizer to move: a block never sits inside a paragraph.
    assert sanitize_rendered_html(rendered) == rendered


@pytest.mark.parametrize(("tag", "body"), INLINE_REGIONS)
def test_an_inline_region_stays_in_its_paragraph(tag: str, body: str) -> None:
    region = _drawn_alone(tag, body)
    rendered = _drawn_in_markdown(tag, body)

    assert f"<p>Before {region} after</p>" in rendered, rendered


def test_markdown_around_a_region_still_renders() -> None:
    rendered = format_note_content_for_view(
        content_html="<div># Groceries</div><div>This **week** ((Item,Qty</div><div>Milk,2)) and `code`.</div>",
        tags="@markdown ((@csv))", redact_credentials=False,
    )
    region = _drawn_alone("((@csv))", "((Item,Qty</div><div>Milk,2))")

    assert "<h1>Groceries</h1>" in rendered, rendered
    assert f"<p>This <strong>week</strong> </p>{region}<p> and <code>code</code>.</p>" in rendered, rendered
