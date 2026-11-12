"""A deleted note's decrypted text and tags leave the content cache; undo brings them back
through the restore that undo always uses (docs/ready-to-build/unbounded-growth-audit.md, M4)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.notes_sql import insert_note
from app.models.database import SafeSession
from app.security import encryption
from app.services import content_cache
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services import undo_state
from app.services.note_store import NoteStore
from app.services.search_index import SearchIndex
from app.services.tag_ontology import TagOntology
from app.usecases.delete_subtree import CmdDeleteSubtree

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)
# Note A (A1 under it) and note B, as (id, parent, prev, next, content, tags).
TREE = [
    ("A", None, None, "B", "<p>Note A secret</p>", "@alpha"),
    ("A1", "A", None, None, "<p>Note A1 secret</p>", "@alpha-child"),
    ("B", None, "A", None, "<p>Note B stays</p>", "@beta"),
]
CACHES = ("_search_cache", "_tag_cache", "_proposed_tag_cache", "_text_cache")
VIEWPORT = {"scrollY": 0, "scrollAnchor": None}


@pytest.fixture
def note_store(monkeypatch: pytest.MonkeyPatch) -> NoteStore:
    monkeypatch.setattr(note_store_module, "search_index", SearchIndex())
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    content_cache.clear_cache()
    undo_state.reset_all_undo_state()
    store = NoteStore()
    store._timing_enabled = False
    monkeypatch.setattr(store_module, "_note_store", store)
    session = SafeSession()
    for note_id, parent_id, prev_id, next_id, content, tags in TREE:
        insert_note(
            session.connection(), note_id=note_id, content=content, encryption_nonce=None, encryption_tag=None,
            tags=tags, tags_encryption_nonce=None, tags_encryption_tag=None, proposed_tags="",
            proposed_tags_encryption_nonce=None, proposed_tags_encryption_tag=None,
            parent_id=parent_id, prev_id=prev_id, next_id=next_id, is_collapsed=False, created_at=NOW, updated_at=NOW,
        )
        content_cache.cache_note(note_id, content)
        content_cache.cache_note_tags(note_id, tags)
        content_cache.cache_note_proposed_tags(note_id, "")
        content_cache.cache_note_text(note_id, content.removeprefix("<p>").removesuffix("</p>"))
    session.commit()
    store.load_from_db(session, prefetched_rows=None)
    yield store
    session.close()
    content_cache.clear_cache()
    undo_state.reset_all_undo_state()


def _cached_ids() -> dict[str, set[str]]:
    return {name: set(getattr(content_cache, name)) for name in CACHES}


def test_a_deleted_note_and_its_children_leave_every_cache(note_store: NoteStore) -> None:
    CmdDeleteSubtree(note_id="A", client_id="c", undo_context="u", viewport=VIEWPORT).execute()

    assert _cached_ids() == {name: {"B"} for name in CACHES}
    assert content_cache.get_cached_content("B") == "<p>Note B stays</p>"


def test_undo_of_a_delete_brings_the_content_back_and_redo_drops_it_again(note_store: NoteStore) -> None:
    CmdDeleteSubtree(note_id="A", client_id="c", undo_context="u", viewport=VIEWPORT).execute()

    undo_state.undo("c", "")

    assert note_store.get_children(None) == ["A", "B"]
    assert content_cache.get_cached_content("A") == "<p>Note A secret</p>"
    assert content_cache.get_cached_text("A1") == "Note A1 secret"
    assert content_cache.get_cached_tags("A1") == "@alpha-child"
    assert content_cache.get_cached_proposed_tags("A") == ""

    undo_state.redo("c", "")

    assert _cached_ids() == {name: {"B"} for name in CACHES}
