"""Each view has its own place in the shared search contexts (multi-view editing step 2,
docs/design/multi-view-editing.md §2 and §10): the context it shows, its scroll in each,
its reference pages and whether the folder tree shows. The contexts themselves, their searches,
orders and filters, are shared. A view is a browser tab or the installed phone app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services import tab_state as tab_state_module
from app.services.edit_locks import edit_locks
from app.services.input_errors import InputRejected
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000a1"
PHONE = "10000000-0000-4000-8000-0000000000a2"
NEW_TAB = "10000000-0000-4000-8000-0000000000a3"
NOTE = "20000000-0000-4000-8000-000000000001"
SCROLLED = 480
LONG_AGO_SECONDS = 365 * 24 * 60 * 60


@pytest.fixture(autouse=True)
def _memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    yield
    SafeSession.use_file_db()


def _save(store: TabStateStore, view: str, edit) -> dict:
    """The view's tabs as it has them, changed by `edit`, saved as the browser saves them."""
    state = store.snapshot(view_id=view)
    edit(state)
    return store.update(
        view_id=view, active_tab_id=state["activeTabId"], tabs=state["tabs"], tab_order=state["tabOrder"],
        reference_views=state["referenceViews"], read_at_version=state["version"],
    )


def _two_contexts(store: TabStateStore) -> tuple[str, str]:
    first = store.snapshot(view_id=MAC)["activeTabId"]
    second = store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)["newTabId"]
    return first, second


def _show(store: TabStateStore, view: str, tab_id: str) -> None:
    def edit(state: dict) -> None:
        state["activeTabId"] = tab_id
    _save(store, view, edit)


def test_each_view_shows_its_own_context_and_keeps_its_own_scroll() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.snapshot(view_id=PHONE)
    _show(store, MAC, second)

    def scroll(state: dict) -> None:
        state["tabs"][second]["scrollY"] = SCROLLED
    _save(store, MAC, scroll)

    assert store.snapshot(view_id=MAC)["activeTabId"] == second
    assert store.snapshot(view_id=PHONE)["activeTabId"] == first, "the phone stays where it was"
    assert store.snapshot(view_id=PHONE)["tabs"][second]["scrollY"] == 0, "scroll is never shared"
    assert store.snapshot(view_id=MAC)["tabs"][second]["scrollY"] == SCROLLED


def test_a_new_view_starts_on_the_context_used_most_recently() -> None:
    store = TabStateStore()
    _first, second = _two_contexts(store)
    _show(store, MAC, second)

    assert store.snapshot(view_id=NEW_TAB)["activeTabId"] == second


def test_the_contexts_and_their_searches_are_shared() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.snapshot(view_id=PHONE)

    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")

    phone = store.snapshot(view_id=PHONE)
    assert phone["tabOrder"] == [first, second]
    assert phone["tabs"][first]["searchQuery"] == "groceries"


def test_a_views_scroll_save_never_puts_back_a_search_another_view_changed() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    phone_had = store.snapshot(view_id=PHONE)

    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")
    # The phone saves its scroll with the tabs it read before the Mac's change.
    phone_had["tabs"][first]["scrollY"] = SCROLLED
    store.update(
        view_id=PHONE, active_tab_id=phone_had["activeTabId"], tabs=phone_had["tabs"],
        tab_order=phone_had["tabOrder"], reference_views=phone_had["referenceViews"],
        read_at_version=phone_had["version"],
    )

    assert store.get_search_query(tab_id=first) == "groceries"
    assert store.snapshot(view_id=PHONE)["tabs"][first]["scrollY"] == SCROLLED


def test_a_save_from_a_view_that_has_not_seen_a_new_context_keeps_it() -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=MAC)["activeTabId"]
    phone_had = store.snapshot(view_id=PHONE)
    added = store.create_tab(view_id=MAC, copy_from_tab_id=first, copies_view=False, is_page=False)["newTabId"]

    store.update(
        view_id=PHONE, active_tab_id=phone_had["activeTabId"], tabs=phone_had["tabs"],
        tab_order=phone_had["tabOrder"], reference_views=phone_had["referenceViews"],
        read_at_version=phone_had["version"],
    )

    assert store.snapshot(view_id=MAC)["tabOrder"] == [first, added]


