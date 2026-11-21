"""A @gallery note inside an embed (the maintainer, 2026-11-19: "galleries don't show up in
embeddings"; it showed its children as an outline, never the grid). An embed is a window onto its
source, drawn as the list draws it (docs/ui/references.md): the grid under its text, one row when
folded, and every picture whatever the search, as the embed shows every child."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List

import pytest

import app.services.embedded_references as embedded_references
from app.services.credential_display import CredentialDisplay
from app.services.embedded_references import EmbedRenderContext, render_note_content_with_embeds

REPORT = "b0000000-0000-4000-8000-000000000001"
HOLIDAY = "b0000000-0000-4000-8000-000000000002"
DAY_ONE = "b0000000-0000-4000-8000-000000000003"
DAY_TWO = "b0000000-0000-4000-8000-000000000004"
PLAN = "b0000000-0000-4000-8000-000000000005"
ROUTE = "b0000000-0000-4000-8000-000000000006"
MARKDOWN = b"# Route\n\nLisbon, then Porto.\n"
TILE = 'class="note-file-reference-link meta-gallery-tile"'
EMBEDDED_GALLERY = "note-embed-gallery"
FIRST_LINE = '<div class="note-embed-gallery-first-line">'


@dataclass(frozen=True)
class _Note:
    content: str
    tags: str
    is_collapsed: bool


def _record(file_id: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id, title=name, original_filename=name, mime_type="text/markdown", size_bytes=len(MARKDOWN),
        thumbnail_kind="file", first_page_revision=0,
    )


RECORDS = {PLAN: _record(PLAN, "plan.md"), ROUTE: _record(ROUTE, "route.md")}
CHILDREN: Dict[str, List[str]] = {HOLIDAY: [DAY_ONE, DAY_TWO]}


def _notes(*, holiday_tags: str, is_holiday_folded: bool) -> Dict[str, _Note]:
    """Trip report embeds Holiday pictures, whose two child notes hold a Markdown file each."""
    return {
        REPORT: _Note(f"<div>Trip report</div><div>![[{HOLIDAY}]]</div><div>and text after</div>", "", False),
        HOLIDAY: _Note("<div>Holiday pictures</div><div>more about them</div>", holiday_tags, is_holiday_folded),
        DAY_ONE: _Note(f"<div>Day one</div><div>![[{PLAN}]]</div>", "", False),
        DAY_TWO: _Note(f"<div>Day two</div><div>![[{ROUTE}]]</div>", "", False),
    }


def _context(notes: Dict[str, _Note], *, is_search_hiding_the_days: bool) -> EmbedRenderContext:
    return EmbedRenderContext(
        has_note=lambda note_id: note_id in notes, get_note=lambda note_id: notes[note_id],
        get_children=lambda parent_id: CHILDREN.get(parent_id, []), has_file=lambda file_id: file_id in RECORDS,
        get_file=lambda file_id: RECORDS[file_id], is_property_used=lambda name: False,
        is_shown_in_gallery=lambda gallery_note_id, note_id: not (is_search_hiding_the_days and note_id in (DAY_ONE, DAY_TWO)),
        static_collapse_arrows=False,
    )


def _render(
    monkeypatch: pytest.MonkeyPatch, note_id: str, *, holiday_tags: str, is_holiday_folded: bool, is_search_hiding_the_days: bool,
) -> str:
    notes = _notes(holiday_tags=holiday_tags, is_holiday_folded=is_holiday_folded)
    monkeypatch.setattr(
        embedded_references.file_registry, "read_stored_file",
        lambda file_id: SimpleNamespace(record=RECORDS[file_id], content_bytes=MARKDOWN),
    )
    return render_note_content_with_embeds(
        note_id=note_id, content_html=notes[note_id].content, tags=notes[note_id].tags,
        context=_context(notes, is_search_hiding_the_days=is_search_hiding_the_days),
        static_export=False, credentials=CredentialDisplay.HIDDEN,
    )


def test_an_open_embedded_gallery_shows_its_grid_and_keeps_its_children_for_the_outline(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _render(monkeypatch, REPORT, holiday_tags="@gallery=markdown", is_holiday_folded=False, is_search_hiding_the_days=False)
    assert f'note-embed-node note-embed-root {EMBEDDED_GALLERY}"' in report
    assert report.count('<section class="meta-gallery"') == 1
    assert report.count(TILE) == len(RECORDS)
    # The switch and the children are drawn too: the outline is one click away (main.css hides one).
    assert report.count('class="meta-gallery-switch"') == 1
    assert 'class="note-embed-children"' in report
    # The grid is the embedded note's own, right under its text.
    assert report.index("more about them") < report.index('<section class="meta-gallery"') < report.index('class="note-embed-children"')


def test_a_folded_embedded_gallery_shows_its_first_line_and_its_row_of_pictures(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _render(monkeypatch, REPORT, holiday_tags="@gallery=markdown", is_holiday_folded=True, is_search_hiding_the_days=False)
    assert f"{EMBEDDED_GALLERY} note-embed-collapsed" in report
    assert report.count(TILE) == len(RECORDS)
    # The line alone is cut to one line, so the row under it shows (main.css).
    assert report.index(FIRST_LINE) < report.index("Holiday pictures") < report.index('<section class="meta-gallery"')
    assert "more about them" not in report
    assert 'class="note-embed-children"' not in report


def test_a_search_narrows_the_list_gallery_but_never_an_embedded_one(monkeypatch: pytest.MonkeyPatch) -> None:
    # The search shows Trip report and Holiday pictures, and neither day.
    in_list = _render(monkeypatch, HOLIDAY, holiday_tags="@gallery=markdown", is_holiday_folded=False, is_search_hiding_the_days=True)
    assert TILE not in in_list
    embedded = _render(monkeypatch, REPORT, holiday_tags="@gallery=markdown", is_holiday_folded=False, is_search_hiding_the_days=True)
    assert embedded.count(TILE) == len(RECORDS)
    folded = _render(monkeypatch, REPORT, holiday_tags="@gallery=markdown", is_holiday_folded=True, is_search_hiding_the_days=True)
    assert folded.count(TILE) == len(RECORDS)


@pytest.mark.parametrize("holiday_tags", ["", "@gallery=pdf"])
def test_an_embedded_note_with_no_gallery_to_show_is_drawn_as_before(monkeypatch: pytest.MonkeyPatch, holiday_tags: str) -> None:
    # No @gallery, or a gallery of PDFs where there are none: the outline, and nothing hidden.
    for is_folded in (False, True):
        report = _render(monkeypatch, REPORT, holiday_tags=holiday_tags, is_holiday_folded=is_folded, is_search_hiding_the_days=False)
        assert EMBEDDED_GALLERY not in report
        assert "meta-gallery" not in report
    open_report = _render(monkeypatch, REPORT, holiday_tags=holiday_tags, is_holiday_folded=False, is_search_hiding_the_days=False)
    assert 'class="note-embed-children"' in open_report
