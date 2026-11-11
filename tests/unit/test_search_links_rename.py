"""Rename tag renames a tag in search links and saved searches (docs/ready-to-build/search-links.md §6)."""
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
from app.usecases.rename_tag import apply_rename_tag_everywhere


@pytest.fixture
def live_database(tmp_path, monkeypatch):
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
    yield session
    session.close()
    store.reset()
    clear_cache()
    file_registry.reset()
    tab_state_store.reset()
    clear_encryption_key()
    set_encryption_required(False)


def _note(note_id: str, previous_id: str | None, *, content: str, tags: str) -> None:
    apply_insert_note(note_id, None, previous_id, None, "", content=content, tags=tags, proposed_tags="")


def _search_in_active_context(search: str) -> str:
    state = tab_state_store.snapshot()
    tab_id = state["activeTabId"]
    tabs = state["tabs"]
    tabs[tab_id]["searchQuery"] = search
    tab_state_store.update(
        active_tab_id=tab_id, tabs=tabs, tab_order=state["tabOrder"], reference_views=state["referenceViews"],
        read_at_version=state["version"],
    )
    return tab_id


def test_rename_tag_renames_it_in_search_links_and_saved_searches(live_database) -> None:
    dashboard = '<div>[[search:work -archive|Current work]] and [[search:"work"]] and work</div>'
    _note("dash", None, content=dashboard, tags="")
    _note("task", "dash", content="<div>Ship it</div>", tags="work")
    updated_before = store.get_note("dash").updated_at
    tab_id = _search_in_active_context("work -archive")
    browser_copy = tab_state_store.snapshot()

    result = apply_rename_tag_everywhere(old="work", new="job", token="")

    # Only the link's tag term; its text, a quoted search and the note's own words stay.
    assert store.get_note("dash").content == '<div>[[search:job -archive|Current work]] and [[search:"work"]] and work</div>'
    assert store.get_note("dash").updated_at == updated_before
    assert tab_state_store.get_search_query(tab_id=tab_id) == "job -archive"
    assert (result["renamedSearchLinkNoteCount"], result["renamedSearchCount"]) == (1, 1)
    # A browser's copy read before the rename doesn't bring the old name back.
    tab_state_store.update(
        active_tab_id=tab_id, tabs=browser_copy["tabs"], tab_order=browser_copy["tabOrder"],
        reference_views=browser_copy["referenceViews"], read_at_version=browser_copy["version"],
    )
    assert tab_state_store.get_search_query(tab_id=tab_id) == "job -archive"


def test_the_search_context_a_link_opens_has_the_same_terms(live_database) -> None:
    tab_id = _search_in_active_context("work  -archive")
    assert tab_state_store.search_context_with_search(search="-archive Work") == tab_id
    assert tab_state_store.search_context_with_search(search="work") == ""