def _open_page(store: TabStateStore, view: str, context: str) -> str:
    page = store.create_tab(view_id=view, copy_from_tab_id=context, copies_view=False, is_page=True)["newTabId"]

    def follow(state: dict) -> None:
        state["tabs"][page]["searchQuery"] = NOTE
        state["activeTabId"] = page
        state["referenceViews"][page] = {
            "fromTabId": context, "referenceQuery": NOTE, "viewKind": "source",
            "originScope": {"scopeTabId": context, "searchQuery": "", "sortMode": "normal", "isUntaggedView": False},
        }
    _save(store, view, follow)
    return page


def test_a_reference_page_belongs_to_the_view_that_opened_it() -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=MAC)["activeTabId"]
    store.snapshot(view_id=PHONE)

    page = _open_page(store, MAC, first)

    phone = store.snapshot(view_id=PHONE)
    assert page not in phone["tabs"] and page not in phone["tabOrder"]
    assert phone["referenceViews"] == {}
    assert phone["activeTabId"] == first, "the phone is not pulled along"
    assert store.snapshot(view_id=MAC)["activeTabId"] == page


def test_another_views_page_cannot_be_deleted_or_claimed() -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=MAC)["activeTabId"]
    page = _open_page(store, MAC, first)

    with pytest.raises(InputRejected):
        store.delete_tab(view_id=PHONE, tab_id=page)


def test_whether_the_folder_tree_shows_is_each_views_own() -> None:
    store = TabStateStore()
    store.snapshot(view_id=PHONE)

    store.set_tree_shown(view_id=MAC, is_shown=True)

    assert store.snapshot(view_id=MAC)["treeShown"] is True
    assert store.snapshot(view_id=PHONE)["treeShown"] is False


def test_a_context_deleted_in_one_view_moves_another_view_off_it() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    store.snapshot(view_id=PHONE)
    _show(store, PHONE, second)
    _show(store, MAC, first)

    store.delete_tab(view_id=MAC, tab_id=second)

    assert store.snapshot(view_id=PHONE)["activeTabId"] == first


def test_the_only_context_cannot_be_deleted_though_pages_are_open() -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=MAC)["activeTabId"]
    _open_page(store, MAC, first)

    with pytest.raises(InputRejected, match="last remaining"):
        store.delete_tab(view_id=MAC, tab_id=first)


def test_a_view_unused_for_weeks_is_forgotten_with_its_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=PHONE)["activeTabId"]
    page = _open_page(store, PHONE, first)
    now = tab_state_module.time()
    monkeypatch.setattr(tab_state_module, "time", lambda: now + LONG_AGO_SECONDS)

    store.snapshot(view_id=NEW_TAB)

    assert PHONE not in store._views
    assert page not in store.snapshot(view_id=NEW_TAB)["tabs"]


def test_a_place_survives_a_restart() -> None:
    store = TabStateStore()
    _first, second = _two_contexts(store)
    _show(store, MAC, second)
    store.set_tree_shown(view_id=MAC, is_shown=True)

    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:view_places"):
        restarted.bootstrap(connection=session.connection())
    session.close()

    again = restarted.snapshot(view_id=MAC)
    assert again["activeTabId"] == second
    assert again["treeShown"] is True


def test_tabs_saved_before_views_go_to_the_first_view_that_asks() -> None:
    # Saved by 0.30.0 and earlier: one place, its pages included.
    legacy = TabStateStore()
    legacy_state = json.loads((Path(__file__).parent.parent / "fixtures" / "upgrade" / "tab-state-v0.29.0.json").read_text())
    legacy._apply_snapshot_locked(legacy._deserialize_snapshot_json(json.dumps(legacy_state)))

    first_view = legacy.snapshot(view_id=MAC)
    second_view = legacy.snapshot(view_id=PHONE)

    assert first_view["activeTabId"] == legacy_state["activeTabId"]
    assert first_view["referenceViews"] == legacy_state["referenceViews"]
    assert second_view["referenceViews"] == {}
    assert not set(legacy_state["referenceViews"]) & set(second_view["tabs"]), "the pages are the first view's"


