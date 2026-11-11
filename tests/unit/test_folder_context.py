"""Folder contexts (docs/ready-to-build/virtual-folders.md, "Folder contexts", agreed with the maintainer
2026-11-07): a search context is either a folder context, with the tree, or a plain search. A folder
chosen in the tree is the context's search (`Projects/`, docs/ready-to-build/folder-tags-in-search.md). Open folders tab goes to the folder context used last (a new one, on `/`,
when there is none); close folders tab goes to the plain search used last (a new blank one when
there is none). Which context was used last is kept with the search contexts. The server's half;
the browser's is in scripts/browser-folder-context-regressions.mjs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.api.routes.imports as imports_route
import app.api.routes.notes as notes_route
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


# Case 1: with no folder context, open folders tab makes one at the end of the list, on `/`.
def test_a_new_folder_context_is_made_at_the_end_on_every_note(fresh_tabs: TabStateStore) -> None:
    todo = fresh_tabs.snapshot()["activeTabId"]
    _save(fresh_tabs, active=todo, searches={todo: "@todo"})

    made = fresh_tabs.create_folder_context()

    folder_tab = made["newTabId"]
    assert made["tabOrder"] == [todo, folder_tab]
    assert made["folderContexts"] == [folder_tab]
    assert made["tabs"][folder_tab]["searchQuery"] == ""
    assert made["tabs"][todo]["searchQuery"] == "@todo"


# Case 6: a folder clicked replaces its folder context's search with the folder, from the top; the
# top, `/`, empties it (folder-tags-in-search.md §2).
def test_a_folder_clicked_becomes_its_folder_contexts_search(fresh_tabs: TabStateStore) -> None:
    folder_tab = fresh_tabs.create_folder_context()["newTabId"]
    _save(fresh_tabs, active=folder_tab, searches={folder_tab: "@todo"})

    chosen = fresh_tabs.choose_folder(tab_id=folder_tab, folder="Projects/")

    assert chosen["tabs"][folder_tab]["searchQuery"] == "Projects/"
    assert chosen["tabs"][folder_tab]["scrollY"] == 0
    assert "folderFilters" not in chosen
    top = fresh_tabs.choose_folder(tab_id=folder_tab, folder="")
    assert top["tabs"][folder_tab]["searchQuery"] == ""


# Case 7: a plain search has no tree, so no folder to click.
def test_a_plain_search_has_no_folder_to_click(fresh_tabs: TabStateStore) -> None:
    todo = fresh_tabs.snapshot()["activeTabId"]
    with pytest.raises(InputRejected, match="folder context"):
        fresh_tabs.choose_folder(tab_id=todo, folder="Projects/")


# Case 4: + on a folder context makes another, with the same folder and search.
def test_a_copy_of_a_folder_context_is_another_folder_context(fresh_tabs: TabStateStore) -> None:
    folder_tab = fresh_tabs.create_folder_context()["newTabId"]
    fresh_tabs.choose_folder(tab_id=folder_tab, folder="Projects/")
    _save(fresh_tabs, active=folder_tab, searches={folder_tab: "@todo"})

    copied = fresh_tabs.create_tab(copy_from_tab_id=folder_tab, copies_view=True)

    copy_id = copied["newTabId"]
    assert sorted(copied["folderContexts"]) == sorted([folder_tab, copy_id])
    assert copied["tabs"][copy_id]["searchQuery"] == "@todo"
    blank = fresh_tabs.create_tab(copy_from_tab_id=folder_tab, copies_view=False)["newTabId"]
    assert blank not in fresh_tabs.snapshot()["folderContexts"]


# Cases 1-3 and 8: the contexts in the order they were last shown, most recent first; a deleted
# one leaves it; it survives a restart.
def test_the_contexts_used_last_are_kept_in_order(fresh_tabs: TabStateStore) -> None:
    todo = fresh_tabs.snapshot()["activeTabId"]
    journal = fresh_tabs.create_tab(copy_from_tab_id=todo, copies_view=False)["newTabId"]
    trips = fresh_tabs.create_folder_context()["newTabId"]
    work = fresh_tabs.create_folder_context()["newTabId"]

    _save(fresh_tabs, active=journal, searches={})
    _save(fresh_tabs, active=work, searches={})
    _save(fresh_tabs, active=trips, searches={})
    shown = _save(fresh_tabs, active=todo, searches={})
    assert shown["recentTabs"][:4] == [todo, trips, work, journal]

    after = fresh_tabs.delete_tab(tab_id=trips)
    assert trips not in after["recentTabs"]
    assert after["recentTabs"][:3] == [todo, work, journal]
    assert _bootstrapped_copy().snapshot()["recentTabs"] == after["recentTabs"]


# Case 5: - deletes a folder context; its folder goes with it.
def test_deleting_a_folder_context(fresh_tabs: TabStateStore) -> None:
    folder_tab = fresh_tabs.create_folder_context()["newTabId"]
    fresh_tabs.choose_folder(tab_id=folder_tab, folder="Projects/")
    after = fresh_tabs.delete_tab(tab_id=folder_tab)
    assert after["folderContexts"] == []


# Case 8: folder contexts and their folders survive a restart.
def test_folder_contexts_survive_a_restart(fresh_tabs: TabStateStore) -> None:
    folder_tab = fresh_tabs.create_folder_context()["newTabId"]
    fresh_tabs.choose_folder(tab_id=folder_tab, folder="Projects/")
    reloaded = _bootstrapped_copy()
    assert reloaded.snapshot()["folderContexts"] == [folder_tab]
    assert reloaded.get_search_query(tab_id=folder_tab) == "Projects/"


# Saved before the folder was search text (2026-11-11): a folder context's folder goes in front of
# its search, once; a folder saved on a plain search (before 2026-11-07) is dropped, and the
# one-folder-context build's (2026-11-07) context stays one.
def test_saved_folders_become_search_text(fresh_tabs: TabStateStore) -> None:
    todo = fresh_tabs.snapshot()["activeTabId"]
    journal = fresh_tabs.create_tab(copy_from_tab_id=todo, copies_view=False)["newTabId"]
    _save(fresh_tabs, active=todo, searches={todo: "@todo", journal: "@urgent"})
    snapshot = fresh_tabs.snapshot()
    snapshot["folderFilters"] = {todo: "Projects/", journal: "Trips/"}
    del snapshot["folderContexts"]
    del snapshot["recentTabs"]
    snapshot["folderContext"] = {"tabId": journal, "originTabId": todo}
    fresh_tabs._apply_snapshot_locked(fresh_tabs._deserialize_snapshot_json(json.dumps(snapshot)))
    assert fresh_tabs.snapshot()["folderContexts"] == [journal]
    assert fresh_tabs.get_search_query(tab_id=journal) == "Trips/ @urgent"
    assert fresh_tabs.get_search_query(tab_id=todo) == "@todo"
    assert "folderFilters" not in fresh_tabs.snapshot()
    assert fresh_tabs.snapshot()["recentTabs"][0] == fresh_tabs.snapshot()["activeTabId"]


# At the limit of search contexts, no new one.
def test_at_the_limit_no_folder_context_is_made(fresh_tabs: TabStateStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tab_state_module, "_MAX_TABS", 1)
    with pytest.raises(InputRejected, match="max tabs"):
        fresh_tabs.create_folder_context()
    assert fresh_tabs.snapshot()["folderContexts"] == []
