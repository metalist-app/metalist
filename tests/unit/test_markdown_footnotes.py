"""Markdown footnotes (2026-10-31; docs/ui/content-formatting.md, Markdown footnotes): in an
@markdown note, [^label] with [^label]: text on a line of its own, and ^[inline text], are
MetaList's own footnotes, numbered by first appearance and listed under References."""

from __future__ import annotations

import re

import pytest

from app.services.credential_display import CredentialDisplay
from app.services.content_formatting import format_note_content_for_view
from app.services.embedded_references import EmbedRenderContext, render_collapsed_note_content_with_embeds
from app.services.markdown_rendering import markdown_task_lines, render_markdown_to_html, render_note_markdown

NOTE_ID = "11111111-1111-4111-8111-111111111111"
LISBON = [
    "Ferry times[^ferry] changed, and the museum[^museum] is closed on Mondays.",
    "The museum[^museum] again. Dinner^[booked by **phone**].",
    "- [ ] Buy tickets[^ferry]",
    "- [x] Check hours",
    "[^ferry]: Every 20 minutes, see [the timetable](https://example.com/ferry).",
    "[^museum]: Open 10:00 to 18:00.",
    "    Free on the first Sunday.",
    "[^unused]: Never referenced.",
]


def render(lines: list[str], tags: str) -> str:
    content = "".join(f"<div>{line}</div>" for line in lines)
    return format_note_content_for_view(content_html=content, tags=tags, credentials=CredentialDisplay.DOTS)


def markers(rendered: str) -> list[str]:
    return re.findall(r'data-footnote-number="(\d+)"', rendered.split("<section", 1)[0])


def references(rendered: str) -> list[str]:
    section = rendered.split("<section", 1)[1]
    return [" ".join(re.sub(r"<[^>]+>", " ", body).split())
            for body in re.findall(r'<div class="meta-footnote-body">(.*?)</div></li>', section, re.S)]


def test_footnotes_are_numbered_by_first_appearance_and_listed() -> None:
    rendered = render(LISBON, "@markdown")
    # A footnote referenced again keeps its number and its one row.
    assert markers(rendered) == ["1", "2", "2", "3", "1"]
    assert references(rendered) == [
        "Every 20 minutes, see the timetable · example.com .",
        "Open 10:00 to 18:00. Free on the first Sunday.",
        "booked by phone",
    ]
    assert 'href="https://example.com/ferry"' in rendered
    assert "<strong>phone</strong>" in rendered
    assert "[^" not in rendered and "^[" not in rendered
    assert "Never referenced" not in rendered


def test_a_definition_line_leaves_the_task_lines_as_they_were() -> None:
    markdown = "\n".join(LISBON)
    assert markdown_task_lines(markdown) == [2, 3]
    note = render_note_markdown(markdown, takes_footnotes=True)
    assert re.findall(r'data-task-index="(\d+)"', note.html) == ["0", "1"]


@pytest.mark.parametrize("markdown", [
    "No definition[^nope].",
    "In code `see [^1]`\n\n[^1]: text",
    "```\nsee [^1]\n[^1]: in a fence\n```",
])
def test_what_is_not_a_footnote_stays_as_written(markdown: str) -> None:
    note = render_note_markdown(markdown, takes_footnotes=True)
    assert note.footnotes == []
    assert "[^" in note.html


def test_labels_ignore_case_and_the_first_definition_counts() -> None:
    note = render_note_markdown("A[^Source] b[^source]\n\n[^SOURCE]: first\n[^source]: second", takes_footnotes=True)
    assert [body for _token, body in note.footnotes] == ["first", "first"]


def test_footnote_text_holds_no_footnotes_of_its_own() -> None:
    note = render_note_markdown("A[^1]\n\n[^1]: see ^[nested]", takes_footnotes=True)
    assert [body for _token, body in note.footnotes] == ["see ^[nested]"]


def test_the_ai_chat_and_a_markdown_region_leave_footnotes_as_written() -> None:
    assert render_markdown_to_html("A[^1]\n\n[^1]: text") == "<p>A[^1]</p><p>[^1]: text</p>"
    rendered = render(["x ((r[^1]))", "[^1]: md"], "((@markdown))")
    assert "r[^1]" in rendered
    assert "meta-footnote" not in rendered


def test_scoped_and_markdown_footnotes_share_one_list() -> None:
    rendered = render(["a{{scoped}} b[^1]", "[^1]: md"], "@markdown {{@footnote}}")
    assert markers(rendered) == ["1", "2"]
    assert references(rendered) == ["scoped", "md"]


def test_a_folded_note_shows_the_numbers_of_its_first_line() -> None:
    context = EmbedRenderContext(
        has_note=lambda note_id: False, get_note=lambda note_id: None, get_children=lambda parent_id: [],
        has_file=lambda file_id: False, get_file=lambda file_id: None,
        is_property_used=lambda property_name: False, static_collapse_arrows=False,
    )
    rendered = render_collapsed_note_content_with_embeds(
        note_id=NOTE_ID, content_html="".join(f"<div>{line}</div>" for line in LISBON), tags="@markdown",
        context=context, static_export=False, credentials=CredentialDisplay.DOTS,
    )
    assert markers(rendered)[:2] == ["1", "2"]
    assert "[^ferry]" not in rendered