def test_a_tab_of_note_ids_saved_before_views_is_the_first_views_page_too() -> None:
    # 0.29.0 left a page whose search context closed as a tab of note ids no view record claimed
    # (the fixture's active tab): it must not become a shared context two views both adopt.
    legacy = TabStateStore()
    legacy_state = json.loads((Path(__file__).parent.parent / "fixtures" / "upgrade" / "tab-state-v0.29.0.json").read_text())
    orphan = legacy_state["activeTabId"]
    assert orphan not in legacy_state["referenceViews"]
    legacy._apply_snapshot_locked(legacy._deserialize_snapshot_json(json.dumps(legacy_state)))

    assert orphan in legacy.snapshot(view_id=MAC)["tabs"]
    assert orphan not in legacy.snapshot(view_id=PHONE)["tabs"]


# Multi-view editing step 3: the status carries a revision of what every view shares, so a view takes
# the search contexts again when another view changed them, and only then.

def test_the_shared_revision_rises_when_another_view_changes_a_contexts_search() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    before = store.shared_revision(view_id=MAC)

    store.set_search(view_id=PHONE, tab_id=first, search_query="groceries")

    assert store.shared_revision(view_id=MAC) > before


def test_the_shared_revision_rises_for_contexts_added_deleted_or_sorted() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    revisions = [store.shared_revision(view_id=MAC)]
    store.set_sort_mode(view_id=PHONE, tab_id=first, sort_mode="alphabetical")
    revisions.append(store.shared_revision(view_id=MAC))
    store.delete_tab(view_id=PHONE, tab_id=second)
    revisions.append(store.shared_revision(view_id=MAC))
    store.create_tab(view_id=PHONE, copy_from_tab_id=first, copies_view=False, is_page=False)
    revisions.append(store.shared_revision(view_id=MAC))

    assert revisions == sorted(set(revisions)), "each change raises it"


def test_the_shared_revision_stays_for_what_is_each_views_own() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    before = store.shared_revision(view_id=MAC)

    def scroll(state: dict) -> None:
        state["tabs"][first]["scrollY"] = SCROLLED
    _save(store, MAC, scroll)
    _show(store, MAC, second)
    store.set_tree_shown(view_id=MAC, is_shown=True)
    _open_page(store, MAC, first)

    assert store.shared_revision(view_id=MAC) == before


def test_a_view_saving_twice_never_puts_back_a_search_another_view_changed() -> None:
    # Found 2026-11-14: the answer to a view's first save told the store the view now had the
    # other view's search, though the browser keeps its own until it loads the tabs again; its next
    # save then counted its old search as a change and put it back.
    store = TabStateStore()
    first, _second = _two_contexts(store)
    phone_has = store.snapshot(view_id=PHONE)

    store.set_search(view_id=MAC, tab_id=first, search_query="groceries")
    for scrolled_to in (SCROLLED, SCROLLED + 1):
        phone_has["tabs"][first]["scrollY"] = scrolled_to
        store.update(
            view_id=PHONE, active_tab_id=phone_has["activeTabId"], tabs=phone_has["tabs"],
            tab_order=phone_has["tabOrder"], reference_views=phone_has["referenceViews"],
            read_at_version=phone_has["version"],
        )

    assert store.get_search_query(tab_id=first) == "groceries"
    # The phone's own search is asked for by name, whatever copy it holds.
    edit_locks.reset()
    store.set_search(view_id=PHONE, tab_id=first, search_query="plants")
    assert store.get_search_query(tab_id=first) == "plants"


