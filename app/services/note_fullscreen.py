from __future__ import annotations

import html
from typing import Set

from app.security.rendered_html import sanitize_rendered_html
from app.services.content_formatting import find_list_style
from app.services.embedded_references import EmbedRenderContext
from app.services.embedded_references import render_note_content_with_embeds
from app.services.file_registry import file_registry
from app.services.file_storage import get_file_reference_record
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
    return _build_markup(note_id, allowance=_EveryNote(), redact_credentials=False)


def build_note_preview_markup(note_id: str) -> str:
    """The top of a note as the list draws it, for a reference's preview card: the note
    and its first descendants, passwords and usernames hidden as an export hides them."""
    return _build_markup(note_id, allowance=_Allowance(PREVIEW_NOTE_LIMIT), redact_credentials=True)


def _build_markup(note_id: str, *, allowance: _Allowance, redact_credentials: bool) -> str:
    if not isinstance(note_id, str) or note_id == "":
        raise TypeError("note_id must be a non-empty string")

    file_record_cache: dict[str, object] = {}

    def _get_file_record(file_id: str) -> object:
        if file_id not in file_record_cache:
            file_record_cache[file_id] = get_file_reference_record(file_id, token=None)
        return file_record_cache[file_id]

    render_context = EmbedRenderContext(
        has_note=note_store.has_note,
        get_note=note_store.get_note,
        get_children=note_store.get_children,
        has_file=file_registry.has_file,
        get_file=_get_file_record,
        is_property_used=search_index.is_property_name_used,
        static_collapse_arrows=False,
    )
    assert allowance.take(), "the note itself is always drawn"
    return sanitize_rendered_html(_render_fullscreen_note(
        note_id=note_id,
        render_context=render_context,
        visiting=set(),
        allowance=allowance,
        redact_credentials=redact_credentials,
    ))


def _render_fullscreen_note(
    *,
    note_id: str,
    render_context: EmbedRenderContext,
    visiting: Set[str],
    allowance: _Allowance,
    redact_credentials: bool,
) -> str:
    if note_id in visiting:
        raise RuntimeError(f"Hierarchy cycle detected while rendering note {note_id}")
    visiting.add(note_id)

    record = note_store.get_note(note_id)
    if not isinstance(record.content, str):
        raise TypeError("note content must be a string")
    if not isinstance(record.tags, str):
        raise TypeError("note tags must be a string")

    rendered_content = render_note_content_with_embeds(
        note_id=note_id,
        content_html=record.content,
        tags=record.tags,
        context=render_context,
        static_export=False,
        redact_credentials=redact_credentials,
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
            redact_credentials=redact_credentials,
        ))
    if child_parts:
        parts.extend(['<div class="note-children">', *child_parts, "</div>"])
    parts.append("</article>")
    visiting.remove(note_id)
    return "".join(parts)

