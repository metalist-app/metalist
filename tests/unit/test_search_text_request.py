"""The server owns each search context's search (docs/future-plans/one-writer-refactoring.md,
idea 1). A view says "the search of context X is now Y" (TabStateStore.set_search); the save of a
view's whole copy of its tabs (update) carries scroll, order and the context shown, and never a
search. The cases agreed 2026-11-17 are numbered in the test names' comments."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import SearchLockedElsewhere, edit_locks
from app.services.input_errors import InputRejected
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000a1"
PHONE = "10000000-0000-4000-8000-0000000000a2"
NO_SUCH_TAB = "10000000-0000-4000-8000-0000000000a3"
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
    first = store.snapshot(view_id=MAC)["activeTabId"]
    second = store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)["newTabId"]
    return first, second


def _save_copy(store: TabStateStore, view: str, copy: dict) -> dict:
    """The whole copy of its tabs a view holds, saved as the browser saves it."""
    return store.update(
        view_id=view, active_tab_id=copy["activeTabId"], tabs=copy["tabs"], tab_order=copy["tabOrder"],
        reference_views=copy["referenceViews"], read_at_version=copy["version"],
    )


def _restarted() -> TabStateStore:
    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:search_text_request"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    return restarted


# Case 1: type a search, reload.
def test_a_search_set_is_answered_and_survives_a_restart() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)

    answer = store.set_search(view_id=MAC, tab_id=first, search_query="groceries")

    assert answer["changed"] is True
    assert answer["tabs"][first]["searchQuery"] == "groceries"
    assert _restarted().snapshot(view_id=MAC)["tabs"][first]["searchQuery"] == "groceries"


# Case 2: type in one context, show another and come back.
def test_a_search_stays_with_its_context_when_another_is_shown() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")

    copy = store.snapshot(view_id=MAC)
    copy["activeTabId"] = second
    _save_copy(store, MAC, copy)

    now = store.snapshot(view_id=MAC)
    assert now["activeTabId"] == second
    assert now["tabs"][first]["searchQuery"] == "groceries"
    assert now["tabs"][second]["searchQuery"] == ""


# Case 3: clear the search, reload.
def test_a_cleared_search_stays_cleared() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")

    store.set_search(view_id=MAC, tab_id=first, search_query="")

    assert _restarted().snapshot(view_id=MAC)["tabs"][first]["searchQuery"] == ""


# Case 4: a search opened in a new context.
def test_a_new_context_takes_its_search() -> None:
    store = TabStateStore()
    _first, second = _two_contexts(store)

    store.set_search(view_id=MAC, tab_id=second, search_query="#recipes")

    assert _restarted().snapshot(view_id=MAC)["tabs"][second]["searchQuery"] == "#recipes"


# Case 5: Rename tag renames a search; a copy read before the rename is saved after it.
def test_a_copy_saved_after_a_rename_keeps_the_new_name() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=first, search_query="#old")
    copy = store.snapshot(view_id=MAC)

    session = SafeSession()
    store.rename_search_terms(rename=lambda search: search.replace("#old", "#new"), connection=session.connection())
    session.close()
    copy["tabs"][first]["scrollY"] = SCROLLED
    _save_copy(store, MAC, copy)

    assert store.get_search_query(tab_id=first) == "#new"


# Case 6: a second view types in a context.
def test_another_views_search_is_shown_and_its_typing_refuses_this_views() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    edit_locks.heard_from(view_id=PHONE, token="phone-sign-in", user_agent="iPhone")
    store.snapshot(view_id=PHONE)

    store.set_search(view_id=PHONE, tab_id=first, search_query="groceries")

    assert store.snapshot(view_id=MAC)["tabs"][first]["searchQuery"] == "groceries"
    with pytest.raises(SearchLockedElsewhere):
        store.set_search(view_id=MAC, tab_id=first, search_query="other")
    assert store.get_search_query(tab_id=first) == "groceries"


# Case 7: more is typed while an earlier save is on its way.
def test_a_copy_holding_earlier_typing_never_puts_it_back() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=first, search_query="gro")
    copy_with_earlier_typing = store.snapshot(view_id=MAC)

    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")
    _save_copy(store, MAC, copy_with_earlier_typing)

    assert store.get_search_query(tab_id=first) == "groceries"


# Case 8: one view scrolls while another changed the search. The copy's own search is no
# request, whatever the view was told before.
def test_a_search_in_a_saved_copy_is_never_taken() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")

    copy = store.snapshot(view_id=PHONE)
    copy["tabs"][first]["searchQuery"] = "something the phone never asked for"
    copy["tabs"][first]["scrollY"] = SCROLLED
    _save_copy(store, PHONE, copy)

    assert store.get_search_query(tab_id=first) == "groceries"
    assert store.snapshot(view_id=PHONE)["tabs"][first]["scrollY"] == SCROLLED


def test_a_search_set_to_what_it_is_changes_nothing() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")
    version = store.snapshot(view_id=MAC)["version"]

    answer = store.set_search(view_id=MAC, tab_id=first, search_query="groceries")

    assert answer["changed"] is False
    assert answer["version"] == version


def test_a_search_for_a_context_that_is_gone_is_refused() -> None:
    store = TabStateStore()
    _two_contexts(store)

    with pytest.raises(InputRejected):
        store.set_search(view_id=MAC, tab_id=NO_SUCH_TAB, search_query="groceries")


def test_a_search_for_a_context_deleted_meanwhile_changes_nothing() -> None:
    # Found 2026-11-17 (live-changes suite): a search typed just before another view deleted its
    # context was refused, and the page showed an error for a context the user no longer has.
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.delete_tab(view_id=PHONE, tab_id=second)

    answer = store.set_search(view_id=MAC, tab_id=second, search_query="groceries")

    assert answer["changed"] is False
    assert answer["tabOrder"] == [first]


def test_another_views_reference_page_takes_no_search_from_this_view() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    page = store.create_tab(view_id=PHONE, copy_from_tab_id=first, copies_view=False, is_page=True)["newTabId"]

    with pytest.raises(InputRejected):
        store.set_search(view_id=MAC, tab_id=page, search_query="groceries")