def test_a_view_asks_for_a_search_after_the_store_loads_again() -> None:
    # Found 2026-11-14: a refused change reloads the store (request_recovery.py), and a view could
    # not change a search until it loaded its tabs again. A search asked for by name needs no
    # record of what the view holds.
    store = TabStateStore()
    first, _second = _two_contexts(store)
    _save(store, PHONE, lambda state: state["tabs"][first].update(scrollY=SCROLLED))

    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:view_places"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    restarted.set_search(view_id=PHONE, tab_id=first, search_query="groceries")

    assert restarted.get_search_query(tab_id=first) == "groceries"


def test_a_place_saved_by_0_30_1_with_its_record_of_searches_loads_without_it() -> None:
    # 0.30.0 and 0.30.1 saved, with each view's place, what its browser held of each search.
    store = TabStateStore()
    first = store.snapshot(view_id=PHONE)["activeTabId"]
    store.set_search(view_id=PHONE, tab_id=first, search_query="groceries")
    saved = json.loads(store._serialize_state_locked())
    assert "knownSearch" not in saved["views"][PHONE]
    saved["views"][PHONE]["knownSearch"] = {first: "groceries"}

    upgraded = TabStateStore()
    upgraded._load_state_json_locked(json.dumps(saved))

    assert upgraded.snapshot(view_id=PHONE)["tabs"][first]["searchQuery"] == "groceries"
    assert "knownSearch" not in json.loads(upgraded._serialize_state_locked())["views"][PHONE]


def test_after_the_store_loads_again_a_stale_save_still_keeps_another_views_search() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    phone_has = store.snapshot(view_id=PHONE)
    _save(store, PHONE, lambda state: state["tabs"][first].update(scrollY=SCROLLED))

    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:view_places"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    restarted.set_search(view_id=MAC, tab_id=first, search_query="groceries")
    phone_has["tabs"][first]["scrollY"] = SCROLLED + 1
    restarted.update(
        view_id=PHONE, active_tab_id=phone_has["activeTabId"], tabs=phone_has["tabs"],
        tab_order=phone_has["tabOrder"], reference_views=phone_has["referenceViews"],
        read_at_version=phone_has["version"],
    )

    assert restarted.get_search_query(tab_id=first) == "groceries"


# Found 2026-11-15: a view's own search lock (taken as its search box is typed in, released when
# the box is left) was part of what every view shares, with nothing telling the view the change
# was its own. Each time, the view took the contexts again a second later and drew its tab row
# anew, under whatever was clicked next (folder-context, Firefox, CI).
def test_a_views_own_search_lock_is_no_change_for_it() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    edit_locks.reset()
    edit_locks.heard_from(view_id=MAC, token="mac-sign-in", user_agent="Macintosh")
    before = store.shared_revision(view_id=MAC)

    edit_locks.note_search_typed(view_id=MAC, tab_id=first)
    while_typing = store.shared_revision(view_id=MAC)
    edit_locks.release_search(view_id=MAC)

    assert while_typing == before
    assert store.shared_revision(view_id=MAC) == before


def test_another_views_search_lock_is_a_change_taken_and_released() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    edit_locks.reset()
    edit_locks.heard_from(view_id=PHONE, token="phone-sign-in", user_agent="iPhone")
    before = store.shared_revision(view_id=MAC)

    edit_locks.note_search_typed(view_id=PHONE, tab_id=first)
    while_typed_there = store.shared_revision(view_id=MAC)
    edit_locks.release_search(view_id=PHONE)

    assert while_typed_there > before
    assert store.shared_revision(view_id=MAC) > while_typed_there


def test_a_save_says_whether_what_is_shared_changed_for_the_view_that_made_it() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    seen = store.shared_revision(view_id=MAC)

    saved = store.set_search(view_id=MAC, tab_id=first, search_query="groceries")

    assert saved["searchContextsRevision"]["before"] == seen
    assert saved["searchContextsRevision"]["after"] == store.shared_revision(view_id=MAC) > seen
