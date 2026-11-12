"""Virtual folders, an experiment (app/services/virtual_folders.py): the folders come from the
search index's tag counts, and every folder's note count, worked out in one pass, is the
count clicking the folder shows (a search per folder)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

import pytest

import app.services.snapshot as snapshot_module
import app.usecases.import_obsidian_vault as import_module
import app.services.virtual_folders as virtual_folders
import app.usecases.virtual_folders as virtual_folder_usecases
from app.db.file_session import begin_file_writer
from app.services.background_work import background_work
from app.models.database import SafeSession
from app.security import encryption
from app.services.image_compression import ImageChoice
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
# Images as they are (the Images screen's first choice).
KEEP_ORIGINALS = ImageChoice(compresses=False, longest_side_px=2560)
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
        content_format=CONTENT_MARKDOWN, folder_prefix="", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT,
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


def test_the_totals_are_the_counts_with_no_search(imported_vault: NoteStore) -> None:
    # A count under a search reads out of the folder's total (docs/ready-to-build/folder-counts.md §2).
    assert virtual_folders.folder_note_totals() == virtual_folders.folder_note_counts("")


def test_the_totals_and_a_searchs_counts_are_kept_apart(imported_vault: NoteStore) -> None:
    searched = virtual_folders.folder_note_counts("urgent")
    totals = virtual_folders.folder_note_totals()
    assert virtual_folders.folder_note_counts("urgent") is searched, "asking for the totals kept the search's counts"
    assert totals["Daily/"] == 1 and searched["Daily/"] == 0


# --- Delete Folder, with its notes --------------------------------------------------------

def _root_titled(store: NoteStore, title: str) -> str:
    for root_id in store.get_children(None):
        if title in store.get_note(root_id).content:
            return root_id
    raise AssertionError(f"No root note titled {title}")


def test_a_folders_notes_are_the_notes_filed_in_it_and_below_it_with_their_subtrees(imported_vault: NoteStore) -> None:
    filed = [_root_titled(imported_vault, title) for title in ("Plan", "Notes", "Budget", "Overview")]
    deletion = virtual_folder_usecases.notes_in_folder("Projects/")
    assert sorted(deletion.top_note_ids) == sorted(filed)
    # Counted as the list counts notes; the notes under them go with them, uncounted.
    assert deletion.note_count == len(filed)
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


# Each tab's folder is kept in tab state; its tests are in test_tab_state.py.


# A root note dragged from the column onto a folder ends up in exactly that folder; dropped
# on the top, in none (docs/ready-to-build/virtual-folders.md §4).
@pytest.mark.parametrize(("tags", "folder", "refiled"), [
    ("work", "Projects/", "work Projects/"),
    ("work Archive/", "Projects/", "work Projects/"),
    ("Archive/ work Old/Stuff/", "Projects/Client-A/", "work Projects/Client-A/"),
    ("work Archive/", "", "work"),
    ("Archive/", "", ""),
    ("running:miles=3 Archive/", "Projects/", "running:miles=3 Projects/"),
])
def test_a_refiled_tag_bar_keeps_its_other_tags_and_has_only_the_target_folder(tags: str, folder: str, refiled: str) -> None:
    assert virtual_folders.refile_tag_bar(tags, folder) == refiled


def _file(note_id: str, folder: str) -> Dict[str, object]:
    return virtual_folder_usecases.file_note_in_folder(
        note_id=note_id, folder=folder, token=TOKEN, client_id="client", undo_context="undo", viewport={},
    )


def test_a_root_note_dropped_on_a_folder_moves_there_in_one_undo_step(imported_vault: NoteStore, monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[tuple[str, str, str]] = []
    monkeypatch.setattr(virtual_folder_usecases, "record_update", lambda client_id, undo_context, note_id, **step: recorded.append(
        (note_id, step["before_tags"], step["after_tags"])))
    plan = _root_titled(imported_vault, "Plan")
    before = imported_vault.get_note(plan).tags
    assert "Projects/Client-A/" in before.split()

    result = _file(plan, "Daily/")

    after = imported_vault.get_note(plan).tags
    assert result["tags"] == after
    assert [tag for tag in after.split() if virtual_folders.is_folder_tag(tag)] == ["Daily/"]
    assert [tag for tag in after.split() if not virtual_folders.is_folder_tag(tag)] == [
        tag for tag in before.split() if not virtual_folders.is_folder_tag(tag)]
    assert recorded == [(plan, before, after)]
    assert virtual_folder_usecases.notes_in_folder("Daily/").top_note_ids.count(plan) == 1


def test_a_root_note_in_no_folder_moves_into_one_and_one_dropped_on_the_top_leaves_every_folder(imported_vault: NoteStore, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(virtual_folder_usecases, "record_update", lambda *args, **kwargs: None)
    top = _root_titled(imported_vault, "Top")
    _file(top, "Projects/")
    assert top in virtual_folder_usecases.notes_in_folder("Projects/").top_note_ids
    budget = _root_titled(imported_vault, "Budget")
    _file(budget, "")
    assert not any(virtual_folders.is_folder_tag(tag) for tag in imported_vault.get_note(budget).tags.split())


def test_a_child_note_or_a_drop_that_changes_nothing_is_refused(imported_vault: NoteStore) -> None:
    plan = _root_titled(imported_vault, "Plan")
    child = imported_vault.get_children(plan)[0]
    tags = imported_vault.get_note(child).tags
    with pytest.raises(InputRejected, match="Only top-level notes can go in a folder"):
        _file(child, "Daily/")
    assert imported_vault.get_note(child).tags == tags
    with pytest.raises(InputRejected, match="already"):
        _file(plan, "Projects/Client-A/")
    with pytest.raises(InputRejected, match="not a folder"):
        _file(plan, "Daily")


def test_an_import_lists_its_progress_a_part_per_file(
    imported_vault: NoteStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[int, int]] = []
    real_store = import_module._store_one_file
    monkeypatch.setattr(import_module, "_store_one_file", lambda *args, **kwargs: (real_store(*args, **kwargs), seen.append(
        tuple((entry["done"], entry["total"]) for entry in background_work.snapshot() if entry["key"] == "import")[0]))[0])
    folder = tmp_path / "progress"
    folder.mkdir()
    (folder / "a.md").write_text("# A\n![[one.png]] ![[two.png]]\n")
    for name in ("one.png", "two.png"):
        (folder / name).write_bytes(b"png")
    CmdImportObsidianVault(
        source="obsidian", folder_path=str(folder), split_mode=SPLIT_HEADINGS_AND_LISTS, content_format=CONTENT_MARKDOWN,
        folder_prefix="Progress", add_to_existing=False, images=KEEP_ORIGINALS, token=TOKEN, imported_at=IMPORTED_AT,
    ).execute()
    # Seen as each file is stored, before its count goes up: out of the files it imports.
    assert seen == [(0, 2), (1, 2)]
    assert background_work.snapshot() == []
