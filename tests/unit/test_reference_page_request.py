"""The server takes a view's reference pages by name (docs/future-plans/one-writer-refactoring.md,
idea 1). A view says "this tab of mine is a reference page showing R, opened from tab F"
(TabStateStore.set_reference_page); closing the tab ends the page, and so does another search in
it. The server takes no copy of a view's tabs. The cases agreed
2026-11-18 are numbered in the comments."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.edit_locks import edit_locks
from app.services.input_errors import InputRejected
from app.services.tab_state import TabStateStore

MAC = "10000000-0000-4000-8000-0000000000f1"
PHONE = "10000000-0000-4000-8000-0000000000f2"
NO_SUCH_TAB = "10000000-0000-4000-8000-0000000000f3"
RECIPE = "20000000-0000-4000-8000-0000000000f4"
SHOPPING_LIST = "20000000-0000-4000-8000-0000000000f5"
MENU = "20000000-0000-4000-8000-0000000000f6"


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
    """Search contexts groceries and travel, the Mac showing groceries."""
    groceries = store.snapshot(view_id=MAC)["activeTabId"]
    travel = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=False)["newTabId"]
    store.show_tab(view_id=MAC, tab_id=groceries)
    store.snapshot(view_id=PHONE)
    return groceries, travel


def _scope(context: str) -> dict:
    return {"scopeTabId": context, "searchQuery": "", "sortMode": "normal", "isUntaggedView": False}


def _open_page(store: TabStateStore, view: str, *, from_tab: str, context: str, note: str) -> str:
    """Follow a reference to note from from_tab, as the page does: a tab of the view's own, what
    it shows, and the view showing it."""
    page = store.create_tab(view_id=view, copy_from_tab_id=from_tab, copies_view=False, is_page=True)["newTabId"]
    answer = store.set_reference_page(
        view_id=view, tab_id=page, from_tab_id=from_tab, reference_query=note, view_kind="source",
        origin_scope=_scope(context),
    )
    assert answer["changed"] is True
    store.show_tab(view_id=view, tab_id=page)
    return page


def _go_back(store: TabStateStore, view: str, *, to_tab: str, closing: list[str]) -> None:
    """Back from pages, as the page does: the tab gone back to is shown, then each page closed."""
    store.show_tab(view_id=view, tab_id=to_tab)
    for page in closing:
        store.delete_tab(view_id=view, tab_id=page)


def _restarted() -> TabStateStore:
    restarted = TabStateStore()
    session = SafeSession()
    with SafeSession.allow_reads("tests:reference_page_request"):
        restarted.bootstrap(connection=session.connection())
    session.close()
    return restarted


# Case 1: follow a reference from a search context, reload.
def test_a_page_opened_from_a_context_is_kept_over_a_restart() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)

    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)

    for held in (store, _restarted()):
        now = held.snapshot(view_id=MAC)
        assert now["activeTabId"] == recipe_page
        assert now["tabs"][recipe_page]["searchQuery"] == RECIPE
        assert now["referenceViews"] == {recipe_page: {
            "fromTabId": groceries, "referenceQuery": RECIPE, "viewKind": "source", "originScope": _scope(groceries),
        }}


# Case 2: follow a reference from a page, reload.
def test_a_page_opened_from_a_page_keeps_the_path_over_a_restart() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)

    list_page = _open_page(store, MAC, from_tab=recipe_page, context=groceries, note=SHOPPING_LIST)

    views = _restarted().snapshot(view_id=MAC)["referenceViews"]
    assert views[recipe_page]["fromTabId"] == groceries
    assert views[list_page]["fromTabId"] == recipe_page
    assert views[list_page]["originScope"]["scopeTabId"] == groceries


# Case 3: back from a page, reload.
def test_a_page_gone_back_from_is_closed_and_stays_closed() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)

    _go_back(store, MAC, to_tab=groceries, closing=[recipe_page])

    for held in (store, _restarted()):
        now = held.snapshot(view_id=MAC)
        assert now["activeTabId"] == groceries
        assert recipe_page not in now["tabs"]
        assert now["referenceViews"] == {}


# Case 4: leave the whole path.
def test_leaving_the_path_closes_every_page_on_it() -> None:
    store = TabStateStore()
    groceries, travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)
    list_page = _open_page(store, MAC, from_tab=recipe_page, context=groceries, note=SHOPPING_LIST)

    _go_back(store, MAC, to_tab=groceries, closing=[recipe_page, list_page])

    now = _restarted().snapshot(view_id=MAC)
    assert now["tabOrder"] == [groceries, travel]
    assert now["referenceViews"] == {}


# Case 5: jump back to an earlier level of the path.
def test_going_back_to_an_earlier_level_closes_the_later_ones_only() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)
    list_page = _open_page(store, MAC, from_tab=recipe_page, context=groceries, note=SHOPPING_LIST)
    menu_page = _open_page(store, MAC, from_tab=list_page, context=groceries, note=MENU)

    _go_back(store, MAC, to_tab=recipe_page, closing=[menu_page, list_page])

    now = _restarted().snapshot(view_id=MAC)
    assert now["activeTabId"] == recipe_page
    assert list(now["referenceViews"]) == [recipe_page]


# Case 6: a later AI reference replaces the AI references a page shows.
def test_what_a_page_shows_is_replaced_in_the_same_tab() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    page = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=True)["newTabId"]
    several = f"{RECIPE} OR {SHOPPING_LIST}"
    store.set_reference_page(
        view_id=MAC, tab_id=page, from_tab_id=groceries, reference_query=several, view_kind="references",
        origin_scope=_scope(groceries),
    )
    tabs_before = store.snapshot(view_id=MAC)["tabOrder"]

    answer = store.set_reference_page(
        view_id=MAC, tab_id=page, from_tab_id=groceries, reference_query=MENU, view_kind="reference",
        origin_scope=_scope(groceries),
    )

    assert answer["changed"] is True
    assert answer["tabOrder"] == tabs_before
    now = _restarted().snapshot(view_id=MAC)
    assert now["tabs"][page]["searchQuery"] == MENU
    assert [now["referenceViews"][page]["referenceQuery"], now["referenceViews"][page]["viewKind"]] == [MENU, "reference"]


def test_a_page_set_to_what_it_is_changes_nothing() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)
    version = store.snapshot(view_id=MAC)["version"]

    answer = store.set_reference_page(
        view_id=MAC, tab_id=recipe_page, from_tab_id=groceries, reference_query=RECIPE, view_kind="source",
        origin_scope=_scope(groceries),
    )

    assert answer["changed"] is False
    assert answer["version"] == version


# Case 7: type in the search box while on a page.
def test_another_search_in_a_page_ends_the_reference_view() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)

    answer = store.set_search(view_id=MAC, tab_id=recipe_page, search_query="milk")

    assert answer["referenceViews"] == {}
    assert answer["tabs"][recipe_page]["searchQuery"] == "milk"
    assert _restarted().snapshot(view_id=MAC)["referenceViews"] == {}


def test_the_reference_asked_for_again_as_a_search_keeps_the_page() -> None:
    # The page sends the search it runs in a page by name too (runReferenceSearchInActiveTab).
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)

    answer = store.set_search(view_id=MAC, tab_id=recipe_page, search_query=RECIPE)

    assert list(answer["referenceViews"]) == [recipe_page]


# Case 8: the note a page shows is deleted.
def test_a_page_whose_note_is_deleted_closes_and_its_view_shows_where_it_came_from() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)

    assert store.close_pages_whose_notes_are_gone(note_exists=lambda note_id: note_id != RECIPE) is True

    now = store.snapshot(view_id=MAC)
    assert recipe_page not in now["tabs"]
    assert now["referenceViews"] == {}
    assert now["activeTabId"] == groceries


# Case 9: another view deletes the search context a page was opened from. The page stays, a tab
# of the view's own that no page record claims; the view gives it to the tab before it
# (adoptOrphanReferenceTabs) and says so by name.
def test_a_page_whose_context_was_deleted_elsewhere_is_taken_by_another_context() -> None:
    store = TabStateStore()
    groceries, travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=travel, context=travel, note=RECIPE)

    store.delete_tab(view_id=PHONE, tab_id=travel)

    left = store.snapshot(view_id=MAC)
    assert left["activeTabId"] == recipe_page
    assert left["referenceViews"] == {}
    answer = store.set_reference_page(
        view_id=MAC, tab_id=recipe_page, from_tab_id=groceries, reference_query=RECIPE, view_kind="source",
        origin_scope=_scope(groceries),
    )
    assert answer["changed"] is True
    assert _restarted().snapshot(view_id=MAC)["referenceViews"][recipe_page]["fromTabId"] == groceries


# Case 10: two views each open pages.
def test_each_view_sees_only_its_own_pages() -> None:
    store = TabStateStore()
    groceries, travel = _two_contexts(store)

    mac_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)
    phone_page = _open_page(store, PHONE, from_tab=travel, context=travel, note=MENU)

    mac, phone = store.snapshot(view_id=MAC), store.snapshot(view_id=PHONE)
    assert list(mac["referenceViews"]) == [mac_page] and phone_page not in mac["tabs"]
    assert list(phone["referenceViews"]) == [phone_page] and mac_page not in phone["tabs"]


def test_a_page_opened_is_no_news_to_the_other_views() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    revision = store.shared_revision(view_id=PHONE)

    _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)

    assert store.shared_revision(view_id=PHONE) == revision


# Case 11: tabs saved with pages open load, and a tab of note ids no page record claims (0.29.0
# left them) is taken as a page by the view that owns it.
def test_saved_pages_load_and_an_unclaimed_tab_of_note_ids_is_taken_as_a_page() -> None:
    saved = json.loads((Path(__file__).parent.parent / "fixtures" / "upgrade" / "tab-state-v0.29.0.json").read_text())
    store = TabStateStore()
    store._apply_snapshot_locked(store._deserialize_snapshot_json(json.dumps(saved)))
    loaded = store.snapshot(view_id=MAC)
    assert loaded["referenceViews"] == saved["referenceViews"]
    unclaimed = saved["activeTabId"]
    assert unclaimed not in loaded["referenceViews"]
    context = next(tab_id for tab_id in loaded["tabOrder"] if tab_id != unclaimed and tab_id not in loaded["referenceViews"])
    reference = loaded["tabs"][unclaimed]["searchQuery"]

    answer = store.set_reference_page(
        view_id=MAC, tab_id=unclaimed, from_tab_id=context, reference_query=reference, view_kind="source",
        origin_scope=_scope(context),
    )

    assert answer["changed"] is True
    assert answer["referenceViews"][unclaimed]["fromTabId"] == context
    assert unclaimed not in store.snapshot(view_id=PHONE)["tabs"]


# Case 12: what is refused, and what changes nothing.
def _ask(store: TabStateStore, **changed: object) -> dict:
    groceries = store.snapshot(view_id=MAC)["tabOrder"][0]
    page = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=True)["newTabId"]
    asked = {
        "tab_id": page, "from_tab_id": groceries, "reference_query": RECIPE, "view_kind": "source",
        "origin_scope": _scope(groceries),
    }
    return store.set_reference_page(view_id=MAC, **{**asked, **changed})


@pytest.mark.parametrize("changed", [
    {"tab_id": NO_SUCH_TAB},
    {"from_tab_id": NO_SUCH_TAB},
    {"origin_scope": _scope(NO_SUCH_TAB)},
    {"view_kind": "bookmark"},
    {"reference_query": ""},
    {"origin_scope": {"scopeTabId": NO_SUCH_TAB}},
], ids=["no such tab", "no such from-tab", "no such context", "unknown kind", "empty reference", "half a scope"])
def test_a_page_that_names_nothing_real_is_refused(changed: dict) -> None:
    store = TabStateStore()
    _two_contexts(store)

    with pytest.raises(InputRejected):
        _ask(store, **changed)

    assert store.snapshot(view_id=MAC)["referenceViews"] == {}


def test_a_page_opened_from_itself_is_refused() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    page = store.create_tab(view_id=MAC, copy_from_tab_id=groceries, copies_view=False, is_page=True)["newTabId"]

    with pytest.raises(InputRejected):
        store.set_reference_page(
            view_id=MAC, tab_id=page, from_tab_id=page, reference_query=RECIPE, view_kind="source",
            origin_scope=_scope(groceries),
        )


def test_another_views_page_is_refused_as_the_page_and_as_where_it_came_from() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    phone_page = _open_page(store, PHONE, from_tab=groceries, context=groceries, note=MENU)

    with pytest.raises(InputRejected):
        _ask(store, tab_id=phone_page)
    with pytest.raises(InputRejected):
        _ask(store, from_tab_id=phone_page)

    assert store.snapshot(view_id=PHONE)["referenceViews"][phone_page]["referenceQuery"] == MENU


def test_a_search_context_with_a_search_of_its_own_is_no_page() -> None:
    store = TabStateStore()
    groceries, travel = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=travel, search_query="tickets")

    with pytest.raises(InputRejected):
        _ask(store, tab_id=travel)

    assert travel in store.snapshot(view_id=PHONE)["tabs"]
    assert store.get_search_query(tab_id=travel) == "tickets"


def test_a_page_closed_a_moment_ago_changes_nothing() -> None:
    store = TabStateStore()
    groceries, _travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)
    store.close_pages_whose_notes_are_gone(note_exists=lambda _note_id: False)
    version = store.snapshot(view_id=MAC)["version"]

    answer = store.set_reference_page(
        view_id=MAC, tab_id=recipe_page, from_tab_id=groceries, reference_query=RECIPE, view_kind="source",
        origin_scope=_scope(groceries),
    )

    assert answer["changed"] is False
    assert answer["version"] == version


def test_a_page_opened_from_a_context_deleted_a_moment_ago_changes_nothing() -> None:
    store = TabStateStore()
    groceries, travel = _two_contexts(store)
    page = store.create_tab(view_id=MAC, copy_from_tab_id=travel, copies_view=False, is_page=True)["newTabId"]
    store.delete_tab(view_id=PHONE, tab_id=travel)

    answer = store.set_reference_page(
        view_id=MAC, tab_id=page, from_tab_id=travel, reference_query=RECIPE, view_kind="source",
        origin_scope=_scope(travel),
    )

    assert answer["changed"] is False
    assert answer["referenceViews"] == {}


# A search context never becomes a reference page (finding 2 of the simulation, cases agreed
# 2026-11-18): only a tab made as a page is one, and the answer names the view's pages
# (pageTabIds), so the page takes back as its own only tabs the server holds as its pages.
def _recipes_holding_note_ids(store: TabStateStore, search: str) -> tuple[str, str]:
    groceries, recipes = _two_contexts(store)
    store.set_search(view_id=MAC, tab_id=recipes, search_query=search)
    return groceries, recipes


def _ask_to_take_as_a_page(store: TabStateStore, view: str, *, context: str, from_tab: str, search: str) -> None:
    store.set_reference_page(
        view_id=view, tab_id=context, from_tab_id=from_tab, reference_query=search, view_kind="source",
        origin_scope=_scope(from_tab),
    )


# Cases 1, 2 and 7: a context whose search is one note ID, or several, asked for as a page.
@pytest.mark.parametrize("search", [RECIPE, f"{RECIPE} OR {MENU}"], ids=["one note id", "several note ids"])
def test_a_context_holding_note_ids_is_refused_as_a_page(search: str) -> None:
    store = TabStateStore()
    groceries, recipes = _recipes_holding_note_ids(store, search)
    version = store.snapshot(view_id=MAC)["version"]

    with pytest.raises(InputRejected):
        _ask_to_take_as_a_page(store, MAC, context=recipes, from_tab=groceries, search=search)

    for view in (MAC, PHONE):
        now = store.snapshot(view_id=view)
        assert now["tabOrder"] == [groceries, recipes]
        assert now["referenceViews"] == {}
        assert now["pageTabIds"] == []
        assert now["version"] == version


# Case 3: the phone has a page opened from the context.
def test_another_views_page_keeps_the_context_it_was_opened_from() -> None:
    store = TabStateStore()
    groceries, recipes = _recipes_holding_note_ids(store, RECIPE)
    phone_page = _open_page(store, PHONE, from_tab=recipes, context=recipes, note=MENU)

    with pytest.raises(InputRejected):
        _ask_to_take_as_a_page(store, MAC, context=recipes, from_tab=groceries, search=RECIPE)

    phone = store.snapshot(view_id=PHONE)
    assert phone["tabOrder"] == [groceries, recipes, phone_page]
    assert phone["referenceViews"][phone_page]["fromTabId"] == recipes
    assert phone["referenceViews"][phone_page]["originScope"]["scopeTabId"] == recipes


# Case 4: the view's own page opened from the context.
def test_a_views_own_page_keeps_the_context_it_was_opened_from() -> None:
    store = TabStateStore()
    groceries, recipes = _recipes_holding_note_ids(store, RECIPE)
    mac_page = _open_page(store, MAC, from_tab=recipes, context=recipes, note=MENU)

    with pytest.raises(InputRejected):
        _ask_to_take_as_a_page(store, MAC, context=recipes, from_tab=groceries, search=RECIPE)

    mac = store.snapshot(view_id=MAC)
    assert mac["referenceViews"] == {mac_page: {
        "fromTabId": recipes, "referenceQuery": MENU, "viewKind": "source", "originScope": _scope(recipes),
    }}
    assert mac["pageTabIds"] == [mac_page]


# Case 6: a page of the view's own that no record claims is still named as its page.
def test_a_page_left_without_its_record_is_still_named_as_the_views_page() -> None:
    store = TabStateStore()
    groceries, travel = _two_contexts(store)
    recipe_page = _open_page(store, MAC, from_tab=travel, context=travel, note=RECIPE)

    store.delete_tab(view_id=PHONE, tab_id=travel)

    assert store.snapshot(view_id=MAC)["referenceViews"] == {}
    assert store.snapshot(view_id=MAC)["pageTabIds"] == [recipe_page]
    assert store.snapshot(view_id=PHONE)["pageTabIds"] == []


# Case 8: the server restarts with a context holding a note id.
def test_a_context_holding_a_note_id_is_a_context_after_a_restart() -> None:
    store = TabStateStore()
    groceries, recipes = _recipes_holding_note_ids(store, RECIPE)

    restarted = _restarted()

    for view in (MAC, PHONE):
        now = restarted.snapshot(view_id=view)
        assert now["tabOrder"] == [groceries, recipes]
        assert now["pageTabIds"] == []


# Case 9: a tab of note ids saved before views, which no record claims, is the first view's page.
def test_a_tab_of_note_ids_saved_before_views_is_named_as_the_first_views_page() -> None:
    saved = json.loads((Path(__file__).parent.parent / "fixtures" / "upgrade" / "tab-state-v0.29.0.json").read_text())
    store = TabStateStore()
    store._apply_snapshot_locked(store._deserialize_snapshot_json(json.dumps(saved)))

    assert saved["activeTabId"] in store.snapshot(view_id=MAC)["pageTabIds"]
    assert store.snapshot(view_id=PHONE)["pageTabIds"] == []


def test_each_view_is_told_its_own_pages_only() -> None:
    store = TabStateStore()
    groceries, travel = _two_contexts(store)
    mac_page = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)
    phone_page = _open_page(store, PHONE, from_tab=travel, context=travel, note=MENU)

    assert store.snapshot(view_id=MAC)["pageTabIds"] == [mac_page]
    assert store.snapshot(view_id=PHONE)["pageTabIds"] == [phone_page]


# Every reference page leads back to a search (finding 3 of the simulation, cases agreed
# 2026-11-18): its search context is never a page, and "opened from" never goes round. Search
# context groceries, with the Mac's Lasagne page and Tomato page.
def _set_page(store: TabStateStore, *, page: str, from_tab: str, context: str, note: str) -> dict:
    return store.set_reference_page(
        view_id=MAC, tab_id=page, from_tab_id=from_tab, reference_query=note, view_kind="source",
        origin_scope=_scope(context),
    )


def _lasagne_then_tomato(store: TabStateStore) -> tuple[str, str, str]:
    groceries, _travel = _two_contexts(store)
    lasagne = _open_page(store, MAC, from_tab=groceries, context=groceries, note=RECIPE)
    tomato = _open_page(store, MAC, from_tab=lasagne, context=groceries, note=SHOPPING_LIST)
    return groceries, lasagne, tomato


# Cases 1 and 2: a page that belongs to itself, or to another page.
@pytest.mark.parametrize("belongs_to_itself", [True, False], ids=["itself", "another page"])
def test_a_page_whose_search_context_is_a_page_is_refused(belongs_to_itself: bool) -> None:
    store = TabStateStore()
    groceries, lasagne, tomato = _lasagne_then_tomato(store)
    before = store.snapshot(view_id=MAC)
    context = tomato
    if belongs_to_itself:
        context = lasagne

    with pytest.raises(InputRejected):
        _set_page(store, page=lasagne, from_tab=groceries, context=context, note=RECIPE)

    assert store.snapshot(view_id=MAC) == before


# Case 3: two pages each opened from the other.
def test_a_page_opened_from_a_page_opened_from_it_is_refused() -> None:
    store = TabStateStore()
    groceries, lasagne, tomato = _lasagne_then_tomato(store)
    before = store.snapshot(view_id=MAC)

    with pytest.raises(InputRejected):
        _set_page(store, page=lasagne, from_tab=tomato, context=groceries, note=RECIPE)

    assert store.snapshot(view_id=MAC) == before


# Case 4: the same loop through three pages.
def test_a_loop_through_three_pages_is_refused() -> None:
    store = TabStateStore()
    groceries, lasagne, tomato = _lasagne_then_tomato(store)
    menu = _open_page(store, MAC, from_tab=tomato, context=groceries, note=MENU)
    before = store.snapshot(view_id=MAC)

    with pytest.raises(InputRejected):
        _set_page(store, page=lasagne, from_tab=menu, context=groceries, note=RECIPE)

    assert store.snapshot(view_id=MAC) == before


# Case 6: a page given another tab to be opened from, with no loop.
def test_a_page_given_another_tab_to_be_opened_from_is_taken() -> None:
    store = TabStateStore()
    groceries, lasagne, tomato = _lasagne_then_tomato(store)

    answer = _set_page(store, page=tomato, from_tab=groceries, context=groceries, note=SHOPPING_LIST)

    assert answer["changed"] is True
    assert answer["referenceViews"][tomato]["fromTabId"] == groceries
    assert answer["referenceViews"][lasagne]["fromTabId"] == groceries


# Case 7: a page opened from a second search context, belonging to it.
def test_a_page_opened_from_a_second_context_belongs_to_it() -> None:
    store = TabStateStore()
    _groceries, travel = _two_contexts(store)

    page = _open_page(store, MAC, from_tab=travel, context=travel, note=RECIPE)

    assert store.snapshot(view_id=MAC)["referenceViews"][page]["originScope"]["scopeTabId"] == travel


# Case 8: a loop that names a page closed a moment ago changes nothing, and is no error.
def test_a_loop_naming_a_page_closed_a_moment_ago_changes_nothing() -> None:
    store = TabStateStore()
    groceries, lasagne, tomato = _lasagne_then_tomato(store)
    store.delete_tab(view_id=MAC, tab_id=tomato)

    answer = _set_page(store, page=lasagne, from_tab=tomato, context=groceries, note=RECIPE)

    assert answer["changed"] is False
    assert answer["referenceViews"][lasagne]["fromTabId"] == groceries


# Case 9: tabs saved with a page that belongs to a page load as they are.
def test_saved_tabs_holding_a_page_that_belongs_to_a_page_load() -> None:
    store = TabStateStore()
    groceries, lasagne, tomato = _lasagne_then_tomato(store)
    with store._lock:
        store._views[MAC]["referenceViews"][lasagne]["originScope"]["scopeTabId"] = tomato
        store._persist_locked(connection=None, encryption_service=None, force_plaintext=False)

    loaded = _restarted().snapshot(view_id=MAC)

    assert loaded["tabOrder"] == [groceries, store.snapshot(view_id=MAC)["tabOrder"][1], lasagne, tomato]
    assert set(loaded["pageTabIds"]) == {lasagne, tomato}
