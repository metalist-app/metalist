"""The folder tree's switch reaches the server (docs/ready-to-build/virtual-folders.md, the folder tree switch, decided
2026-11-07: per browser): each request says whether its tree is open (X-Metalist-Folders-Shown),
and a search context's folder narrows what it shows only then. Closed, the folder is remembered,
never applied."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

import app.api.routes.imports as imports_route
import app.api.routes.notes as notes_route
from app.api import folder_tree_switch
from app.api.folder_tree_switch import applied_folder, record_folders_shown
from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services import tab_state as tab_state_module
from app.services.tab_state import TabStateStore


@pytest.fixture(autouse=True)
def fresh_tabs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TabStateStore:
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    store = TabStateStore()
    for module in (tab_state_module, folder_tree_switch, notes_route, imports_route):
        if hasattr(module, "tab_state_store"):
            monkeypatch.setattr(module, "tab_state_store", store)
    try:
        yield store
    finally:
        set_encryption_required(False)
        SafeSession.use_file_db()


def _tab_in_folder(store: TabStateStore, folder: str) -> str:
    tab_id = store.snapshot()["activeTabId"]
    store.set_folder_filter(tab_id=tab_id, folder=folder)
    return tab_id


# Cases A and C (the server's half): open, the folder narrows; closed, the search shows alone.
@pytest.mark.parametrize("shown, applied", [("true", "Projects/"), ("false", "")], ids=["tree open", "tree closed"])
def test_a_folder_applies_only_while_the_tree_is_open(fresh_tabs: TabStateStore, shown: str, applied: str) -> None:
    tab_id = _tab_in_folder(fresh_tabs, "Projects/")
    record_folders_shown({"x-metalist-folders-shown": shown})
    assert applied_folder(tab_id) == applied
    assert fresh_tabs.get_folder_filter(tab_id=tab_id) == "Projects/", "closed, the folder is remembered"


# Case K: two browsers on one vault each apply folders by their own tree.
def test_two_browsers_each_apply_folders_by_their_own_tree(fresh_tabs: TabStateStore) -> None:
    tab_id = _tab_in_folder(fresh_tabs, "Projects/")
    record_folders_shown({"x-metalist-folders-shown": "true"})
    assert applied_folder(tab_id) == "Projects/"
    record_folders_shown({"x-metalist-folders-shown": "false"})
    assert applied_folder(tab_id) == ""


def test_a_tab_in_no_folder_needs_no_switch(fresh_tabs: TabStateStore) -> None:
    tab_id = fresh_tabs.snapshot()["activeTabId"]
    record_folders_shown({})
    assert applied_folder(tab_id) == ""


def test_a_request_that_needs_the_switch_and_does_not_send_it_is_refused(fresh_tabs: TabStateStore) -> None:
    tab_id = _tab_in_folder(fresh_tabs, "Projects/")
    record_folders_shown({})
    with pytest.raises(HTTPException, match="X-Metalist-Folders-Shown"):
        applied_folder(tab_id)


# Case L: with the tree closed, the view's search, find and a new note use the search alone.
@pytest.mark.parametrize("shown, view_search, new_note_search", [
    ("true", "Projects/ journal", "Projects/ journal"),
    ("false", "journal", "journal"),
], ids=["tree open", "tree closed"])
def test_the_view_find_and_new_notes_follow_the_switch(
    fresh_tabs: TabStateStore, shown: str, view_search: str, new_note_search: str,
) -> None:
    tab_id = _tab_in_folder(fresh_tabs, "Projects/")
    record_folders_shown({"x-metalist-folders-shown": shown})
    assert notes_route._in_tab_folder("journal", tab_id) == view_search
    assert notes_route._new_note_search("journal", tab_id) == new_note_search
