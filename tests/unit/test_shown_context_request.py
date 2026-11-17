"""The server owns the context each view shows (docs/future-plans/one-writer-refactoring.md, idea
1). A view says "I now show tab X" (TabStateStore.show_tab); the save of its whole copy of the tabs
(update) carries scroll, order and reference pages, and never the tab shown. The cases agreed
2026-11-17 are numbered in the comments."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import edit_locks
from app.services.input_errors import InputRejected
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000d1"
PHONE = "10000000-0000-4000-8000-0000000000d2"
NEW_VIEW = "10000000-0000-4000-8000-0000000000d3"
NO_SUCH_TAB = "10000000-0000-4000-8000-0000000000d4"
NOTE = "20000000-0000-4000-8000-0000000000d5"
SCROLLED = 480


@pytest.fixture(autouse=True)
def _memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    edit_locks.reset()
    yield
    edit_locks.reset()
    SafeSession.use_file_db()


def _two_contexts(store: TabStateStore) -> tuple[str, str]:
    """Two search contexts, the Mac showing the first."""
    first = store.snapshot(view_id=MAC)["activeTabId"]
    second = store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)["newTabId"]
    store.show_tab(view_id=MAC, tab_id=first)
    return first, second


def _save_copy(store: TabStateStore, view: str, copy: dict) -> dict:
    return store.update(
        view_id=view, tabs=copy["tabs"], tab_order=copy["tabOrder"],
        reference_views=copy["referenceViews"], read_at_version=copy["version"],
    )


def _restarted() -> TabStateStore:
    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:shown_context_request"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    return restarted


def _open_page(store: TabStateStore, view: str, context: str) -> str:
    """A reference page opened from context, as the browser opens one: made, shown, then saved
    with the view's copy."""
    page = store.create_tab(view_id=view, copy_from_tab_id=context, copies_view=False, is_page=True)["newTabId"]
    store.show_tab(view_id=view, tab_id=page)
    copy = store.snapshot(view_id=view)
    copy["tabs"][page]["searchQuery"] = NOTE
    copy["referenceViews"][page] = {
        "fromTabId": context, "referenceQuery": NOTE, "viewKind": "source",
        "originScope": {"scopeTabId": context, "searchQuery": "", "sortMode": "normal", "isUntaggedView": False},
    }
    _save_copy(store, view, copy)
    return page


# Case 1: switch to another context, reload.
def test_a_context_shown_is_answered_and_survives_a_restart() -> None:
    store = TabStateStore()
    _first, second = _two_contexts(store)

    answer = store.show_tab(view_id=MAC, tab_id=second)

    assert answer["changed"] is True
    assert answer["activeTabId"] == second
    assert _restarted().snapshot(view_id=MAC)["activeTabId"] == second


# Case 2: A, B, A.
def test_the_context_asked_for_last_is_the_one_shown() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)

    store.show_tab(view_id=MAC, tab_id=second)
    store.show_tab(view_id=MAC, tab_id=first)

    assert _restarted().snapshot(view_id=MAC)["activeTabId"] == first


# Case 3: a new context is shown.
def test_a_new_context_is_shown_once_asked_for() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    made = store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)["newTabId"]

    store.show_tab(view_id=MAC, tab_id=made)

    assert _restarted().snapshot(view_id=MAC)["activeTabId"] == made


# Case 4: the context shown is deleted.
def test_deleting_the_context_shown_shows_the_one_the_server_picks() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.show_tab(view_id=MAC, tab_id=second)

    answer = store.delete_tab(view_id=MAC, tab_id=second)

    assert answer["activeTabId"] == first


# Case 5: a reference page is shown, kept on reload, and Back shows its search.
def test_a_reference_page_is_shown_and_back_shows_its_search() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)

    page = _open_page(store, MAC, first)

    assert _restarted().snapshot(view_id=MAC)["activeTabId"] == page
    store.show_tab(view_id=MAC, tab_id=first)
    assert store.snapshot(view_id=MAC)["activeTabId"] == first


# Case 6: a page's notes are all deleted.
def test_a_page_closed_with_its_notes_gives_way_to_its_search() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    _open_page(store, MAC, first)

    store.close_pages_whose_notes_are_gone(note_exists=lambda _note_id: False)

    assert store.snapshot(view_id=MAC)["activeTabId"] == first


# Case 7: each view shows its own context.
def test_a_context_shown_in_one_view_moves_no_other_view() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.show_tab(view_id=PHONE, tab_id=first)

    store.show_tab(view_id=MAC, tab_id=second)

    assert store.snapshot(view_id=PHONE)["activeTabId"] == first
    assert store.snapshot(view_id=MAC)["activeTabId"] == second


# Case 8: another view deletes the context shown here.
def test_a_context_deleted_elsewhere_gives_way_to_one_the_server_picks() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.show_tab(view_id=PHONE, tab_id=second)

    store.delete_tab(view_id=MAC, tab_id=second)

    assert store.snapshot(view_id=PHONE)["activeTabId"] == first


# Case 9: a new view starts on the context used most recently.
def test_a_new_view_starts_on_the_context_shown_most_recently() -> None:
    store = TabStateStore()
    _first, second = _two_contexts(store)

    store.show_tab(view_id=MAC, tab_id=second)

    assert store.snapshot(view_id=NEW_VIEW)["activeTabId"] == second


def test_a_new_view_starts_on_the_search_of_a_page_shown_most_recently() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.show_tab(view_id=MAC, tab_id=second)
    store.show_tab(view_id=MAC, tab_id=first)

    _open_page(store, MAC, first)

    assert store.snapshot(view_id=NEW_VIEW)["activeTabId"] == first


# Case 10: a copy read before a switch is saved after it.
def test_a_copy_read_before_a_switch_never_moves_the_view_back() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    copy_showing_the_first = store.snapshot(view_id=MAC)

    store.show_tab(view_id=MAC, tab_id=second)
    copy_showing_the_first["tabs"][first]["scrollY"] = SCROLLED
    answer = _save_copy(store, MAC, copy_showing_the_first)

    assert answer["activeTabId"] == second
    assert answer["tabs"][first]["scrollY"] == SCROLLED


# Case 11: the context asked for was deleted a moment ago.
def test_a_context_deleted_meanwhile_changes_nothing() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.delete_tab(view_id=PHONE, tab_id=second)

    answer = store.show_tab(view_id=MAC, tab_id=second)

    assert answer["changed"] is False
    assert answer["activeTabId"] == first


# Case 12: another view's reference page.
def test_another_views_reference_page_is_refused() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    page = _open_page(store, PHONE, first)

    with pytest.raises(InputRejected):
        store.show_tab(view_id=MAC, tab_id=page)


def test_a_tab_the_server_never_had_is_refused() -> None:
    store = TabStateStore()
    _two_contexts(store)

    with pytest.raises(InputRejected):
        store.show_tab(view_id=MAC, tab_id=NO_SUCH_TAB)


def test_showing_the_context_already_shown_changes_nothing() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    version = store.snapshot(view_id=MAC)["version"]

    answer = store.show_tab(view_id=MAC, tab_id=first)

    assert answer["changed"] is False
    assert answer["version"] == version
