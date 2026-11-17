"""Every change a view can see in its tabs raises the tab state's version.

The page relies on it (tab-state-service.js, fetchTabStateNotOvertaken): of two answers it holds,
the one with the higher version is the newer, so a reading of the tabs answered late is not taken
over a change made since (docs/future-plans/one-writer-refactoring.md, idea 1; agreed 2026-11-17).
Each change the store offers is made here, and the views' tabs compared before and after."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import edit_locks
from app.services.root_date_filter import DATE_RANGE_TODAY, make_root_date_filter
from app.services.root_date_filter import OPEN_DATE
from app.services.root_sorting import SORT_MODE_CREATED
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000b1"
PHONE = "10000000-0000-4000-8000-0000000000b2"
NOTE = "20000000-0000-4000-8000-0000000000b3"
SCROLLED = 480
# What a view shows of its tabs; the rest of an answer is not the tabs (the version itself, who
# is typing a search, and the number the views compare their shared contexts by).
_NOT_THE_TABS = ("version", "searchLocks", "searchContextsRevision")


@pytest.fixture(autouse=True)
def _memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    edit_locks.reset()
    yield
    edit_locks.reset()
    SafeSession.use_file_db()


def _tabs_shown(store: TabStateStore) -> dict:
    shown = {}
    for view in (MAC, PHONE):
        answer = store.snapshot(view_id=view)
        shown[view] = {key: value for key, value in answer.items() if key not in _NOT_THE_TABS}
    return shown


def _save_copy(store: TabStateStore, view: str, change: Callable[[dict], None]) -> None:
    copy = store.snapshot(view_id=view)
    change(copy)
    # The tab shown is asked for by name; the copy carries the rest.
    store.show_tab(view_id=view, tab_id=copy["activeTabId"])
    store.update(
        view_id=view, tabs=copy["tabs"], tab_order=copy["tabOrder"],
        reference_views=copy["referenceViews"], read_at_version=copy["version"],
    )


def _set_search(store: TabStateStore, first: str, _second: str) -> None:
    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")


def _set_sort(store: TabStateStore, first: str, _second: str) -> None:
    store.set_sort_mode(view_id=MAC, tab_id=first, sort_mode=SORT_MODE_CREATED)


def _set_date_range(store: TabStateStore, first: str, _second: str) -> None:
    today = make_root_date_filter(field="created", range_kind=DATE_RANGE_TODAY, from_date=OPEN_DATE, to_date=OPEN_DATE)
    store.set_date_filter(view_id=MAC, tab_id=first, date_filter=today)


def _set_files_filter(store: TabStateStore, first: str, _second: str) -> None:
    store.set_file_filter(view_id=MAC, tab_id=first, file_filter=".pdf")


def _set_untagged(store: TabStateStore, first: str, _second: str) -> None:
    store.set_untagged_view(view_id=MAC, tab_id=first, is_untagged_view=True)


def _show_tree(store: TabStateStore, _first: str, _second: str) -> None:
    shown = store.snapshot(view_id=MAC)["treeShown"]
    store.set_tree_shown(view_id=MAC, is_shown=not shown)


def _choose_folder(store: TabStateStore, first: str, _second: str) -> None:
    store.choose_folder(view_id=MAC, tab_id=first, folder="work/", adds=False)


def _new_context(store: TabStateStore, first: str, _second: str) -> None:
    store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)


def _new_page(store: TabStateStore, first: str, _second: str) -> None:
    store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=True)


def _delete_context(store: TabStateStore, _first: str, second: str) -> None:
    store.delete_tab(view_id=MAC, tab_id=second)


def _show_another_context(store: TabStateStore, _first: str, second: str) -> None:
    def show(copy: dict) -> None:
        copy["activeTabId"] = second
    _save_copy(store, MAC, show)


def _scroll(store: TabStateStore, first: str, _second: str) -> None:
    def scroll(copy: dict) -> None:
        copy["tabs"][first]["scrollY"] = SCROLLED
    _save_copy(store, MAC, scroll)


def _reorder(store: TabStateStore, _first: str, _second: str) -> None:
    def reorder(copy: dict) -> None:
        copy["tabOrder"] = list(reversed(copy["tabOrder"]))
    _save_copy(store, MAC, reorder)


def _rename_in_searches(store: TabStateStore, first: str, _second: str) -> None:
    store.set_search(view_id=PHONE, tab_id=first, search_query="#old")
    before = store.snapshot(view_id=MAC)["version"]
    session = SafeSession()
    store.rename_search_terms(rename=lambda search: search.replace("#old", "#new"), connection=session.connection())
    session.close()
    assert store.snapshot(view_id=MAC)["version"] > before, "the rename itself raises the version"


def _open_page(store: TabStateStore, context: str) -> str:
    page = store.create_tab(view_id=MAC, copy_from_tab_id=context, copies_view=False, is_page=True)["newTabId"]

    def follow(copy: dict) -> None:
        copy["tabs"][page]["searchQuery"] = NOTE
        copy["activeTabId"] = page
        copy["referenceViews"][page] = {
            "fromTabId": context, "referenceQuery": NOTE, "viewKind": "source",
            "originScope": {"scopeTabId": context, "searchQuery": "", "sortMode": "normal", "isUntaggedView": False},
        }
    _save_copy(store, MAC, follow)
    return page


_CHANGES = [
    _set_search, _set_sort, _set_date_range, _set_files_filter, _set_untagged, _show_tree, _choose_folder,
    _new_context, _new_page, _delete_context, _show_another_context, _scroll, _reorder, _rename_in_searches,
]


@pytest.mark.parametrize("change", _CHANGES, ids=lambda change: change.__name__.lstrip("_"))
def test_a_change_a_view_can_see_raises_the_version(change: Callable[[TabStateStore, str, str], None]) -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=MAC)["activeTabId"]
    second = store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)["newTabId"]
    _save_copy(store, MAC, lambda copy: copy.update(activeTabId=first))
    store.snapshot(view_id=PHONE)
    shown_before = _tabs_shown(store)
    version_before = store.snapshot(view_id=MAC)["version"]

    change(store, first, second)

    assert _tabs_shown(store) != shown_before, "the change shows in a view's tabs"
    assert store.snapshot(view_id=MAC)["version"] > version_before


@pytest.mark.parametrize("change", _CHANGES, ids=lambda change: change.__name__.lstrip("_"))
def test_the_version_never_goes_back(change: Callable[[TabStateStore, str, str], None]) -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=MAC)["activeTabId"]
    second = store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)["newTabId"]
    version_before = store.snapshot(view_id=MAC)["version"]

    change(store, first, second)
    version_after = store.snapshot(view_id=MAC)["version"]
    store.snapshot(view_id=PHONE)

    assert version_after >= version_before
    assert store.snapshot(view_id=PHONE)["version"] == version_after, "reading the tabs changes no version"


def test_a_page_closed_because_its_notes_are_gone_raises_the_version() -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=MAC)["activeTabId"]
    _open_page(store, first)
    shown_before = _tabs_shown(store)
    version_before = store.snapshot(view_id=MAC)["version"]

    assert store.close_pages_whose_notes_are_gone(note_exists=lambda _note_id: False) is True

    assert _tabs_shown(store) != shown_before
    assert store.snapshot(view_id=MAC)["version"] > version_before
