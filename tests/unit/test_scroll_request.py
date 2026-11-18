"""The server takes a view's scroll in a tab by name (docs/future-plans/one-writer-refactoring.md,
idea 1). A view says "my scroll in tab X is now here" (TabStateStore.set_scroll); the server
takes no copy of a view's tabs, so nothing else changes a scroll.
The cases agreed 2026-11-17 are numbered in the comments."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import edit_locks
from app.services.input_errors import InputRejected
from app.services.root_date_filter import DATE_RANGE_TODAY, OPEN_DATE, make_root_date_filter
from app.services.root_sorting import SORT_MODE_CREATED
from app.services.tab_state import TabStateStore
from tests.unit.tab_place_saving import save_as_the_page_does

MAC = "10000000-0000-4000-8000-0000000000e1"
PHONE = "10000000-0000-4000-8000-0000000000e2"
NO_SUCH_TAB = "10000000-0000-4000-8000-0000000000e3"
NOTE = "20000000-0000-4000-8000-0000000000e4"
SCROLLED = 480
SCROLLED_ELSEWHERE = 960
INTO_THE_NOTE = 12


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
    """Search contexts groceries and recipes, the Mac showing groceries."""
    groceries = store.snapshot(view_id=MAC)["activeTabId"]
    recipes = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=False)["newTabId"]
    store.show_tab(view_id=MAC, tab_id=groceries)
    store.snapshot(view_id=PHONE)
    return groceries, recipes


def _scroll_at(scroll_y: int) -> dict:
    return {"scrollY": scroll_y, "anchorRootId": None, "scrollAnchor": None}


def _scroll(store: TabStateStore, view: str, tab_id: str, scroll_y: int) -> dict:
    """The view scrolls a tab, having heard everything the server holds."""
    version = store.snapshot(view_id=view)["version"]
    return store.set_scroll(view_id=view, tab_id=tab_id, scroll=_scroll_at(scroll_y), read_at_version=version)


def _scroll_of(store: TabStateStore, view: str, tab_id: str) -> int:
    return store.snapshot(view_id=view)["tabs"][tab_id]["scrollY"]


def _restarted() -> TabStateStore:
    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:scroll_request"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    return restarted


# Case 1: scroll in a context, reload.
def test_a_scroll_is_answered_and_survives_a_restart() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)

    answer = _scroll(store, MAC, groceries, SCROLLED)

    assert answer["changed"] is True
    assert answer["tabs"][groceries]["scrollY"] == SCROLLED
    assert _scroll_of(_restarted(), MAC, groceries) == SCROLLED


def test_a_scroll_keeps_the_note_it_is_anchored_to() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    anchor = {
        "anchorId": NOTE, "anchorBias": "top", "intraOffset": INTO_THE_NOTE,
        "beltPrev": [], "beltNext": [], "anchorSortKey": {"domIndex": 0},
    }
    scroll = {"scrollY": SCROLLED, "anchorRootId": NOTE, "scrollAnchor": anchor}
    version = store.snapshot(view_id=MAC)["version"]

    store.set_scroll(view_id=MAC, tab_id=groceries, scroll=scroll, read_at_version=version)

    kept = _restarted().snapshot(view_id=MAC)["tabs"][groceries]
    assert kept["anchorRootId"] == NOTE
    assert kept["scrollAnchor"]["anchorId"] == NOTE
    assert kept["scrollAnchor"]["intraOffset"] == INTO_THE_NOTE


# Case 2: scroll in groceries, show recipes, come back.
def test_each_context_keeps_its_own_scroll() -> None:
    store = TabStateStore()
    groceries, recipes = _two_contexts(store)
    _scroll(store, MAC, groceries, SCROLLED)

    store.show_tab(view_id=MAC, tab_id=recipes)
    _scroll(store, MAC, recipes, SCROLLED_ELSEWHERE)
    store.show_tab(view_id=MAC, tab_id=groceries)

    assert _scroll_of(store, MAC, groceries) == SCROLLED
    assert _scroll_of(store, MAC, recipes) == SCROLLED_ELSEWHERE


# Case 3: two views scroll the same context.
def test_each_view_keeps_its_own_scroll() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)

    _scroll(store, MAC, groceries, SCROLLED)
    _scroll(store, PHONE, groceries, SCROLLED_ELSEWHERE)

    assert _scroll_of(store, MAC, groceries) == SCROLLED
    assert _scroll_of(store, PHONE, groceries) == SCROLLED_ELSEWHERE


def test_a_scroll_is_no_news_to_the_other_views() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    revision = store.shared_revision(view_id=PHONE)

    _scroll(store, MAC, groceries, SCROLLED)

    assert store.shared_revision(view_id=PHONE) == revision


def _change_sort(store: TabStateStore, tab_id: str) -> None:
    store.set_sort_mode(view_id=PHONE, tab_id=tab_id, sort_mode=SORT_MODE_CREATED)


def _change_date_range(store: TabStateStore, tab_id: str) -> None:
    today = make_root_date_filter(field="created", range_kind=DATE_RANGE_TODAY, from_date=OPEN_DATE, to_date=OPEN_DATE)
    store.set_date_filter(view_id=PHONE, tab_id=tab_id, date_filter=today)


def _change_files_filter(store: TabStateStore, tab_id: str) -> None:
    store.set_file_filter(view_id=PHONE, tab_id=tab_id, file_filter=".pdf")


def _change_untagged(store: TabStateStore, tab_id: str) -> None:
    store.set_untagged_view(view_id=PHONE, tab_id=tab_id, is_untagged_view=True)


def _change_folder(store: TabStateStore, tab_id: str) -> None:
    store.choose_folder(view_id=PHONE, tab_id=tab_id, folder="work/", adds=False)


# A search typed is not among them: the server restarts no scroll for it, and the page that typed
# it sends its own scroll, at the top (test_a_search_typed_leaves_the_scroll_to_the_page).
_CHANGES_OF_THE_NOTES_SHOWN = [
    _change_sort, _change_date_range, _change_files_filter, _change_untagged, _change_folder,
]


# Case 4: a change of what a context shows starts its scroll at the top, in every view.
@pytest.mark.parametrize("change", _CHANGES_OF_THE_NOTES_SHOWN, ids=lambda change: change.__name__.lstrip("_"))
def test_a_change_of_the_notes_shown_starts_the_scroll_at_the_top(change: Callable[[TabStateStore, str], None]) -> None:
    store = TabStateStore()
    groceries, recipes = _two_contexts(store)
    _scroll(store, MAC, groceries, SCROLLED)
    _scroll(store, PHONE, groceries, SCROLLED_ELSEWHERE)
    _scroll(store, MAC, recipes, SCROLLED)

    change(store, groceries)

    assert _scroll_of(store, MAC, groceries) == 0
    assert _scroll_of(store, PHONE, groceries) == 0
    assert _scroll_of(store, MAC, recipes) == SCROLLED


# Case 5: a scroll measured before that change reaches the server after it.
@pytest.mark.parametrize("change", _CHANGES_OF_THE_NOTES_SHOWN, ids=lambda change: change.__name__.lstrip("_"))
def test_a_scroll_measured_before_the_notes_changed_is_not_taken(change: Callable[[TabStateStore, str], None]) -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    heard_at = store.snapshot(view_id=MAC)["version"]
    change(store, groceries)
    version = store.snapshot(view_id=MAC)["version"]

    answer = store.set_scroll(view_id=MAC, tab_id=groceries, scroll=_scroll_at(SCROLLED), read_at_version=heard_at)

    assert answer["changed"] is False
    assert answer["version"] == version
    assert _scroll_of(store, MAC, groceries) == 0
    # Measured once the view heard of the change, it is taken.
    assert _scroll(store, MAC, groceries, SCROLLED)["changed"] is True


def test_a_search_typed_leaves_the_scroll_to_the_page() -> None:
    # As before this request existed (found while building it, 2026-11-17).
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    _scroll(store, MAC, groceries, SCROLLED)

    store.set_search(view_id=MAC, tab_id=groceries, search_query="milk")

    assert _scroll_of(store, MAC, groceries) == SCROLLED
    assert _scroll(store, MAC, groceries, 0)["changed"] is True


# Case 6: scroll in a context another view deleted a moment ago.
def test_a_scroll_in_a_context_deleted_meanwhile_changes_nothing() -> None:
    store = TabStateStore()
    groceries, recipes = _two_contexts(store)
    heard_at = store.snapshot(view_id=MAC)["version"]
    store.delete_tab(view_id=PHONE, tab_id=recipes)

    answer = store.set_scroll(view_id=MAC, tab_id=recipes, scroll=_scroll_at(SCROLLED), read_at_version=heard_at)

    assert answer["changed"] is False
    assert answer["tabOrder"] == [groceries]


# Case 7: a scroll that has not changed.
def test_a_scroll_set_to_what_it_is_changes_nothing() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    _scroll(store, MAC, groceries, SCROLLED)
    version = store.snapshot(view_id=MAC)["version"]

    answer = _scroll(store, MAC, groceries, SCROLLED)

    assert answer["changed"] is False
    assert answer["version"] == version


def test_a_scroll_at_the_top_of_a_context_never_scrolled_changes_nothing() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    version = store.snapshot(view_id=MAC)["version"]

    answer = _scroll(store, MAC, groceries, 0)

    assert answer["changed"] is False
    assert answer["version"] == version


# Case 8: duplicate a context.
def test_a_duplicate_starts_at_the_scroll_of_the_original() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    _scroll(store, MAC, groceries, SCROLLED)

    duplicate = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=True, is_page=False)

    assert duplicate["tabs"][duplicate["newTabId"]]["scrollY"] == SCROLLED


# Case 9: scroll in a reference page of this view, reload.
def test_a_scroll_in_this_views_reference_page_survives_a_restart() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    page = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=True)["newTabId"]

    _scroll(store, MAC, page, SCROLLED)

    assert _scroll_of(_restarted(), MAC, page) == SCROLLED


# Case 12: a tab the server never had, another view's reference page, or no position.
def test_a_scroll_for_a_tab_the_server_never_had_is_refused() -> None:
    store = TabStateStore()
    _two_contexts(store)

    with pytest.raises(InputRejected):
        _scroll(store, MAC, NO_SUCH_TAB, SCROLLED)


def test_another_views_reference_page_takes_no_scroll_from_this_view() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    page = store.create_tab(view_id=PHONE, copy_from_tab_id=groceries, copies_view=False, is_page=True)["newTabId"]

    with pytest.raises(InputRejected):
        _scroll(store, MAC, page, SCROLLED)


@pytest.mark.parametrize("position", [-1, "480", None, 480.5])
def test_a_scroll_that_is_no_position_is_refused(position: object) -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)
    version = store.snapshot(view_id=MAC)["version"]

    with pytest.raises(InputRejected):
        store.set_scroll(view_id=MAC, tab_id=groceries, scroll=_scroll_at(position), read_at_version=version)

    assert _scroll_of(store, MAC, groceries) == 0


def test_a_scroll_naming_no_version_is_refused() -> None:
    store = TabStateStore()
    groceries, _recipes = _two_contexts(store)

    with pytest.raises(InputRejected):
        store.set_scroll(view_id=MAC, tab_id=groceries, scroll=_scroll_at(SCROLLED), read_at_version=-1)
