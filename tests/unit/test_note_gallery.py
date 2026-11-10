"""@gallery: the pictures in a note and every note under it (docs/future-plans/gallery.md)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pytest

from app.services.content_formatting import is_known_meta_tag_term, list_known_meta_tag_terms
from app.services.embedded_references import collect_active_reference_tokens, extract_collapsed_preview_source_html
from app.security.rendered_html import sanitize_rendered_html
from app.services.note_gallery import GalleryItem, collect_gallery_items, gallery_kinds, render_gallery

PHOTO_A, PHOTO_B, DRAWING, MANUAL = (f"{index:08d}-0000-4000-8000-000000000000" for index in range(1, 5))


@dataclass(frozen=True)
class _Note:
    content: str
    tags: str


@dataclass(frozen=True)
class _File:
    original_filename: str
    thumbnail_kind: str


@dataclass
class _Tree:
    notes: Dict[str, _Note]
    children: Dict[Optional[str], List[str]]
    files: Dict[str, _File]

    def has_file(self, file_id: str) -> bool:
        return file_id in self.files

    def get_file(self, file_id: str) -> _File:
        return self.files[file_id]

    def get_note(self, note_id: str) -> _Note:
        return self.notes[note_id]

    def get_children(self, note_id: Optional[str]) -> List[str]:
        return self.children.get(note_id, [])


def _items(tree: _Tree, note_id: str, tags: str) -> list[tuple[str, str, str]]:
    kinds = gallery_kinds(tags)
    assert kinds is not None
    items = collect_gallery_items(
        note_id=note_id, kinds=kinds, context=tree,
        file_ids_in=lambda content_html: [(token.start, token.note_id) for token in collect_active_reference_tokens(content_html)],
        first_line_of=extract_collapsed_preview_source_html,
    )
    return [(item.file_id, item.note_id, item.caption) for item in items]


def _trip() -> _Tree:
    """trip (@gallery) → day-1 (Beach at dusk, a photo) → day-1-more (the photo again, a drawing);
    trip → day-2 (only a photo); trip → manual (a PDF)."""
    return _Tree(
        notes={
            "trip": _Note("<div>Lisbon trip</div>", "@gallery"),
            "day-1": _Note(f"<div>Beach at dusk</div><div>![[{PHOTO_A}]]</div>", ""),
            "day-1-more": _Note(f"<div>![[{PHOTO_A}]] and ![[{DRAWING}]]</div>", ""),
            "day-2": _Note(f"<div>![[{PHOTO_B}]]</div>", ""),
            "manual": _Note(f"<div>Tram manual ![[{MANUAL}]]</div>", ""),
        },
        children={"trip": ["day-1", "day-2", "manual"], "day-1": ["day-1-more"]},
        files={
            PHOTO_A: _File("beach.jpg", "image"), PHOTO_B: _File("IMG_4031.jpg", "image"),
            DRAWING: _File("map.excalidraw", "excalidraw"), MANUAL: _File("manual.pdf", "pdf"),
        },
    )


def test_it_is_a_known_built_in_tag_with_or_without_kinds() -> None:
    assert "@gallery" in list_known_meta_tag_terms()
    for term in ("@gallery", "@Gallery", "@gallery=image", "@gallery=image,pdf", "@gallery=.png"):
        assert is_known_meta_tag_term(term), term
    assert not is_known_meta_tag_term("@galleries")


@pytest.mark.parametrize(
    ("tags", "kinds"),
    [("@gallery", ()), ("trip @gallery=image,PDF", ("image", "pdf")), ("trip", None), ("my@gallery", None)],
)
def test_the_tag_names_the_kinds(tags: str, kinds) -> None:
    assert gallery_kinds(tags) == kinds


def test_pictures_come_in_outline_order_each_once_with_their_note_first_line() -> None:
    assert _items(_trip(), "trip", "@gallery") == [
        (PHOTO_A, "day-1", "Beach at dusk"),
        (DRAWING, "day-1-more", "and"),
        (PHOTO_B, "day-2", ""),
    ]


def test_a_kind_narrows_it_and_names_files_as_notes_with_files_does() -> None:
    assert [item[0] for item in _items(_trip(), "trip", "@gallery=image")] == [PHOTO_A, PHOTO_B]
    assert [item[0] for item in _items(_trip(), "trip", "@gallery=pdf")] == [MANUAL]
    assert [item[0] for item in _items(_trip(), "trip", "@gallery=pdf,.excalidraw")] == [DRAWING, MANUAL]


def test_an_embedded_note_adds_nothing() -> None:
    tree = _trip()
    tree.notes["trip"] = _Note("<div>Lisbon trip ![[day-2]]</div>", "@gallery")
    tree.children["trip"] = ["day-1"]
    assert [item[0] for item in _items(tree, "trip", "@gallery")] == [PHOTO_A, DRAWING]


def _pictures(tree: _Tree, note_id: str, tags: str) -> list[tuple[str, str]]:
    """Each picture as (what it is, its note): a file's id, or an inline picture's address."""
    kinds = gallery_kinds(tags)
    assert kinds is not None
    items = collect_gallery_items(
        note_id=note_id, kinds=kinds, context=tree,
        file_ids_in=lambda content_html: [(token.start, token.note_id) for token in collect_active_reference_tokens(content_html)],
        first_line_of=extract_collapsed_preview_source_html,
    )
    return [(item.file_id or item.image_source, item.note_id) for item in items]


def test_pictures_written_in_the_text_count_too_in_the_order_written() -> None:
    """Pictures pasted into a note live in its text: an <img>, or ![...](...) in a Markdown note
    (2026-11-10: a gallery over such notes showed nothing)."""
    tree = _Tree(
        notes={
            "album": _Note("<div>Album</div>", "@gallery"),
            "pasted": _Note('<div>Dinner</div><div><img src="https://example.com/a.jpg"></div>'
                            f'<div>![[{PHOTO_B}]]</div><div><img src="data:image/png;base64,AAAA"></div>', ""),
            "markdown": _Note("<div>Hike</div><div>![summit](https://example.com/summit.png)</div>", "@markdown"),
            "plain": _Note("<div>![not markdown](https://example.com/x.png)</div>", ""),
        },
        children={"album": ["pasted", "markdown", "plain"]},
        files={PHOTO_B: _File("IMG_4031.jpg", "image")},
    )
    assert _pictures(tree, "album", "@gallery") == [
        ("https://example.com/a.jpg", "pasted"), (PHOTO_B, "pasted"), ("data:image/png;base64,AAAA", "pasted"),
        ("https://example.com/summit.png", "markdown"),
    ]
    assert _pictures(tree, "album", "@gallery=pdf") == []


def test_a_gallery_with_nothing_to_show_draws_nothing() -> None:
    tree = _Tree(notes={"album": _Note("<div>Album</div>", "@gallery"), "text": _Note("<div>Just words</div>", "")},
                 children={"album": ["text"]}, files={})
    assert _pictures(tree, "album", "@gallery") == []


def test_the_note_of_each_picture_survives_sanitizing() -> None:
    """Go to note reads it from the tile (2026-11-10: the sanitizer dropped it)."""
    drawn = render_gallery(
        items=[GalleryItem(file_id="", image_source="data:image/png;base64,AAAA", note_id="day-1", caption="Beach")],
        tile_body=lambda file_id: "", view_kind=lambda file_id: "", written_picture=lambda source: f'<img src="{source}">',
    )
    assert 'data-gallery-note-id="day-1"' in sanitize_rendered_html(drawn)
