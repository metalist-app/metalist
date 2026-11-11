from __future__ import annotations

import html
from typing import FrozenSet, Set

from app.services.credential_display import CredentialDisplay
from app.security.rendered_html import sanitize_rendered_html
from app.services.content_formatting import find_list_style
from app.services.content_formatting import showing_sites_above
from app.services.content_formatting import sites_linked_in
from app.services.embedded_references import EmbedRenderContext
from app.services.embedded_references import render_note_content_with_embeds
from app.services.file_registry import file_registry
from app.services.file_storage import get_file_reference_record
from app.services.file_view import STATUS_READY, FileView
from app.services.note_store import store as note_store
from app.services.search_index import search_index

# A reference's preview card shows the top of its note (docs/ui/references.md):
# the note and its first descendants, more than the card's few lines can show.
PREVIEW_NOTE_LIMIT = 12


class _Allowance:
    """How many more notes a rendering may draw."""

    def __init__(self, notes: int) -> None:
        assert notes > 0, "a rendering draws at least its note"
        self.left = notes

    def take(self) -> bool:
        if self.left == 0:
            return False
        self.left -= 1
        return True


class _EveryNote(_Allowance):
    """Full screen and floating windows draw the whole subtree."""

    def __init__(self) -> None:
        super().__init__(1)

    def take(self) -> bool:
        return True


def build_note_fullscreen_markup(note_id: str) -> str:
    """The note and its whole subtree, as full screen and floating windows show them."""
    return _build_markup(note_id, allowance=_EveryNote(), credentials=CredentialDisplay.DOTS)


def build_note_preview_markup(note_id: str) -> str:
    """The top of a note as the list draws it, for a reference's preview card: the note
    and its first descendants, passwords and usernames hidden as an export hides them."""
    return _build_markup(note_id, allowance=_Allowance(PREVIEW_NOTE_LIMIT), credentials=CredentialDisplay.HIDDEN)


def build_file_preview_markup(file_id: str) -> str:
    """A file reference's preview card (smart previews, slice 4): the file as `![[UUID]]`
    draws it in a note: a picture, a diagram's preview, or the file's card."""
    if not isinstance(file_id, str) or not file_registry.has_file(file_id):
        raise ValueError("file_id must name a file")
    rendered_embed = render_note_content_with_embeds(
        note_id=file_id,
        content_html=f"<div>![[{file_id}]]</div>",
        tags="",
        context=_render_context(),
        static_export=False,
        credentials=CredentialDisplay.HIDDEN,
    )
    return sanitize_rendered_html(
        '<article class="note"><div class="note-content" contenteditable="false">'
        f"{rendered_embed}</div></article>"
    )


def build_file_view_markup(file_id: str, view: FileView) -> str:
    """A file as the viewer shows it (docs/ready-to-build/files-shown-not-copied.md §4): its
    note HTML drawn as a note with its meta tag is (`@markdown`, `@csv`, `@json`, `@code=…`)."""
    if not isinstance(file_id, str) or not file_registry.has_file(file_id):
        raise ValueError("file_id must name a file")
    if view.status != STATUS_READY:
        raise ValueError(f"only a ready view is drawn, not {view.status!r}")
    rendered = render_note_content_with_embeds(
        note_id=file_id,
        content_html=view.content_html,
        tags=view.render_tag,
        context=_render_context(),
        static_export=False,
        credentials=CredentialDisplay.HIDDEN,
    )
    return sanitize_rendered_html(
        '<article class="note"><div class="note-content" contenteditable="false">'
        f"{rendered}</div></article>"
    )


def _render_context() -> EmbedRenderContext:
    file_record_cache: dict[str, object] = {}

    def _get_file_record(file_id: str) -> object:
        if file_id not in file_record_cache:
            file_record_cache[file_id] = get_file_reference_record(file_id, token=None)
        return file_record_cache[file_id]

    return EmbedRenderContext(
        has_note=note_store.has_note,
        get_note=note_store.get_note,
        get_children=note_store.get_children,
        has_file=file_registry.has_file,
        get_file=_get_file_record,
        is_property_used=search_index.is_property_name_used,
        # Not a searched list: every note shows.
        is_shown_in_gallery=lambda gallery_note_id, note_id: True,
        static_collapse_arrows=False,
    )


def _build_markup(note_id: str, *, allowance: _Allowance, credentials: CredentialDisplay) -> str:
    if not isinstance(note_id, str) or note_id == "":
        raise TypeError("note_id must be a non-empty string")

    render_context = _render_context()
    assert allowance.take(), "the note itself is always drawn"
    return sanitize_rendered_html(_render_fullscreen_note(
        note_id=note_id,
        render_context=render_context,
        visiting=set(),
        allowance=allowance,
        credentials=credentials,
        # Shown without its ancestors: its own links keep their sites.
        sites_above=frozenset(),
    ))


def _render_fullscreen_note(
    *,
    note_id: str,
    render_context: EmbedRenderContext,
    visiting: Set[str],
    allowance: _Allowance,
    credentials: CredentialDisplay,
    sites_above: FrozenSet[str],
) -> str:
    if note_id in visiting:
        raise RuntimeError(f"Hierarchy cycle detected while rendering note {note_id}")
    visiting.add(note_id)

    record = note_store.get_note(note_id)
    if not isinstance(record.content, str):
        raise TypeError("note content must be a string")
    if not isinstance(record.tags, str):
        raise TypeError("note tags must be a string")

    # Links to a site its ancestors here link to show their text alone (docs/ui/content-formatting.md).
    with showing_sites_above(sites_above):
        rendered_content = render_note_content_with_embeds(
            note_id=note_id,
            content_html=record.content,
            tags=record.tags,
            context=render_context,
            static_export=False,
            credentials=credentials,
        )

    classes = ["note"]
    list_style = find_list_style(record.tags)
    if list_style == "bulleted":
        classes.append("list-bulleted")
    elif list_style == "numbered":
        classes.append("list-numbered")

    # No indentation is added for readability: inside a code block every added space
    # would show (an @code note's lines moved right by four spaces per level).
    parts = [
        f'<article class="{" ".join(classes)}">',
        '<div class="note-content" contenteditable="false">',
        rendered_content,
        "</div>",
        f'<div class="note-tags" aria-hidden="true">{html.escape(record.tags)}</div>',
    ]

    child_parts = []
    for child_id in note_store.get_children(note_id):
        if not allowance.take():
            break
        child_parts.append(_render_fullscreen_note(
            note_id=child_id,
            render_context=render_context,
            visiting=visiting,
            allowance=allowance,
            credentials=credentials,
            sites_above=sites_above | sites_linked_in(record.content),
        ))
    if child_parts:
        parts.extend(['<div class="note-children">', *child_parts, "</div>"])
    parts.append("</article>")
    visiting.remove(note_id)
    return "".join(parts)

