"""Virtual folders, an experiment (app/services/virtual_folders.py): the folders come from the
search index's tag counts, and every folder's note count, worked out in one pass, is the
count clicking the folder shows (a search per folder)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.services.snapshot as snapshot_module
import app.services.virtual_folders as virtual_folders
import app.usecases.virtual_folders as virtual_folder_usecases
from app.db.file_session import begin_file_writer
from app.models.database import SafeSession
from app.security import encryption
from app.services import note_store as note_store_module
from app.services import store as store_module
from app.services.file_registry import file_registry
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.obsidian_import.tree import CONTENT_MARKDOWN, SPLIT_HEADINGS_AND_LISTS
from app.services.search_index import SearchIndex
from app.services.search_query import parse_search_query
from app.services.tag_ontology import TagOntology
from app.usecases.import_obsidian_vault import CmdImportObsidianVault

TOKEN = "token"
IMPORTED_AT = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
# Folders, tags and notes under notes (headings and list items become children).
VAULT = {
    "Projects/Client-A/plan.md": "---\ntags: [urgent]\n---\n# Plan\n- step one\n- step two\n",
    "Projects/Client-A/notes.md": "# Notes\nsome text about the budget\n",
    "Projects/Client-B/budget.md": "---\ntags: [urgent, money]\n---\n# Budget\n- budget line\n",
    "Projects/overview.md": "# Overview\n",
    "Daily/2026/today.md": "---\ntags: [money]\n---\n# Today\n- urgent errand\n",
    "top.md": "# Top\n",
}
SEARCHES = ["", "urgent", "money", "-urgent", "urgent OR money", "urgent -money", '"budget"', "nothing-has-this"]


@pytest.fixture
def imported_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> NoteStore:
    index = SearchIndex()
    for module in (note_store_module, snapshot_module, virtual_folders):
        monkeypatch.setattr(module, "search_index", index)
    monkeypatch.setattr(note_store_module, "get_ontology", TagOntology.empty)
    SafeSession.use_memory_db()
    SafeSession.disable_read_guard()
    encryption.set_encryption_required(False)
    file_registry.reset()
    with begin_file_writer() as connection:
        connection.execute("DELETE FROM files")
    store = NoteStore()
    store._timing_enabled = False
    monkeypatch.setattr(store_module, "_note_store", store)
    for module in (snapshot_module, virtual_folders, virtual_folder_usecases):
        monkeypatch.setattr(module, "note_store", store)
    monkeypatch.setattr(virtual_folder_usecases, "search_index", index)
    session = SafeSession()
    store.load_from_db(session, prefetched_rows=None)
    for relative, text in VAULT.items():
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(text)
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(tmp_path), split_mode=SPLIT_HEADINGS_AND_LISTS,
        content_format=CONTENT_MARKDOWN, token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    yield store
    session.close()
    file_registry.reset()


def test_the_folders_are_the_folder_tags_and_the_folders_above_them(imported_vault: NoteStore) -> None:
    assert virtual_folders.all_folder_tags() == ["Daily/2026/", "Projects/", "Projects/Client-A/", "Projects/Client-B/"]
    assert virtual_folders.folder_paths() == ["Daily/", "Daily/2026/", "Projects/", "Projects/Client-A/", "Projects/Client-B/"]


def test_a_folder_counts_its_notes_and_its_subfolders_notes(imported_vault: NoteStore) -> None:
    counts = virtual_folders.folder_note_counts("")
    assert counts == {
        "": 6, "Daily/": 1, "Daily/2026/": 1, "Projects/": 4, "Projects/Client-A/": 2, "Projects/Client-B/": 1,
    }


@pytest.mark.parametrize("search", SEARCHES)
def test_the_one_pass_counts_are_what_clicking_each_folder_shows(imported_vault: NoteStore, search: str) -> None:
    root_ids = imported_vault.get_children(None)
    paths = virtual_folders.folder_paths()
    clauses = parse_search_query(search).clauses
    assert all(snapshot_module.is_plain_clause(clause) for clause in clauses)
    one_pass = virtual_folders._count_in_one_pass(clauses, paths, root_ids)
    searched = {path: virtual_folders._count_roots(virtual_folders.search_in_folder(search, path), root_ids) for path in paths}
    searched[virtual_folders.NO_FOLDER] = virtual_folders._count_roots(search, root_ids)
    assert one_pass == searched


def test_a_folder_count_follows_the_search(imported_vault: NoteStore) -> None:
    counts = virtual_folders.folder_note_counts("urgent")
    # Plan and Budget carry the tag; Today only has the word in a list item.
    assert counts["Projects/"] == 2
    assert counts["Projects/Client-A/"] == 1
    assert counts["Daily/"] == 0


# --- Delete Folder, with its notes --------------------------------------------------------

def _root_titled(store: NoteStore, title: str) -> str:
    for root_id in store.get_children(None):
        if title in store.get_note(root_id).content:
            return root_id
    raise AssertionError(f"No root note titled {title}")


def _subtree_size(store: NoteStore, note_id: str) -> int:
    return 1 + sum(_subtree_size(store, child_id) for child_id in store.get_children(note_id))


def test_a_folders_notes_are_the_notes_filed_in_it_and_below_it_with_their_subtrees(imported_vault: NoteStore) -> None:
    filed = [_root_titled(imported_vault, title) for title in ("Plan", "Notes", "Budget", "Overview")]
    deletion = virtual_folder_usecases.notes_in_folder("Projects/")
    assert sorted(deletion.top_note_ids) == sorted(filed)
    assert deletion.note_count == sum(_subtree_size(imported_vault, note_id) for note_id in filed)
    assert virtual_folder_usecases.notes_in_folder("Projects/Client-B/").top_note_ids == [_root_titled(imported_vault, "Budget")]


def test_deleting_a_folder_with_its_notes_keeps_the_notes_elsewhere(imported_vault: NoteStore, monkeypatch: pytest.MonkeyPatch) -> None:
    resets: list[tuple[str, str]] = []
    monkeypatch.setattr(virtual_folder_usecases, "reset_undo_stack", lambda client_id, undo_context: resets.append((client_id, undo_context)))
    deletion = virtual_folder_usecases.notes_in_folder("Projects/")
    kept = [_root_titled(imported_vault, title) for title in ("Today", "Top")]
    roots_before = len(imported_vault.get_children(None))
    result = virtual_folder_usecases.delete_folder_and_notes(
        folder="Projects/", expected_note_count=4, token=TOKEN, client_id="client", undo_context="undo",
    )
    # The total drops by the number the dialog gave (the notes under them go uncounted).
    assert result["deletedNoteCount"] == 4
    assert len(imported_vault.get_children(None)) == roots_before - 4
    assert not any(imported_vault.has_note(note_id) for note_id in deletion.top_note_ids)
    assert all(imported_vault.has_note(note_id) for note_id in kept)
    assert virtual_folders.all_folder_tags() == ["Daily/2026/"]
    assert resets == [("client", "undo")]


def test_deleting_a_folders_notes_is_refused_when_their_count_changed(imported_vault: NoteStore) -> None:
    deletion = virtual_folder_usecases.notes_in_folder("Projects/")
    with pytest.raises(InputRejected, match="now holds"):
        virtual_folder_usecases.delete_folder_and_notes(
            folder="Projects/", expected_note_count=len(deletion.top_note_ids) + 1, token=TOKEN, client_id="client", undo_context="undo",
        )
    assert all(imported_vault.has_note(note_id) for note_id in deletion.top_note_ids)
