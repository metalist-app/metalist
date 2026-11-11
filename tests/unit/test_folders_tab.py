"""The folders tab only shows or hides the tree (docs/ready-to-build/folders-tab-and-multiple-folders.md
§1, agreed with the maintainer 2026-11-11): no search context changes, and the tree belongs to the view,
kept with the tabs over a restart. A folder clicked is the search of the context it was clicked in;
⌘-clicked, added or taken out (§2). Folder contexts, a kind of search context from 2026-11-07, became
ordinary ones. The browser's half is in scripts/browser-folder-context-regressions.mjs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.api.routes.imports as imports_route
import app.api.routes.notes as notes_route
import app.api.routes.virtual_folders as virtual_folders_route
from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services import tab_state as tab_state_module
from app.services.input_errors import InputRejected
from app.services.tab_state import TabStateStore


@pytest.fixture(autouse=True)
def fresh_tabs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TabStateStore:
    set_encryption_required(False)
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    store = TabStateStore()
    for module in (tab_state_module, notes_route, imports_route):
        monkeypatch.setattr(module, "tab_state_store", store)
    try:
        yield store
    finally:
        set_encryption_required(False)
        SafeSession.use_file_db()


def _bootstrapped_copy() -> TabStateStore:
    reloaded = TabStateStore()
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:folder_context:bootstrap"):
            reloaded.bootstrap(connection=session.connection())
    finally:
        session.close()
    return reloaded


def _save(store: TabStateStore, *, active: str, searches: dict[str, str]) -> dict[str, object]:
    """The browser's snapshot save: the context shown, and searches typed."""
    snapshot = store.snapshot()
    for tab_id, search in searches.items():
        snapshot["tabs"][tab_id]["searchQuery"] = search
    return store.update(reference_views={}, active_tab_id=active, tabs=snapshot["tabs"],
                        tab_order=snapshot["tabOrder"], read_at_version=snapshot["version"])


# §1: the folders tab shows or hides the tree, nothing else; a restart keeps it.
def test_the_folders_tab_only_shows_or_hides_the_tree(fresh_tabs: TabStateStore) -> None:
    groceries = fresh_tabs.snapshot()["activeTabId"]
    _save(fresh_tabs, active=groceries, searches={groceries: "@todo"})
    before = fresh_tabs.snapshot()
    assert before["treeShown"] is False

    shown = fresh_tabs.set_tree_shown(is_shown=True)

    assert shown["treeShown"] is True
    assert [shown["activeTabId"], shown["tabOrder"], shown["tabs"]] == [before["activeTabId"], before["tabOrder"], before["tabs"]]
    assert _bootstrapped_copy().snapshot()["treeShown"] is True
    hidden = fresh_tabs.set_tree_shown(is_shown=False)
    assert hidden["treeShown"] is False
    assert hidden["tabs"] == before["tabs"]
    assert _bootstrapped_copy().snapshot()["treeShown"] is False


# §1: switching search contexts leaves the tree as it is.
def test_switching_contexts_leaves_the_tree_as_it_is(fresh_tabs: TabStateStore) -> None:
    groceries = fresh_tabs.snapshot()["activeTabId"]
    pics = fresh_tabs.create_tab(copy_from_tab_id=groceries, copies_view=False)["newTabId"]
    fresh_tabs.set_tree_shown(is_shown=True)
    assert _save(fresh_tabs, active=pics, searches={pics: "OLD_PICS/"})["treeShown"] is True
    assert _save(fresh_tabs, active=groceries, searches={})["treeShown"] is True


# §2: a click makes the folder the search of any context, the one before replaced, from the top;
# the top, `/`, empties it (folder-tags-in-search.md §2).
def test_a_folder_clicked_becomes_the_search(fresh_tabs: TabStateStore) -> None:
    groceries = fresh_tabs.snapshot()["activeTabId"]
    _save(fresh_tabs, active=groceries, searches={groceries: "@todo"})

    chosen = fresh_tabs.choose_folder(tab_id=groceries, folder="Projects/", adds=False)

    assert chosen["tabs"][groceries]["searchQuery"] == "Projects/"
    assert chosen["tabs"][groceries]["scrollY"] == 0
    top = fresh_tabs.choose_folder(tab_id=groceries, folder="", adds=False)
    assert top["tabs"][groceries]["searchQuery"] == ""


