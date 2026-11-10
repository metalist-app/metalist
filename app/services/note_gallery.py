"""`@gallery`: the pictures in a note and in every note under it, as a grid under its text
(docs/future-plans/gallery.md). `@gallery=image`, `@gallery=pdf,.png` narrow it to file kinds,
named as Notes with Files names them (file_kinds.file_kind_of).

Files are read through the render context, as @stats reads values (subtree_stats.py), so the
cached rendering of the note is redrawn whenever a note under it changes. An embedded note adds
nothing: only real children are part of the subtree, as for tags (docs/ui/references.md).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Protocol, Tuple

from app.services.content_formatting import is_markdown_note
from app.services.file_kinds import FILE_KIND_IMAGE, file_kind_of
from app.services.inline_image_occurrences import INLINE_IMAGE_TAG_RE
from app.services.structured_note_renderers import extract_plain_text_from_note_html

GALLERY_TAG = "@gallery"
# A whole token on the note's own tag line: @gallery or @gallery=image,pdf.
_GALLERY_TAG_RE = re.compile(r"(?<!\S)@gallery(?:=(?P<kinds>[^\s=:]+))?(?!\S)", re.IGNORECASE)
# What plain @gallery shows: what can be drawn as a picture. PDFs join once they have a
# first-page preview (docs/future-plans/gallery.md, "PDF first pages").
_PICTURE_THUMBNAIL_KINDS = frozenset({"image", "excalidraw"})
_KIND_SEPARATOR = ","
# A file written in a note: ![[id]] or [[id]].
_REFERENCE_RE = re.compile(r"!?\[\[[^\]]*\]\]")
# A picture written in a note's text: an <img>'s address, or ![...](address) in a Markdown note.
_IMAGE_SOURCE_RE = re.compile(r"\ssrc\s*=\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|(?P<bare>[^\s>]+))", re.IGNORECASE)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?(?P<source>[^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


class GalleryTree(Protocol):
    has_file: Callable[[str], bool]
    get_file: Callable[[str], object]
    get_note: Callable[[str], object]
    get_children: Callable[[Optional[str]], List[str]]


@dataclass(frozen=True, slots=True)
class GalleryItem:
    """One picture: a stored file (file_id) or one written in the text (image_source); the other is ""."""
    file_id: str
    image_source: str
    note_id: str
    caption: str


def gallery_kinds(tags: str) -> Optional[Tuple[str, ...]]:
    """The file kinds a note's @gallery asks for: () for plain @gallery, None for no @gallery."""
    if not isinstance(tags, str):
        raise TypeError(f"tags must be a string, got {type(tags)}")
    match = _GALLERY_TAG_RE.search(tags)
    if match is None:
        return None
    if match.group("kinds") is None:
        return ()
    return tuple(kind.casefold() for kind in match.group("kinds").split(_KIND_SEPARATOR) if kind != "")


def _attribute(record: object, name: str) -> str:
    value = getattr(record, name)
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value)}")
    return value


def _is_shown(record: object, kinds: Tuple[str, ...]) -> bool:
    thumbnail_kind = _attribute(record, "thumbnail_kind")
    if not kinds:
        return thumbnail_kind in _PICTURE_THUMBNAIL_KINDS
    return file_kind_of(thumbnail_kind=thumbnail_kind, file_name=_attribute(record, "original_filename")) in kinds


def _caption(content_html: str, first_line_of: Callable[[str], str]) -> str:
    """The note's first line when it is text; a note that is only its picture has none."""
    first_line = _REFERENCE_RE.sub(" ", first_line_of(content_html))
    return " ".join(extract_plain_text_from_note_html(first_line).split())


