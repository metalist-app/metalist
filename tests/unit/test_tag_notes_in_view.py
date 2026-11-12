"""Tag Notes in View… (the maintainer, 2026-11-11; app/usecases/tag_notes_in_view.py): a tag
added to the notes a view finds, those under them carrying it through them; removed from every
note shown from them down; one undo step; done only if the count the dialog showed holds."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.notes_sql import insert_note
from app.models.database import SafeSession
from app.security import encryption
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services import undo_state
from app.services.content_cache import cache_note_tags, clear_cache
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.search_index import SearchIndex
from app.services.snapshot import ResolvedViewScope
from app.services.tag_ontology import TagOntology
from app.services.undo_state import reset_all_undo_state
from app.usecases.tag_notes_in_view import ADD, REMOVE, CmdTagNotesInView, tag_changes_in_view, tags_to_remove_in_view

NOW = datetime(2026, 11, 11, tzinfo=timezone.utc)
VIEWPORT = {"scrollY": 0, "scrollAnchor": None}
SUGGESTION_LIMIT = 20
# Leek soup (Shopping list), Lasagna, Taxes, as (id, parent, prev, next, tags).
TREE = [
    ("leek", None, None, "lasagna", "recipes"),
    ("shopping", "leek", None, None, "dinner"),
    ("lasagna", None, "leek", "taxes", "recipes Dinner"),
    ("taxes", None, "lasagna", None, "work dinner"),
]
# The search `recipes`: Leek soup and Lasagna found, Shopping list shown under Leek soup.
RECIPES = ResolvedViewScope(
    filter_active=True, allowed_note_ids=frozenset({"leek", "shopping", "lasagna"}),
    matched_note_ids=frozenset({"leek", "shopping", "lasagna"}), ordered_root_ids=(), total_root_count=0,
)
NO_SEARCH = ResolvedViewScope(
    filter_active=False, allowed_note_ids=frozenset(), matched_note_ids=frozenset(), ordered_root_ids=(), total_root_count=0,
)


@pytest.fixture
def note_store(monkeypatch: pytest.MonkeyPatch) -> NoteStore:
    monkeypatch.setattr(note_store_module, "search_index", SearchIndex())
    monkeypatch.setattr(note_store_module, "get_cached_content", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_cached_text", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_cached_proposed_tags", lambda note_id: "")
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    store = NoteStore()
    store._timing_enabled = False
    monkeypatch.setattr(store_module, "_note_store", store)
    clear_cache()
    session = SafeSession()
    for note_id, parent_id, prev_id, next_id, tags in TREE:
        cache_note_tags(note_id, tags)
        insert_note(
            session.connection(), note_id=note_id, content="", encryption_nonce=None, encryption_tag=None,
            tags=tags, tags_encryption_nonce=None, tags_encryption_tag=None, proposed_tags="",
            proposed_tags_encryption_nonce=None, proposed_tags_encryption_tag=None,
            parent_id=parent_id, prev_id=prev_id, next_id=next_id, is_collapsed=False, created_at=NOW, updated_at=NOW,
        )
    session.commit()
    store.load_from_db(session, prefetched_rows=None)
    reset_all_undo_state()
    yield store
    reset_all_undo_state()
    session.close()
    clear_cache()


def _tags(note_store: NoteStore) -> dict[str, str]:
    return {note_id: note_store.get_note(note_id).tags for note_id, *_ in TREE}


def _run(scope: ResolvedViewScope, *, action: str, tag: str, expected: int) -> dict[str, object]:
    return CmdTagNotesInView(
        scope=scope, action=action, tag=tag, expected_note_count=expected, token="",
        client_id="client", undo_context="context", viewport=VIEWPORT,
    ).execute()


def test_adding_tags_the_found_notes_and_not_those_under_them(note_store: NoteStore) -> None:
    assert _run(RECIPES, action=ADD, tag="soup", expected=2)["changedCount"] == 2

    assert _tags(note_store) == {
        "leek": "recipes soup", "shopping": "dinner", "lasagna": "recipes Dinner soup", "taxes": "work dinner",
    }


def test_a_note_with_the_tag_already_is_left_as_it_is(note_store: NoteStore) -> None:
    # Lasagna has Dinner already, whatever its case.
    assert [change.note_id for change in tag_changes_in_view(RECIPES, action=ADD, tag="dinner")] == ["leek"]


def test_removing_takes_it_from_every_note_shown_from_the_found_ones_down(note_store: NoteStore) -> None:
    assert _run(RECIPES, action=REMOVE, tag="dinner", expected=2)["changedCount"] == 2

    # Taxes is not in the view: it keeps its own.
    assert _tags(note_store) == {"leek": "recipes", "shopping": "", "lasagna": "recipes", "taxes": "work dinner"}


def test_with_no_search_every_note_counts(note_store: NoteStore) -> None:
    assert [change.note_id for change in tag_changes_in_view(NO_SEARCH, action=ADD, tag="kept")] == ["leek", "lasagna", "taxes"]
    assert [change.note_id for change in tag_changes_in_view(NO_SEARCH, action=REMOVE, tag="dinner")] == ["shopping", "lasagna", "taxes"]


def test_one_undo_takes_it_all_back(note_store: NoteStore) -> None:
    before = _tags(note_store)
    _run(RECIPES, action=REMOVE, tag="dinner", expected=2)

    assert undo_state.undo("client", "") is not None

    assert _tags(note_store) == before


def test_nothing_changes_if_the_view_changed_since_the_count(note_store: NoteStore) -> None:
    before = _tags(note_store)

    with pytest.raises(InputRejected, match="changed while the dialog was open"):
        _run(RECIPES, action=ADD, tag="soup", expected=3)

    assert _tags(note_store) == before


def test_only_one_plain_tag_is_taken(note_store: NoteStore) -> None:
    with pytest.raises(InputRejected, match="one tag"):
        tag_changes_in_view(RECIPES, action=ADD, tag="two words")


def test_removing_suggests_the_tags_the_notes_carry_most_first_then_by_name(note_store: NoteStore) -> None:
    assert tags_to_remove_in_view(RECIPES, prefix="", limit=SUGGESTION_LIMIT) == ["dinner", "recipes"]
    assert tags_to_remove_in_view(RECIPES, prefix="di", limit=SUGGESTION_LIMIT) == ["dinner"]
