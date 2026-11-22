"""A copied note's diagrams are its own (docs/ui/excalidraw.md, "Copies"; the maintainer,
2026-11-22: "if I copy a note that has a diagram in it, just make a new identical diagram").

Diagrams are the only attachments edited in place, so they are the only ones where sharing a
file between two notes shows: redrawing it in one note changed the other. A pasted copy of a
note gets its own copy of each diagram another note still shows, as it gets its own copy of the
text. A diagram no note shows any more (the note was cut, not copied) goes on with the pasted
note as it is.
"""

from __future__ import annotations

from typing import Dict, List

from app.services.file_registry import file_registry, referenced_file_ids
from app.services.file_storage import duplicate_editable_file, is_editable_file_kind
from app.services.note_store import store as note_store


def diagram_ids_in(text: str) -> List[str]:
    """The diagrams a note's text references, in order, once each."""
    diagram_ids: List[str] = []
    for file_id in referenced_file_ids(text):
        kind = file_registry.thumbnail_kind_of(file_id)
        if kind is not None and is_editable_file_kind(kind):
            diagram_ids.append(file_id)
    return diagram_ids


def _name_of(file_id: str) -> str:
    name = file_registry.title_of(file_id)
    assert name is not None, "a diagram in the registry has a name"
    return name


def snapshot_with_own_diagrams(snapshot: List[dict], *, token: str) -> List[dict]:
    """The copied notes about to be pasted, each diagram a live note still shows replaced by a
    copy of it (one copy however many of the pasted notes show it)."""
    copies: Dict[str, str] = {}
    pasted: List[dict] = []
    for entry in snapshot:
        content = entry["content"]
        if not isinstance(content, str):
            raise ValueError("Clipboard snapshot content must be a string")
        for file_id in diagram_ids_in(content):
            if file_id not in copies and note_store.note_ids_referencing({file_id}):
                copies[file_id] = duplicate_editable_file(file_id=file_id, name=_name_of(file_id), token=token).id
            if file_id in copies:
                content = content.replace(file_id, copies[file_id])
        pasted.append({**entry, "content": content})
    return pasted
