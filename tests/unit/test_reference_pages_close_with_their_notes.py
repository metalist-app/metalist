"""A reference page whose notes are all deleted closes, with the pages opened from it, and its search
context goes back to its search: `foo > bar`, bar deleted, reads `foo` (the maintainer, 2026-11-14;
docs/ready-to-build/reference-cards.md §2 rule 10)."""

from __future__ import annotations

import pytest

from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.tab_state import tab_state_store
from app.usecases.create_note import apply_insert_note
from app.usecases.delete_subtree import apply_delete_subtree

PARENT = "10000000-0000-4000-8000-000000000001"
BAR = "10000000-0000-4000-8000-000000000002"
OTHER = "10000000-0000-4000-8000-000000000003"
DEEPER = "10000000-0000-4000-8000-000000000004"


@pytest.fixture
def notes(tmp_path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "fixture.metalist.db")
    monkeypatch.setattr(SafeSession, "_use_memory", False)
    clear_encryption_key()
    set_encryption_required(False)
    clear_cache()
    store.reset()
    file_registry.reset()
    tab_state_store.reset()
    session = SafeSession()
    auth_service.AuthService(session).initialize_settings()
    bootstrap_ontology_rules_store(connection=session.connection())
    store.load_from_db(None, prefetched_rows=[])
    apply_insert_note(PARENT, None, None, None, "", content="<div>parent</div>", tags="", proposed_tags="")
    apply_insert_note(BAR, PARENT, None, None, "", content="<div>bar</div>", tags="", proposed_tags="")
    apply_insert_note(OTHER, None, PARENT, None, "", content="<div>other</div>", tags="", proposed_tags="")
    apply_insert_note(DEEPER, None, OTHER, None, "", content="<div>deeper</div>", tags="", proposed_tags="")
    yield session
    session.close()
    store.reset()
    clear_cache()
    file_registry.reset()
    tab_state_store.reset()
    clear_encryption_key()
    set_encryption_required(False)


def _open_pages(foo_search: str, pages: list[tuple[str, str]]) -> tuple[str, list[str]]:
    """foo, searching foo_search, with a way of pages (reference query, kind) from it, the last
    one shown. Returns foo's tab and the pages' tabs."""
    state = tab_state_store.snapshot()
    foo = state["activeTabId"]
    page_tabs = [tab_state_store.create_tab(copy_from_tab_id=foo, copies_view=False)["newTabId"] for _ in pages]
    state = tab_state_store.snapshot()
    tabs = state["tabs"]
    tabs[foo]["searchQuery"] = foo_search
    views = {}
    from_tab = foo
    for page_tab, (query, kind) in zip(page_tabs, pages):
        tabs[page_tab]["searchQuery"] = query
        views[page_tab] = {
            "fromTabId": from_tab, "referenceQuery": query, "viewKind": kind,
            "originScope": {"scopeTabId": foo, "searchQuery": foo_search, "sortMode": "normal", "isUntaggedView": False},
        }
        from_tab = page_tab
    tab_state_store.update(active_tab_id=page_tabs[-1], tabs=tabs, tab_order=state["tabOrder"],
                           reference_views=views, read_at_version=state["version"])
    assert set(tab_state_store.snapshot()["referenceViews"]) == set(page_tabs)
    return foo, page_tabs


def test_deleting_the_linked_note_closes_its_page_and_shows_the_search(notes) -> None:
    foo, (page,) = _open_pages("foo", [(BAR, "source")])

    apply_delete_subtree(BAR)

    state = tab_state_store.snapshot()
    assert state["tabOrder"] == [foo]
    assert state["referenceViews"] == {}
    # Shown on the page when its note went: the search it was opened from.
    assert state["activeTabId"] == foo
    # The browser, not yet told, may ask for the closed page's view once: it is answered (empty).
    assert tab_state_store.was_closed_with_its_notes(tab_id=page)
    assert tab_state_store.pages_closed_at_version() == state["version"]


def test_deleting_a_parent_of_the_linked_note_closes_its_page(notes) -> None:
    foo, (page,) = _open_pages("foo", [(BAR, "source")])

    apply_delete_subtree(PARENT)

    assert tab_state_store.snapshot()["tabOrder"] == [foo]


def test_a_page_of_several_notes_closes_only_once_all_are_gone(notes) -> None:
    foo, (page,) = _open_pages("foo", [(f"{BAR} OR {OTHER}", "backlinks")])

    apply_delete_subtree(BAR)
    assert tab_state_store.snapshot()["tabOrder"] == [foo, page], "one note is left to show"

    apply_delete_subtree(OTHER)
    assert tab_state_store.snapshot()["tabOrder"] == [foo]


def test_the_pages_opened_from_a_closed_page_close_with_it(notes) -> None:
    foo, (page_a, page_b) = _open_pages("foo", [(BAR, "source"), (DEEPER, "source")])

    apply_delete_subtree(BAR)

    state = tab_state_store.snapshot()
    assert state["tabOrder"] == [foo]
    assert state["activeTabId"] == foo


def test_a_page_whose_notes_remain_is_left_alone(notes) -> None:
    foo, (page,) = _open_pages("foo", [(OTHER, "source")])

    apply_delete_subtree(PARENT)

    assert tab_state_store.snapshot()["tabOrder"] == [foo, page]


def test_a_save_still_naming_a_closed_page_is_taken_without_it(notes) -> None:
    # The browser may save its tabs before it hears the page closed: that save is not refused.
    foo, (page,) = _open_pages("foo", [(BAR, "source")])
    browser_copy = tab_state_store.snapshot()

    apply_delete_subtree(BAR)
    tab_state_store.update(
        active_tab_id=page, tabs=browser_copy["tabs"], tab_order=browser_copy["tabOrder"],
        reference_views=browser_copy["referenceViews"], read_at_version=browser_copy["version"],
    )

    state = tab_state_store.snapshot()
    assert state["tabOrder"] == [foo]
    assert state["referenceViews"] == {}
    assert state["activeTabId"] == foo