def _written_pictures(content_html: str, tags: str) -> List[Tuple[int, str]]:
    """The pictures written in a note's text, with where each starts."""
    found: List[Tuple[int, str]] = []
    for image in INLINE_IMAGE_TAG_RE.finditer(content_html):
        source = _IMAGE_SOURCE_RE.search(image.group(0))
        if source is None:
            continue
        address = next(value for value in source.group("double", "single", "bare") if value is not None)
        if address.strip() != "":
            found.append((image.start(), html.unescape(address.strip())))
    if is_markdown_note(tags):
        found.extend((match.start(), html.unescape(match.group("source"))) for match in _MARKDOWN_IMAGE_RE.finditer(content_html))
    return found


def _note_pictures(
    *, note_id: str, kinds: Tuple[str, ...], context: GalleryTree, file_ids_in: Callable[[str], Iterable[Tuple[int, str]]],
) -> List[Tuple[int, str, str]]:
    """A note's pictures in the order written, as (where, file id, image address)."""
    record = context.get_note(note_id)
    content_html = _attribute(record, "content")
    pictures: List[Tuple[int, str, str]] = []
    for start, file_id in file_ids_in(content_html):
        if context.has_file(file_id) and _is_shown(context.get_file(file_id), kinds):
            pictures.append((start, file_id, ""))
    # A picture written in the text is an image (Notes with Files' kind).
    if not kinds or FILE_KIND_IMAGE in kinds:
        pictures.extend((start, "", address) for start, address in _written_pictures(content_html, _attribute(record, "tags")))
    return sorted(pictures)


def collect_gallery_items(
    *,
    note_id: str,
    kinds: Tuple[str, ...],
    context: GalleryTree,
    file_ids_in: Callable[[str], Iterable[Tuple[int, str]]],
    first_line_of: Callable[[str], str],
) -> List[GalleryItem]:
    """The pictures the gallery shows, in outline order (the note, then each child's subtree in
    turn), each once, where it first appears."""
    items: List[GalleryItem] = []
    seen: set[Tuple[str, str]] = set()
    pending = [note_id]
    while pending:
        current_id = pending.pop()
        caption: Optional[str] = None
        for _start, file_id, image_source in _note_pictures(note_id=current_id, kinds=kinds, context=context, file_ids_in=file_ids_in):
            if (file_id, image_source) in seen:
                continue
            seen.add((file_id, image_source))
            if caption is None:
                caption = _caption(_attribute(context.get_note(current_id), "content"), first_line_of)
            items.append(GalleryItem(file_id=file_id, image_source=image_source, note_id=current_id, caption=caption))
        pending.extend(reversed(context.get_children(current_id)))
    return items


def render_gallery(
    *, items: List[GalleryItem], tile_body: Callable[[str], str], view_kind: Callable[[str], str],
    written_picture: Callable[[str], str],
) -> str:
    """The grid under the note's text: nothing when there is no picture, so the children stay
    shown (main.css). A click on a tile shows its picture full screen (mouse-events.js)."""
    if not items:
        return ""
    tiles = []
    for item in items:
        caption = ""
        if item.caption != "":
            caption = f'<span class="meta-gallery-caption">{html.escape(item.caption)}</span>'
        note = f'data-gallery-note-id="{html.escape(item.note_id, quote=True)}"'
        if item.file_id == "":
            tiles.append(
                f'<button type="button" class="note-file-reference-link meta-gallery-tile" {note}>'
                f'<span class="meta-gallery-picture">{written_picture(item.image_source)}</span>{caption}</button>'
            )
            continue
        escaped_file_id = html.escape(item.file_id, quote=True)
        tiles.append(
            f'<button type="button" class="note-file-reference-link meta-gallery-tile" data-file-ref-id="{escaped_file_id}" '
            f'data-file-view="{html.escape(view_kind(item.file_id), quote=True)}" {note}>'
            f'<span class="meta-gallery-picture">{tile_body(item.file_id)}</span>{caption}</button>'
        )
    # The switch between the grid and the children (gallery-view-service.js) sits in the margin.
    switch = '<button type="button" class="meta-gallery-switch" aria-label="Show as outline" title="Show as outline"></button>'
    return f'<section class="meta-gallery" aria-label="Gallery">{switch}<div class="meta-gallery-grid">{"".join(tiles)}</div></section>'
