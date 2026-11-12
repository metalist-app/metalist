"""Delete Notes (Current View)… (2026-10-31; docs/ui/command-palette.md): the notes a view
finds, each with everything under it, a note above a match staying; with nothing narrowing
the view, every note; and only if the confirmed count still holds."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.notes_sql import insert_note
from app.models.database import SafeSession
from app.security import encryption
from app.services import content_cache
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.search_index import SearchIndex
from app.services.snapshot import ResolvedViewScope
from app.services.tag_ontology import TagOntology
from app.usecases.delete_notes_in_view import CmdDeleteNotesInView, notes_to_delete

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)
# A (A1, A2), B (B1), C, as (id, parent, prev, next).
TREE = [
    ("A", None, None, "B"), ("A1", "A", None, "A2"), ("A2", "A", "A1", None),
    ("B", None, "A", "C"), ("B1", "B", None, None), ("C", None, "B", None),
]


@pytest.fixture
def note_store(monkeypatch: pytest.MonkeyPatch) -> NoteStore:
    monkeypatch.setattr(note_store_module, "search_index", SearchIndex())
    monkeypatch.setattr(note_store_module, "get_cached_content", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_cached_text", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_cached_tags", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_cached_proposed_tags", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    store = NoteStore()
    store._timing_enabled = False
    monkeypatch.setattr(store_module, "_note_store", store)
    session = SafeSession()
    for note_id, parent_id, prev_id, next_id in TREE:
        insert_note(
            session.connection(), note_id=note_id, content="", encryption_nonce=None, encryption_tag=None,
            tags="", tags_encryption_nonce=None, tags_encryption_tag=None, proposed_tags="",
            proposed_tags_encryption_nonce=None, proposed_tags_encryption_tag=None,
            parent_id=parent_id, prev_id=prev_id, next_id=next_id, is_collapsed=False, created_at=NOW, updated_at=NOW,
        )
    session.commit()
    # The real cache as loading fills it: a delete evicts its notes from it (content_cache.forget_notes).
    for note_id, _parent_id, _prev_id, _next_id in TREE:
        _fill_content_cache(note_id)
    store.load_from_db(session, prefetched_rows=None)
    yield store
    session.close()
    content_cache.clear_cache()


def _fill_content_cache(note_id: str) -> None:
    content_cache.cache_note(note_id, "")
    content_cache.cache_note_tags(note_id, "")
    content_cache.cache_note_proposed_tags(note_id, "")
    content_cache.cache_note_text(note_id, "")


def view(matched: set[str], *, is_filtered: bool) -> ResolvedViewScope:
    return ResolvedViewScope(
        filter_active=is_filtered, allowed_note_ids=frozenset(matched), matched_note_ids=frozenset(matched),
        ordered_root_ids=(), total_root_count=0,
    )


def test_the_topmost_found_notes_go_with_everything_under_them(note_store: NoteStore) -> None:
    deletion = notes_to_delete(view({"A", "A1", "B1"}, is_filtered=True))
    # Counted as the list counts notes: A1 goes with A, uncounted.
    assert (deletion.top_note_ids, deletion.note_count, deletion.is_whole_vault) == (["A", "B1"], 2, False)
    CmdDeleteNotesInView(scope=view({"A", "A1", "B1"}, is_filtered=True), expected_note_count=2, client_id="c", undo_context="u").execute()
    # B stays: it is above a match, not a match.
    assert note_store.get_children(None) == ["B", "C"]
    assert note_store.get_children("B") == []


def test_with_nothing_narrowing_the_view_every_note_goes(note_store: NoteStore) -> None:
    deletion = notes_to_delete(view(set(), is_filtered=False))
    assert (deletion.note_count, deletion.is_whole_vault) == (3, True)
    CmdDeleteNotesInView(scope=view(set(), is_filtered=False), expected_note_count=3, client_id="c", undo_context="u").execute()
    assert note_store.get_children(None) == []


def test_a_count_that_changed_since_the_confirmation_deletes_nothing(note_store: NoteStore) -> None:
    with pytest.raises(InputRejected, match="now holds 3 notes, not the 2 you confirmed"):
        CmdDeleteNotesInView(scope=view(set(), is_filtered=False), expected_note_count=2, client_id="c", undo_context="u").execute()
    assert note_store.get_children(None) == ["A", "B", "C"]
