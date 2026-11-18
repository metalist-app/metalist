"""The server owns the order of the tabs (docs/future-plans/one-writer-refactoring.md, idea 1). A
view says "move tab X to where tab Y is" (TabStateStore.move_tab); the save of its whole copy of
the tabs (update) carries scroll and reference pages, and never an order the server takes. The
cases agreed 2026-11-17 are numbered in the comments."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import edit_locks
from app.services.input_errors import InputRejected
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000c1"
PHONE = "10000000-0000-4000-8000-0000000000c2"
NO_SUCH_TAB = "10000000-0000-4000-8000-0000000000c3"
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


def _new_tab(store: TabStateStore, view: str, *, is_page: bool) -> str:
    first = store.snapshot(view_id=view)["tabOrder"][0]
    return store.create_tab(view_id=view, copy_from_tab_id=first, copies_view=False, is_page=is_page)["newTabId"]


def _three_contexts(store: TabStateStore) -> tuple[str, str, str]:
    """Search contexts groceries, recipes and travel, in that order, the Mac showing groceries."""
    groceries = store.snapshot(view_id=MAC)["activeTabId"]
    recipes = _new_tab(store, MAC, is_page=False)
    travel = _new_tab(store, MAC, is_page=False)
    store.show_tab(view_id=MAC, tab_id=groceries)
    store.snapshot(view_id=PHONE)
    return groceries, recipes, travel


def _order(store: TabStateStore, view: str) -> list[str]:
    return store.snapshot(view_id=view)["tabOrder"]


def _save_copy(store: TabStateStore, view: str, copy: dict) -> dict:
    return store.update(
        view_id=view, tabs=copy["tabs"], tab_order=copy["tabOrder"],
        reference_views=copy["referenceViews"], read_at_version=copy["version"],
    )


def _restarted() -> TabStateStore:
    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:move_context_request"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    return restarted


# Case 1: drag a context down onto another, reload.
def test_a_context_moved_down_takes_the_others_place_and_survives_a_restart() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)

    answer = store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=recipes)

    assert answer["changed"] is True
    assert answer["tabOrder"] == [recipes, groceries, travel]
    assert _order(_restarted(), MAC) == [recipes, groceries, travel]


def test_a_context_moved_down_past_several_lands_after_the_one_it_was_dropped_on() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)

    assert store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=travel)["tabOrder"] == [recipes, travel, groceries]


# Case 2: drag a context up onto another, reload.
def test_a_context_moved_up_takes_the_others_place_and_survives_a_restart() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)

    answer = store.move_tab(view_id=MAC, tab_id=travel, to_tab_id=groceries)

    assert answer["changed"] is True
    assert answer["tabOrder"] == [travel, groceries, recipes]
    assert _order(_restarted(), MAC) == [travel, groceries, recipes]


# Case 3: drop a context on itself, or drag with only one context.
def test_a_context_dropped_on_itself_changes_nothing() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    version = store.snapshot(view_id=MAC)["version"]

    answer = store.move_tab(view_id=MAC, tab_id=recipes, to_tab_id=recipes)

    assert answer["changed"] is False
    assert answer["version"] == version
    assert answer["tabOrder"] == [groceries, recipes, travel]


def test_the_only_context_dropped_on_itself_changes_nothing() -> None:
    store = TabStateStore()
    only = store.snapshot(view_id=MAC)["activeTabId"]

    answer = store.move_tab(view_id=MAC, tab_id=only, to_tab_id=only)

    assert answer["changed"] is False
    assert answer["tabOrder"] == [only]


# Case 4: two views; move a context in one.
def test_a_move_shows_in_the_other_view() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    revision = store.shared_revision(view_id=PHONE)
    version = store.snapshot(view_id=PHONE)["version"]

    store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=recipes)

    assert _order(store, PHONE) == [recipes, groceries, travel]
    assert store.shared_revision(view_id=PHONE) > revision
    assert store.snapshot(view_id=PHONE)["version"] > version


# Case 5: a view saves its scroll with the old order, after another view moved a context.
def test_a_copy_holding_the_old_order_never_puts_it_back() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    copy_with_the_old_order = store.snapshot(view_id=MAC)

    store.move_tab(view_id=PHONE, tab_id=groceries, to_tab_id=travel)
    copy_with_the_old_order["tabs"][groceries]["scrollY"] = SCROLLED
    _save_copy(store, MAC, copy_with_the_old_order)

    assert _order(store, MAC) == [recipes, travel, groceries]
    assert store.snapshot(view_id=MAC)["tabs"][groceries]["scrollY"] == SCROLLED


def test_an_order_in_a_saved_copy_is_never_taken() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)

    copy = store.snapshot(view_id=MAC)
    copy["tabOrder"] = [travel, recipes, groceries]
    _save_copy(store, MAC, copy)

    assert _order(store, MAC) == [groceries, recipes, travel]


# Case 6: two views each move a different context at nearly the same time, neither having heard
# of the other's move.
def test_two_views_moves_both_apply() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    notes = _new_tab(store, MAC, is_page=False)

    store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=recipes)
    store.move_tab(view_id=PHONE, tab_id=notes, to_tab_id=travel)

    assert _order(store, MAC) == [recipes, groceries, notes, travel]
    assert _order(store, PHONE) == [recipes, groceries, notes, travel]


# Case 7: move a context while another view has made one this view has not heard of.
def test_a_context_made_elsewhere_keeps_its_place_at_the_end() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    made_on_the_phone = _new_tab(store, PHONE, is_page=False)

    answer = store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=travel)

    assert answer["tabOrder"] == [recipes, travel, groceries, made_on_the_phone]


# Case 8: move a context, or onto a context, that another view deleted a moment ago.
@pytest.mark.parametrize("deleted_is_the_one_moved", [True, False])
def test_a_move_with_a_context_deleted_meanwhile_changes_nothing(deleted_is_the_one_moved: bool) -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    store.delete_tab(view_id=PHONE, tab_id=travel)
    version = store.snapshot(view_id=MAC)["version"]

    if deleted_is_the_one_moved:
        answer = store.move_tab(view_id=MAC, tab_id=travel, to_tab_id=groceries)
    else:
        answer = store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=travel)

    assert answer["changed"] is False
    assert answer["version"] == version
    assert answer["tabOrder"] == [groceries, recipes]


# Case 9: move a context while views have reference pages open.
def test_reference_pages_stay_with_their_view_and_keep_their_place() -> None:
    store = TabStateStore()
    groceries = store.snapshot(view_id=MAC)["activeTabId"]
    store.snapshot(view_id=PHONE)
    mac_page = _new_tab(store, MAC, is_page=True)
    recipes = _new_tab(store, MAC, is_page=False)
    phone_page = _new_tab(store, PHONE, is_page=True)
    travel = _new_tab(store, MAC, is_page=False)
    assert _order(store, MAC) == [groceries, mac_page, recipes, travel]
    assert _order(store, PHONE) == [groceries, recipes, phone_page, travel]

    store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=travel)

    assert _order(store, MAC) == [mac_page, recipes, travel, groceries]
    assert _order(store, PHONE) == [recipes, phone_page, travel, groceries]

    store.move_tab(view_id=PHONE, tab_id=travel, to_tab_id=recipes)

    assert _order(store, MAC) == [mac_page, travel, recipes, groceries]
    assert _order(store, PHONE) == [travel, recipes, phone_page, groceries]
    assert _order(_restarted(), PHONE) == [travel, recipes, phone_page, groceries]


# Case 10: a move changes neither the context shown nor any scroll.
def test_a_move_leaves_the_context_shown_and_its_scroll() -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    copy = store.snapshot(view_id=MAC)
    copy["tabs"][groceries]["scrollY"] = SCROLLED
    _save_copy(store, MAC, copy)
    before = store.snapshot(view_id=MAC)

    after = store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=travel)

    assert after["activeTabId"] == before["activeTabId"] == groceries
    assert after["tabs"] == before["tabs"]
    assert store.snapshot(view_id=PHONE)["activeTabId"] == groceries


# Case 11: a tab the server never had, or another view's reference page.
@pytest.mark.parametrize("unknown_is_the_one_moved", [True, False])
def test_a_move_with_a_tab_the_server_never_had_is_refused(unknown_is_the_one_moved: bool) -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)

    with pytest.raises(InputRejected):
        if unknown_is_the_one_moved:
            store.move_tab(view_id=MAC, tab_id=NO_SUCH_TAB, to_tab_id=groceries)
        else:
            store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=NO_SUCH_TAB)

    assert _order(store, MAC) == [groceries, recipes, travel]


@pytest.mark.parametrize("page_is_the_one_moved", [True, False])
def test_a_move_with_another_views_reference_page_is_refused(page_is_the_one_moved: bool) -> None:
    store = TabStateStore()
    groceries, recipes, travel = _three_contexts(store)
    phone_page = _new_tab(store, PHONE, is_page=True)

    with pytest.raises(InputRejected):
        if page_is_the_one_moved:
            store.move_tab(view_id=MAC, tab_id=phone_page, to_tab_id=groceries)
        else:
            store.move_tab(view_id=MAC, tab_id=groceries, to_tab_id=phone_page)

    assert _order(store, PHONE) == [groceries, recipes, travel, phone_page]
