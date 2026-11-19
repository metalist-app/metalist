"""A request that names a search context another view deleted a moment ago changes nothing and
is no error (finding 4 of the tab-state simulation, docs/future-plans/one-writer-refactoring.md,
idea 2): the view's list catches up as it does for a search typed then. A tab the server never
had, and another view's reference page, are still refused. The cases agreed 2026-11-18 are
numbered in the comments."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import edit_locks
from app.services.input_errors import InputRejected
from app.services.root_date_filter import make_root_date_filter
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000d1"
PHONE = "10000000-0000-4000-8000-0000000000d2"
NO_SUCH_TAB = "10000000-0000-4000-8000-0000000000d3"

Request = Callable[[TabStateStore, str], Dict[str, object]]


@pytest.fixture(autouse=True)
def _memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    edit_locks.reset()
    yield
    edit_locks.reset()
    SafeSession.use_file_db()


def _october() -> object:
    return make_root_date_filter(field="created", range_kind="custom", from_date="2026-10-01", to_date="2026-10-22")


# Cases 1 to 7, each as the Mac asks it of one tab.
REQUESTS: Dict[str, Request] = {
    "sort order": lambda store, tab: store.set_sort_mode(view_id=MAC, tab_id=tab, sort_mode="created"),
    "date range": lambda store, tab: store.set_date_filter(view_id=MAC, tab_id=tab, date_filter=_october()),
    "Files filter": lambda store, tab: store.set_file_filter(view_id=MAC, tab_id=tab, file_filter="any"),
    "Untagged": lambda store, tab: store.set_untagged_view(view_id=MAC, tab_id=tab, is_untagged_view=True),
    "folder": lambda store, tab: store.choose_folder(view_id=MAC, tab_id=tab, folder="Projects/", adds=False),
    "delete": lambda store, tab: store.delete_tab(view_id=MAC, tab_id=tab),
    "duplicate": lambda store, tab: store.create_tab(view_id=MAC, copy_from_tab_id=tab, copies_view=True, is_page=False),
    "new context": lambda store, tab: store.create_tab(view_id=MAC, copy_from_tab_id=tab, copies_view=False, is_page=False),
}
every_request = pytest.mark.parametrize("request_name", list(REQUESTS))


def _three_contexts(store: TabStateStore) -> tuple[str, str, str]:
    """Search contexts groceries, recipes and travel; both views have heard of all three."""
    groceries = store.snapshot(view_id=MAC)["activeTabId"]
    recipes = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=False)["newTabId"]
    travel = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=False)["newTabId"]
    store.snapshot(view_id=PHONE)
    return groceries, recipes, travel


def _everything(store: TabStateStore) -> dict:
    return {view: store.snapshot(view_id=view) for view in (MAC, PHONE)}


# Cases 1 to 7: the phone deleted travel; the Mac, not having heard, asks about travel.
@every_request
def test_a_request_about_a_context_deleted_a_moment_ago_changes_nothing(request_name: str) -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    store.delete_tab(view_id=PHONE, tab_id=travel)
    before = _everything(store)

    answer = REQUESTS[request_name](store, travel)

    assert answer["changed"] is False
    assert answer["tabOrder"] == [groceries, recipes]
    assert "newTabId" not in answer
    assert _everything(store) == before


# Case 8: a tab the server never had.
@every_request
def test_a_request_about_a_tab_the_server_never_had_is_refused(request_name: str) -> None:
    store = TabStateStore()
    _three_contexts(store)
    before = _everything(store)

    with pytest.raises(InputRejected):
        REQUESTS[request_name](store, NO_SUCH_TAB)

    assert _everything(store) == before


# Case 9: the phone's reference page is never the Mac's to change.
@every_request
def test_a_request_about_another_views_reference_page_is_refused(request_name: str) -> None:
    store = TabStateStore()
    groceries, _recipes, _travel = _three_contexts(store)
    phone_page = store.create_tab(view_id=PHONE, copy_from_tab_id=groceries, copies_view=False, is_page=True)["newTabId"]
    before = _everything(store)

    with pytest.raises(InputRejected):
        REQUESTS[request_name](store, phone_page)

    assert _everything(store) == before


# Case 10: a context that is there.
@every_request
def test_a_request_about_a_context_that_is_there_is_taken(request_name: str) -> None:
    store = TabStateStore()
    _groceries, _recipes, travel = _three_contexts(store)
    version = store.snapshot(view_id=MAC)["version"]

    answer = REQUESTS[request_name](store, travel)

    assert answer["changed"] is True
    assert answer["version"] > version


# Case 11: the last remaining context.
def test_deleting_the_last_context_is_refused() -> None:
    store = TabStateStore()
    only = store.snapshot(view_id=MAC)["activeTabId"]

    with pytest.raises(InputRejected):
        store.delete_tab(view_id=MAC, tab_id=only)
