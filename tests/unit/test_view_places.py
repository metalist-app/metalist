"""Each view has its own place in the shared search contexts (multi-view editing step 2,
docs/ready-to-build/multi-view-editing.md §2 and §10): the context it shows, its scroll in each,
its reference pages and whether the folder tree shows. The contexts themselves, their searches,
orders and filters, are shared. A view is a browser tab or the installed phone app."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services import tab_state as tab_state_module
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

    def search(state: dict) -> None:
        state["tabs"][first]["searchQuery"] = "groceries"
    _save(store, MAC, search)

    phone = store.snapshot(view_id=PHONE)
    assert phone["tabOrder"] == [first, second]
    assert phone["tabs"][first]["searchQuery"] == "groceries"


def test_a_views_scroll_save_never_puts_back_a_search_another_view_changed() -> None:
    store = TabStateStore()
    first, _second = _two_contexts(store)
    phone_had = store.snapshot(view_id=PHONE)

    def search(state: dict) -> None:
        state["tabs"][first]["searchQuery"] = "groceries"
    _save(store, MAC, search)
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
    before = store.shared_revision()

    def search(state: dict) -> None:
        state["tabs"][first]["searchQuery"] = "groceries"
    _save(store, PHONE, search)

    assert store.shared_revision() > before


def test_the_shared_revision_rises_for_contexts_added_deleted_or_sorted() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    revisions = [store.shared_revision()]
    store.set_sort_mode(view_id=PHONE, tab_id=first, sort_mode="alphabetical")
    revisions.append(store.shared_revision())
    store.delete_tab(view_id=PHONE, tab_id=second)
    revisions.append(store.shared_revision())
    store.create_tab(view_id=PHONE, copy_from_tab_id=first, copies_view=False, is_page=False)
    revisions.append(store.shared_revision())

    assert revisions == sorted(set(revisions)), "each change raises it"


def test_the_shared_revision_stays_for_what_is_each_views_own() -> None:
    store = TabStateStore()
    first, second = _two_contexts(store)
    before = store.shared_revision()

    def scroll(state: dict) -> None:
        state["tabs"][first]["scrollY"] = SCROLLED
    _save(store, MAC, scroll)
    _show(store, MAC, second)
    store.set_tree_shown(view_id=MAC, is_shown=True)
    _open_page(store, MAC, first)

    assert store.shared_revision() == before


def test_a_view_saving_twice_never_puts_back_a_search_another_view_changed() -> None:
    # Found 2026-11-14: the answer to a view's first save told the store the view now had the
    # other view's search, though the browser keeps its own until it loads the tabs again; its next
    # save then counted its old search as a change and put it back.
    store = TabStateStore()
    first, _second = _two_contexts(store)
    phone_has = store.snapshot(view_id=PHONE)

    def search(state: dict) -> None:
        state["tabs"][first]["searchQuery"] = "groceries"
    _save(store, MAC, search)
    for scrolled_to in (SCROLLED, SCROLLED + 1):
        phone_has["tabs"][first]["scrollY"] = scrolled_to
        store.update(
            view_id=PHONE, active_tab_id=phone_has["activeTabId"], tabs=phone_has["tabs"],
            tab_order=phone_has["tabOrder"], reference_views=phone_has["referenceViews"],
            read_at_version=phone_has["version"],
        )

    assert store.get_search_query(tab_id=first) == "groceries"
    # Once the phone takes the tabs again (live changes, step 3), its own searches count again.
    _save(store, PHONE, lambda state: state["tabs"][first].update(searchQuery="plants"))
    assert store.get_search_query(tab_id=first) == "plants"


def test_what_a_view_holds_survives_the_store_loading_again() -> None:
    # Found 2026-11-14: a refused change reloads the store (request_recovery.py); without its record
    # of what each view holds, a view could not change a search until it loaded its tabs again.
    store = TabStateStore()
    first, _second = _two_contexts(store)
    phone_has = store.snapshot(view_id=PHONE)
    _save(store, PHONE, lambda state: state["tabs"][first].update(scrollY=SCROLLED))

    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:view_places"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    phone_has["tabs"][first]["searchQuery"] = "groceries"
    restarted.update(
        view_id=PHONE, active_tab_id=phone_has["activeTabId"], tabs=phone_has["tabs"],
        tab_order=phone_has["tabOrder"], reference_views=phone_has["referenceViews"],
        read_at_version=phone_has["version"],
    )

    assert restarted.get_search_query(tab_id=first) == "groceries"


def test_a_place_saved_before_records_were_kept_takes_the_views_search() -> None:
    store = TabStateStore()
    first = store.snapshot(view_id=PHONE)["activeTabId"]
    saved = json.loads(store._serialize_state_locked())
    del saved["views"][PHONE]["knownSearch"]
    older = TabStateStore()
    older._load_state_json_locked(json.dumps(saved))

    phone_has = older.snapshot(view_id=PHONE)
    older._views[PHONE]["knownSearch"] = {}
    phone_has["tabs"][first]["searchQuery"] = "groceries"
    older.update(
        view_id=PHONE, active_tab_id=phone_has["activeTabId"], tabs=phone_has["tabs"],
        tab_order=phone_has["tabOrder"], reference_views=phone_has["referenceViews"],
        read_at_version=phone_has["version"],
    )

    assert older.get_search_query(tab_id=first) == "groceries"


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
    _save(restarted, MAC, lambda state: state["tabs"][first].update(searchQuery="groceries"))
    phone_has["tabs"][first]["scrollY"] = SCROLLED + 1
    restarted.update(
        view_id=PHONE, active_tab_id=phone_has["activeTabId"], tabs=phone_has["tabs"],
        tab_order=phone_has["tabOrder"], reference_views=phone_has["referenceViews"],
        read_at_version=phone_has["version"],
    )

    assert restarted.get_search_query(tab_id=first) == "groceries"