# §2: ⌘-click adds or takes out one folder, keeping the rest; on `/`, every folder goes.
@pytest.mark.parametrize(
    ("search", "folder", "after"),
    [
        ("Projects/ @todo", "Archive/", "Projects/ Archive/ @todo"),
        ("Projects/ Archive/ @todo", "Archive/", "Projects/ @todo"),
        ("Projects/ Archive/ @todo", "archive/", "Projects/ @todo"),
        ("@todo", "Archive/", "Archive/ @todo"),
        ("Projects/ Archive/ @todo", "", "@todo"),
        ("Projects/ OR Archive/ @todo", "", "@todo"),
        ("Projects/ OR Archive/", "Archive/", "Projects/"),
    ],
)
def test_a_folder_cmd_clicked_is_added_or_taken_out(fresh_tabs: TabStateStore, search: str, folder: str, after: str) -> None:
    groceries = fresh_tabs.snapshot()["activeTabId"]
    _save(fresh_tabs, active=groceries, searches={groceries: search})
    assert fresh_tabs.choose_folder(tab_id=groceries, folder=folder, adds=True)["tabs"][groceries]["searchQuery"] == after


# + copies the search, folders included; nothing about the tree.
def test_a_copy_copies_the_search(fresh_tabs: TabStateStore) -> None:
    groceries = fresh_tabs.snapshot()["activeTabId"]
    _save(fresh_tabs, active=groceries, searches={groceries: "Projects/ @todo"})
    copied = fresh_tabs.create_tab(copy_from_tab_id=groceries, copies_view=True)
    assert copied["tabs"][copied["newTabId"]]["searchQuery"] == "Projects/ @todo"
    assert "folderContexts" not in copied and "recentTabs" not in copied


# Saved with folder contexts (2026-11-07 to 2026-11-11): each becomes an ordinary search context with
# its search, a folder kept apart going in front of it, once; the tree shows when the context shown
# was one. A folder saved on a plain search (before 2026-11-07) is dropped.
@pytest.mark.parametrize("active_is_folder_context", [True, False])
def test_folder_contexts_become_ordinary_ones(fresh_tabs: TabStateStore, active_is_folder_context: bool) -> None:
    groceries = fresh_tabs.snapshot()["activeTabId"]
    pics = fresh_tabs.create_tab(copy_from_tab_id=groceries, copies_view=False)["newTabId"]
    active = groceries
    if active_is_folder_context:
        active = pics
    _save(fresh_tabs, active=active, searches={groceries: "@todo", pics: "@urgent"})
    snapshot = fresh_tabs.snapshot()
    del snapshot["treeShown"]
    snapshot["folderFilters"] = {groceries: "Projects/", pics: "OLD_PICS/"}
    snapshot["folderContexts"] = [pics]
    snapshot["recentTabs"] = [active, groceries, pics]

    fresh_tabs._apply_snapshot_locked(fresh_tabs._deserialize_snapshot_json(json.dumps(snapshot)))

    after = fresh_tabs.snapshot()
    assert after["treeShown"] is active_is_folder_context
    assert fresh_tabs.get_search_query(tab_id=pics) == "OLD_PICS/ @urgent"
    assert fresh_tabs.get_search_query(tab_id=groceries) == "@todo"
    assert [key for key in ("folderFilters", "folderContexts", "recentTabs") if key in after] == []


# The one folder context of the build tried on 2026-11-07 converts the same way.
def test_the_single_folder_context_converts_too(fresh_tabs: TabStateStore) -> None:
    groceries = fresh_tabs.snapshot()["activeTabId"]
    snapshot = fresh_tabs.snapshot()
    del snapshot["treeShown"]
    snapshot["folderContext"] = {"tabId": groceries, "originTabId": groceries}
    fresh_tabs._apply_snapshot_locked(fresh_tabs._deserialize_snapshot_json(json.dumps(snapshot)))
    assert fresh_tabs.snapshot()["treeShown"] is True


# The browser's two calls for the tree: a folder clicked, and the folders tab.
def test_the_tree_routes_exist() -> None:
    paths = {route.path for route in virtual_folders_route.router.routes}
    assert {"/virtual-folders/folder-context", "/virtual-folders/tree-shown"} <= paths
    assert "/virtual-folders/folder-context/new" not in paths
