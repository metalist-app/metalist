"""Trim Unused Files never deletes a file that ⌘Z or a paste could bring back
(docs/ui/command-palette.md, `Trim Unused Files…`; agreed 2026-10-27): files named by any
tab's undo or redo history, or by any tab's copied note, are kept."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.api.routes.files as files_route
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required, set_session_dek
from app.services import sync, undo_state
from app.services.file_registry import file_registry
from app.services.file_storage import create_file
from app.services.store import NodeRecord

VIEWPORT = {"scrollY": 0, "scrollAnchor": None}
CLIENT = "client-trim"
UNDO_CONTEXT = "tab:main|search:|epoch:0"


@dataclass(frozen=True)
class _Note:
    content: str


class _NoReferences:
    """A vault whose notes reference no file (the note holding it was deleted or cut)."""

    loaded = True

    def has_note(self, note_id: str) -> bool:
        return note_id == "other"

    def list_note_ids(self) -> list[str]:
        return ["other"]

    def get_note(self, note_id: str) -> _Note:
        return _Note(content="<div>No files here</div>")

    def referenced_target_ids(self) -> frozenset[str]:
        return frozenset()


def _record(content: str) -> NodeRecord:
    return NodeRecord(
        id="gone", parent_id=None, prev_id=None, next_id=None, is_collapsed=False, content=content, tags="",
        proposed_tags="", tag_terms=frozenset(), non_meta_tag_terms=frozenset(), proposed_tag_terms=frozenset(),
        proposed_non_meta_tag_terms=frozenset(), created_at=None, updated_at=None,
    )


@pytest.fixture
def files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_encryption_required(True)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_session_dek(os.urandom(32))
    file_registry.reset()
    undo_state._clients.clear()
    sync.reset_state()
    store = _NoReferences()
    monkeypatch.setattr("app.services.file_storage.note_store", store)
    monkeypatch.setattr(files_route, "_require_bearer_token", lambda request: "token")
    kept = create_file(original_filename="photo.png", mime_type="image/png", content_bytes=b"photo", token="token")
    unused = create_file(original_filename="old.txt", mime_type="text/plain", content_bytes=b"old", token="token")
    yield SimpleNamespace(kept=kept.id, unused=unused.id)
    undo_state._clients.clear()
    sync.reset_state()
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)
    SafeSession.use_file_db()


def _trim() -> list[str]:
    return files_route.trim_unused_files_endpoint(request=None).deleted_file_ids


def test_a_deleted_notes_file_survives_trim_for_undo(files: SimpleNamespace) -> None:
    undo_state.record_delete(CLIENT, UNDO_CONTEXT, [_record(f"<div>![[{files.kept}]]</div>")], viewport=VIEWPORT)
    assert _trim() == [files.unused]
    assert file_registry.has_file(files.kept)


def test_a_copied_notes_file_survives_trim_for_paste(files: SimpleNamespace) -> None:
    sync.set_clipboard(CLIENT, [{"id": "gone", "content": f"<div>![[{files.kept}]]</div>", "tags": ""}])
    assert _trim() == [files.unused]
    assert file_registry.has_file(files.kept)
