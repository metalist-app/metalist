"""@gallery: the pictures in a note and every note under it (docs/future-plans/gallery.md)."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Dict, List, Optional

import pytest

from app.services.content_formatting import is_known_meta_tag_term, list_known_meta_tag_terms
from app.services.embedded_references import collect_active_reference_tokens, extract_collapsed_preview_source_html
from app.security.rendered_html import sanitize_rendered_html
from app.services.note_gallery import GalleryItem, collect_gallery_items, gallery_kinds, gallery_kinds_found, render_gallery
from app.services.tag_suggestions import _with_gallery_values

PHOTO_A, PHOTO_B, DRAWING, MANUAL, SKETCH = (f"{index:08d}-0000-4000-8000-000000000000" for index in range(1, 6))


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
    # Notes a search shows as grey bars.
    hidden: frozenset[str]

    def has_file(self, file_id: str) -> bool:
        return file_id in self.files

    def get_file(self, file_id: str) -> _File:
        return self.files[file_id]

    def get_note(self, note_id: str) -> _Note:
        return self.notes[note_id]

    def get_children(self, note_id: Optional[str]) -> List[str]:
        return self.children.get(note_id, [])

    def is_shown_in_gallery(self, gallery_note_id: str, note_id: str) -> bool:
        return note_id not in self.hidden


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
        hidden=frozenset(),
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
    # Plain @gallery shows images, drawings and PDFs alike (decision 3).
    assert _items(_trip(), "trip", "@gallery") == [
        (PHOTO_A, "day-1", "Beach at dusk"),
        (DRAWING, "day-1-more", "and"),
        (PHOTO_B, "day-2", ""),
        (MANUAL, "manual", "Tram manual"),
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
        hidden=frozenset(),
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
    tree = _Tree(hidden=frozenset(), notes={"album": _Note("<div>Album</div>", "@gallery"), "text": _Note("<div>Just words</div>", "")},
                 children={"album": ["text"]}, files={})
    assert _pictures(tree, "album", "@gallery") == []


def test_the_note_of_each_picture_survives_sanitizing() -> None:
    """Go to note reads it from the tile (2026-11-10: the sanitizer dropped it)."""
    drawn = render_gallery(
        items=[GalleryItem(file_id="", image_source="data:image/png;base64,AAAA", note_id="day-1", caption="Beach")],
        tile_body=lambda file_id: "", view_kind=lambda file_id: "", written_picture=lambda source: f'<img src="{source}">',
    )
    assert 'data-gallery-note-id="day-1"' in sanitize_rendered_html(drawn)


def _kinds_found(tree: _Tree, note_id: str) -> List[str]:
    return gallery_kinds_found(
        note_id=note_id, context=tree,
        file_ids_in=lambda content_html: [(token.start, token.note_id) for token in collect_active_reference_tokens(content_html)],
    )


def test_the_kinds_found_come_most_files_first_each_file_once() -> None:
    # Two photos (one written twice), one PDF, one drawing: equally many keep image, pdf, drawing.
    assert _kinds_found(_trip(), "trip") == ["image", "pdf", ".excalidraw"]
    tree = _trip()
    tree.notes["day-2"] = _Note(f"<div>![[{DRAWING}]]</div>", "")
    tree.files[SKETCH] = _File("sketch.excalidraw", "excalidraw")
    tree.notes["manual"] = _Note(f"<div>![[{SKETCH}]]</div>", "")
    assert _kinds_found(tree, "trip") == [".excalidraw", "image"]


def test_a_picture_written_in_the_text_is_an_image_and_other_files_are_not_kinds() -> None:
    tree = _Tree(
        hidden=frozenset(),
        notes={"album": _Note(f'<div><img src="https://example.com/a.png"></div><div>![[{SKETCH}]]</div>', "")},
        children={}, files={SKETCH: _File("notes.md", "text")},
    )
    assert _kinds_found(tree, "album") == ["image"]
    assert _kinds_found(_Tree(hidden=frozenset(), notes={"empty": _Note("<div>Nothing</div>", "")}, children={}, files={}), "empty") == []


def test_the_gallery_kinds_follow_plain_gallery_in_place_of_kinds_other_notes_use() -> None:
    offered = ["@gallery=image", "@gallery=pdf"]
    assert _with_gallery_values(["@gallery", "@gallery=.png", "@gantt"], gallery_values=offered, limit=10) == [
        "@gallery", "@gallery=image", "@gallery=pdf", "@gantt",
    ]
    assert _with_gallery_values(["@gallery=.png"], gallery_values=offered, limit=10) == offered
    assert _with_gallery_values(["@gallery", "@gantt"], gallery_values=offered, limit=2) == ["@gallery", "@gallery=image"]


def test_under_a_search_the_grid_holds_only_the_notes_it_shows() -> None:
    # Searching "beach": day-1 matches, the trip shows as its ancestor; day-1-more, day-2 and the
    # manual are grey bars, and so is everything under them.
    searched = dataclasses.replace(_trip(), hidden=frozenset({"day-1-more", "day-2", "manual"}))
    assert _items(searched, "trip", "@gallery") == [(PHOTO_A, "day-1", "Beach at dusk")]
    # A gallery the search shows nothing under holds only its own pictures: here none.
    assert _items(dataclasses.replace(_trip(), hidden=frozenset({"day-1", "day-2", "manual"})), "trip", "@gallery") == []
    # A gallery shown as a grey bar itself holds none.
    assert _items(dataclasses.replace(_trip(), hidden=frozenset({"trip"})), "trip", "@gallery") == []
