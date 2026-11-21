"""A file with no picture of its own, in a gallery (the maintainer, 2026-11-18): with
`@gallery=markdown` each Markdown file's card, which holds Open and Download buttons inside the
tile's own button, came apart into three tiles. A Markdown, text, code or data file is now one
tile showing the top of the file as the viewer draws it; any other file, its badge and name."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import app.services.embedded_references as embedded_references
from app.services.credential_display import CredentialDisplay
from app.services.embedded_references import EmbedRenderContext, render_note_content_with_embeds

PLAN = "a0000000-0000-4000-8000-000000000001"
ARCHIVE = "a0000000-0000-4000-8000-000000000002"
MARKDOWN = b"# Centuries of Steel\n\nA game about **medieval** battles.\n\n- one\n- two\n"


@dataclass(frozen=True)
class _Note:
    content: str
    tags: str


def _record(file_id: str, name: str, mime_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=file_id, title=name, original_filename=name, mime_type=mime_type, size_bytes=len(MARKDOWN),
        thumbnail_kind="file", first_page_revision=0,
    )


RECORDS = {
    PLAN: _record(PLAN, "plan.md", "text/markdown"),
    ARCHIVE: _record(ARCHIVE, "pack.zip", "application/zip"),
}


def _gallery(monkeypatch: pytest.MonkeyPatch, *, is_export: bool) -> str:
    notes = {"trip": _Note(f"<div>Game idea</div><div>![[{PLAN}]]</div><div>![[{ARCHIVE}]]</div>", "@gallery=markdown,.zip")}
    monkeypatch.setattr(
        embedded_references.file_registry, "read_stored_file",
        lambda file_id: SimpleNamespace(record=RECORDS[file_id], content_bytes=MARKDOWN),
    )
    return render_note_content_with_embeds(
        note_id="trip", content_html=notes["trip"].content, tags=notes["trip"].tags,
        context=EmbedRenderContext(
            has_note=lambda note_id: note_id in notes, get_note=lambda note_id: notes[note_id],
            get_children=lambda parent_id: [], has_file=lambda file_id: file_id in RECORDS,
            get_file=lambda file_id: RECORDS[file_id], is_property_used=lambda name: False,
            is_shown_in_gallery=lambda gallery_note_id, note_id: True, static_collapse_arrows=False,
        ),
        static_export=is_export, credentials=CredentialDisplay.HIDDEN,
    )


def _grid(rendered: str) -> str:
    return rendered[rendered.index('<section class="meta-gallery"'):]


def test_each_file_is_one_tile_with_no_button_inside_it(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = _grid(_gallery(monkeypatch, is_export=False))

    assert grid.count('class="note-file-reference-link meta-gallery-tile"') == 2
    # The switch and the two tiles: a button inside a tile would end the tile there.
    assert grid.count("<button") == 3


def test_a_markdown_file_shows_the_top_of_the_file_drawn(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = _grid(_gallery(monkeypatch, is_export=False))

    document = grid[grid.index('<span class="meta-gallery-document"'):]
    assert "<h1" in document and "Centuries of Steel" in document
    assert "<strong>medieval</strong>" in document
    assert "# Centuries" not in document, "drawn, not its source"


def test_a_file_that_cannot_be_drawn_shows_its_badge_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = _grid(_gallery(monkeypatch, is_export=False))

    assert '<span class="meta-gallery-file-name">pack.zip</span>' in grid
    assert ".ZIP" in grid


def test_an_export_shows_each_by_its_badge_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    grid = _grid(_gallery(monkeypatch, is_export=True))

    assert '<span class="meta-gallery-file-name">plan.md</span>' in grid
    assert "meta-gallery-document" not in grid
    assert grid.count("<button") == 3
