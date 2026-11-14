"""A read that checks a note is there and then reads it in later steps runs one at a time with the
writes (serialized_read_route): a delete landing between the two failed it (the Password Audit
with a note deleted from its menu, 2026-11-14). Each read here is made while a delete, holding the
lock writes hold, tries to land in the middle of it."""

from __future__ import annotations

from threading import Thread

import pytest

import app.api.routes.notes as notes_routes
from app.services.bulk_operation import bulk_operation_guard

NOTE = "10000000-0000-4000-8000-00000000000a"
# Long enough for a delete that isn't held back to finish.
_DELETE_GRACE_SECONDS = 0.3


class _Notes:
    """A note store with one note, which a delete can remove."""

    def __init__(self) -> None:
        self.present = {NOTE}

    def has_note(self, note_id: str) -> bool:
        return note_id in self.present

    def get_outside_referrer_ids(self, note_id: str) -> frozenset[str]:
        if note_id not in self.present:
            raise KeyError(f"Note {note_id} not present in NoteStore")
        return frozenset()


def _delete_landing_now(notes: _Notes) -> None:
    """A delete as a write makes it, holding the writes' lock; given time to land."""
    def delete() -> None:
        with bulk_operation_guard.lock:
            notes.present.discard(NOTE)

    deleting = Thread(target=delete, daemon=True)
    deleting.start()
    deleting.join(timeout=_DELETE_GRACE_SECONDS)


def _built_after_a_delete_tries_to_land(notes: _Notes):
    def build(note_id: str) -> str:
        _delete_landing_now(notes)
        if note_id not in notes.present:
            raise KeyError(f"Note {note_id} not present in NoteStore")
        return "<div>the note</div>"
    return build


@pytest.fixture
def notes(monkeypatch: pytest.MonkeyPatch) -> _Notes:
    store = _Notes()
    monkeypatch.setattr(notes_routes, "note_store", store)
    monkeypatch.setattr(notes_routes, "_require_note_present", lambda note_id, *, context: None)
    builder = _built_after_a_delete_tries_to_land(store)
    monkeypatch.setattr(notes_routes, "build_note_preview_markup", builder)
    monkeypatch.setattr(notes_routes, "build_note_fullscreen_markup", builder)
    monkeypatch.setattr(notes_routes, "get_current_sync_uuid", lambda: "sync")
    return store


def test_a_preview_card_is_not_failed_by_a_delete(notes: _Notes) -> None:
    assert notes_routes.note_preview(NOTE) == {"status": "ready", "html": "<div>the note</div>"}


def test_full_screen_is_not_failed_by_a_delete(notes: _Notes) -> None:
    assert notes_routes.note_fullscreen(NOTE) == {"html": "<div>the note</div>"}


def test_a_floating_window_is_not_failed_by_a_delete(notes: _Notes, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(notes_routes.link_title_store, "get_revision", lambda: 1)
    assert notes_routes.note_floating_window(NOTE, revision="older")["status"] == "ready"


def test_counting_outside_referrers_is_not_failed_by_a_delete(notes: _Notes, monkeypatch: pytest.MonkeyPatch) -> None:
    def present_then_deleted(note_id: str, *, context: str) -> None:
        assert note_id in notes.present
        _delete_landing_now(notes)

    monkeypatch.setattr(notes_routes, "_require_note_present", present_then_deleted)
    assert notes_routes.outside_referrers(NOTE) == {"noteId": NOTE, "count": 0}
