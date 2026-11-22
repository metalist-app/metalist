"""Importing a folder again (docs/ready-to-build/import-export-launch.md §5, "Importing again"; the maintainer, 2026-11-20,
going back on "an import only adds"): the files that came in before are recognized, Keep both
adds them again, Replace puts a changed file's new notes in its old notes' place and leaves an
unchanged file alone, and notes edited in MetaList are replaced only when asked. "Changed
since" brings in only the files changed on or after a day."""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.services.content_cache as content_cache
from app.db.import_origins_sql import fetch_all_import_origins
from app.db.session import begin_writer
from app.services import import_origins
from app.services.input_errors import InputRejected
from app.services.note_store import NoteStore
from app.services.obsidian_import.tree import CONTENT_MARKDOWN, SPLIT_NONE
from app.usecases.delete_subtree import apply_delete_subtree
from app.usecases.import_again import changed_since_day
from app.usecases.import_obsidian_vault import (
    NOTHING_TO_BRING_IN,
    CmdImportFolderOfFiles,
    CmdImportObsidianVault,
    CmdPreviewFolderOfFiles,
    CmdPreviewImport,
    FileSelection,
)
from tests.unit.test_obsidian_import import IMPORTED_AT, KEEP_ORIGINALS, TOKEN, first_line, imported_roots
from tests.unit.test_obsidian_import import note_store  # noqa: F401  (the vault these imports go into)

FIRST_IMPORT = IMPORTED_AT
SECOND_IMPORT = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)
RECIPES = {"Bread.md": "Flour and water", "Soup.md": "See [[Bread]]", "Tea.md": "Leaves"}
EVERY_FILE = FileSelection(excluded_groups=(), excluded_files=(), included_files=(), keeps_markdown_as_files=False)
NOTHING_BEFORE = {"importedAt": "", "fileCount": 0, "changedCount": 0, "editedCount": 0, "edited": []}


def _write(folder: Path, files: dict[str, str]) -> None:
    folder.mkdir(exist_ok=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def _recipes(tmp_path: Path) -> Path:
    folder = tmp_path / "Recipes"
    _write(folder, RECIPES)
    return folder


def _import(folder: Path, *, earlier_notes: str, changed_since: str, imported_at: datetime, prefix: str) -> dict[str, object]:
    return CmdImportObsidianVault(
        source="markdown", folder_path=str(folder), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix=prefix, add_to_existing=True, images=KEEP_ORIGINALS, token=TOKEN, imported_at=imported_at,
        folder_name=folder.name, changed_since=changed_since, earlier_notes=earlier_notes,
    ).execute()


def _preview(folder: Path, *, earlier_notes: str, changed_since: str) -> dict[str, object]:
    return CmdPreviewImport(
        source="markdown", folder_path=str(folder), split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", imported_at=SECOND_IMPORT, folder_name=folder.name, changed_since=changed_since,
        earlier_notes=earlier_notes,
    ).execute()


def _first_import(folder: Path) -> None:
    _import(folder, earlier_notes="keep", changed_since="", imported_at=FIRST_IMPORT, prefix="")


def _titles(store: NoteStore) -> list[str]:
    return [first_line(store, note_id) for note_id in imported_roots(store)]


def _id_of(store: NoteStore, title: str) -> str:
    [note_id] = [note_id for note_id in imported_roots(store) if first_line(store, note_id) == title]
    return note_id


def _edit(note_id: str, content: str) -> None:
    """As an edit in MetaList leaves the vault's text of a note."""
    content_cache.cache_note(note_id, content)


def test_a_first_import_meets_nothing_and_is_recorded(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    assert _preview(folder, earlier_notes="keep", changed_since="")["again"] == NOTHING_BEFORE

    _first_import(folder)

    earlier = import_origins.earlier_files(folder_name="Recipes", prefix_folder="")
    assert sorted(earlier) == sorted(RECIPES)
    assert {found.imported_at for found in earlier.values()} == {FIRST_IMPORT}
    assert earlier["Bread.md"].file.root_id == _id_of(note_store, "Bread")


def test_the_preview_says_what_came_in_before_changed_and_was_edited(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    _write(folder, {"Bread.md": "Flour, water and salt", "Tea.md": "Leaves and hot water", "Cake.md": "New"})
    _edit(_id_of(note_store, "Tea"), "<div>Tea</div><div>My own way</div>")

    again = _preview(folder, earlier_notes="keep", changed_since="")["again"]

    assert again == {
        "importedAt": FIRST_IMPORT.isoformat(), "fileCount": 3, "changedCount": 2, "editedCount": 1, "edited": ["Tea.md"],
    }


def test_keep_both_adds_every_file_again_beside_the_old_notes(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    before = imported_roots(note_store)

    _import(folder, earlier_notes="keep", changed_since="", imported_at=SECOND_IMPORT, prefix="")

    after = imported_roots(note_store)
    assert after[:len(before)] == before
    assert _titles(note_store) == ["Bread", "Soup", "Tea", "Bread", "Soup", "Tea"]


def test_replace_puts_a_changed_files_notes_in_the_old_ones_place_and_leaves_the_rest(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    before = imported_roots(note_store)
    soup_before = note_store.get_note(_id_of(note_store, "Soup")).content
    _write(folder, {"Bread.md": "Flour, water and salt", "Cake.md": "New"})

    result = _import(folder, earlier_notes="replace", changed_since="", imported_at=SECOND_IMPORT, prefix="")

    # Bread in its place under its old id, Soup and Tea untouched, Cake after the last note.
    after = imported_roots(note_store)
    assert after[:len(before)] == before
    assert _titles(note_store) == ["Bread", "Soup", "Tea", "Cake"]
    bread = _id_of(note_store, "Bread")
    assert "Flour, water and salt" in note_store.get_note(bread).content
    # Soup's link to Bread, written by the first import, still leads to Bread's note.
    assert note_store.get_note(_id_of(note_store, "Soup")).content == soup_before
    assert bread in soup_before
    assert result["noteCount"] == 2
    # The next import meets Bread as it is now.
    assert _preview(folder, earlier_notes="replace", changed_since="")["again"]["changedCount"] == 0


def test_replace_keeps_a_replaced_note_where_it_was_moved(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    _write(folder, {"Soup.md": "Stock and [[Bread]]"})
    soup = _id_of(note_store, "Soup")

    _import(folder, earlier_notes="replace", changed_since="", imported_at=SECOND_IMPORT, prefix="")

    # Between Bread and Tea, as before, and its link leads to the Bread that stayed.
    assert _titles(note_store) == ["Bread", "Soup", "Tea"]
    assert _id_of(note_store, "Soup") == soup
    assert _id_of(note_store, "Bread") in note_store.get_note(soup).content


def test_replace_keeps_both_for_a_note_edited_in_metalist(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    tea = _id_of(note_store, "Tea")
    _edit(tea, "<div>Tea</div><div>My own way</div>")
    _write(folder, {"Tea.md": "Leaves and hot water"})

    _import(folder, earlier_notes="replace", changed_since="", imported_at=SECOND_IMPORT, prefix="")

    # The edited note stays as it is, and the file's new notes come in beside it.
    assert content_cache.get_cached_content(tea) == "<div>Tea</div><div>My own way</div>"
    assert _titles(note_store) == ["Bread", "Soup", "Tea", "Tea"]
    assert "Leaves and hot water" in note_store.get_note(imported_roots(note_store)[-1]).content


def test_replace_takes_the_edited_notes_too_when_asked(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    tea = _id_of(note_store, "Tea")
    _edit(tea, "<div>Tea</div><div>My own way</div>")
    _write(folder, {"Tea.md": "Leaves and hot water"})

    _import(folder, earlier_notes="replace-edited", changed_since="", imported_at=SECOND_IMPORT, prefix="")

    assert _titles(note_store) == ["Bread", "Soup", "Tea"]
    assert "Leaves and hot water" in note_store.get_note(tea).content


def test_an_edited_note_whose_file_did_not_change_is_never_replaced(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    tea = _id_of(note_store, "Tea")
    _edit(tea, "<div>Tea</div><div>My own way</div>")
    _write(folder, {"Bread.md": "Flour, water and salt"})

    _import(folder, earlier_notes="replace-edited", changed_since="", imported_at=SECOND_IMPORT, prefix="")

    assert content_cache.get_cached_content(tea) == "<div>Tea</div><div>My own way</div>"
    assert _titles(note_store) == ["Bread", "Soup", "Tea"]


def test_replace_with_nothing_changed_brings_nothing_in_and_says_so(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)

    assert _preview(folder, earlier_notes="replace", changed_since="")["rootNoteCount"] == 0
    with pytest.raises(InputRejected) as refused:
        _import(folder, earlier_notes="replace", changed_since="", imported_at=SECOND_IMPORT, prefix="")

    assert str(refused.value) == NOTHING_TO_BRING_IN
    assert _titles(note_store) == ["Bread", "Soup", "Tea"]


def test_a_deleted_note_no_longer_counts_as_imported_before(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _first_import(folder)
    apply_delete_subtree(_id_of(note_store, "Tea"))

    again = _preview(folder, earlier_notes="replace", changed_since="")["again"]

    assert again["fileCount"] == 2


@pytest.mark.parametrize(("folder_name", "prefix"), [("Other", ""), ("Recipes", "Kitchen")], ids=["another-folder", "another-place"])
def test_another_folder_or_another_place_is_not_the_same_import(
    tmp_path: Path, note_store: NoteStore, folder_name: str, prefix: str,
) -> None:
    _first_import(_recipes(tmp_path))
    folder = tmp_path / folder_name
    _write(folder, RECIPES)

    _import(folder, earlier_notes="replace", changed_since="", imported_at=SECOND_IMPORT, prefix=prefix)

    assert _titles(note_store) == ["Bread", "Soup", "Tea", "Bread", "Soup", "Tea"]


# --- Changed since ---------------------------------------------------------------------------

def _changed_on(path: Path, day: datetime) -> None:
    os.utime(path, (day.timestamp(), day.timestamp()))


def test_changed_since_brings_in_only_the_files_changed_that_day_or_later(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    _changed_on(folder / "Bread.md", datetime(2026, 10, 31, 23, 59))
    _changed_on(folder / "Soup.md", datetime(2026, 11, 1, 0, 0))
    _changed_on(folder / "Tea.md", datetime(2026, 11, 5, 12, 0))

    assert _preview(folder, earlier_notes="keep", changed_since="2026-11-01")["fileCount"] == 2
    _import(folder, earlier_notes="keep", changed_since="2026-11-01", imported_at=FIRST_IMPORT, prefix="")

    assert _titles(note_store) == ["Soup", "Tea"]


def test_changed_since_with_no_file_changed_says_so(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    for name in RECIPES:
        _changed_on(folder / name, datetime(2026, 10, 1, 12, 0))

    with pytest.raises(InputRejected, match="No file in the folder changed since 2026-11-01"):
        _import(folder, earlier_notes="keep", changed_since="2026-11-01", imported_at=FIRST_IMPORT, prefix="")


@pytest.mark.parametrize("typed", ["yesterday", "2026-13-01", "2026-02-30", "0000-01-01", "2026-1-1"])
def test_changed_since_refuses_what_is_no_day(typed: str) -> None:
    with pytest.raises(InputRejected):
        changed_since_day(typed)


def test_changed_since_empty_is_no_day() -> None:
    assert changed_since_day("") is None


# --- A folder of any files ---------------------------------------------------------------------

def _import_files(folder: Path, *, earlier_notes: str, changed_since: str, imported_at: datetime) -> dict[str, object]:
    return CmdImportFolderOfFiles(
        folder_path=str(folder), selection=EVERY_FILE, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=True, images=KEEP_ORIGINALS, token=TOKEN, imported_at=imported_at,
        folder_name=folder.name, changed_since=changed_since, earlier_notes=earlier_notes,
    ).execute()


def test_a_file_kept_as_a_file_is_replaced_in_place_when_it_changed(tmp_path: Path, note_store: NoteStore) -> None:
    folder = tmp_path / "Papers"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"%PDF one")
    (folder / "b.pdf").write_bytes(b"%PDF two")
    (folder / "notes.md").write_text("Notes", encoding="utf-8")
    _import_files(folder, earlier_notes="keep", changed_since="", imported_at=FIRST_IMPORT)
    before = imported_roots(note_store)
    contents_before = [note_store.get_note(note_id).content for note_id in before]
    (folder / "b.pdf").write_bytes(b"%PDF two, revised")

    preview = CmdPreviewFolderOfFiles(
        folder_path=str(folder), selection=EVERY_FILE, split_mode=SPLIT_NONE, content_format=CONTENT_MARKDOWN,
        folder_prefix="", imported_at=SECOND_IMPORT, folder_name="Papers", changed_since="", earlier_notes="replace",
    ).execute()
    result = _import_files(folder, earlier_notes="replace", changed_since="", imported_at=SECOND_IMPORT)

    assert preview["again"] == {
        "importedAt": FIRST_IMPORT.isoformat(), "fileCount": 3, "changedCount": 1, "editedCount": 0, "edited": [],
    }
    assert (preview["rootNoteCount"], result["noteCount"]) == (1, 1)
    # The same notes in the same order; only b.pdf's note shows another stored file.
    assert imported_roots(note_store) == before
    contents_after = [note_store.get_note(note_id).content for note_id in before]
    assert [was == now for was, now in zip(contents_before, contents_after)] == [True, False, True]


# --- The record with and without a password ----------------------------------------------------

class _ReversingService:
    """Stands for the vault's key: what it stores is not what it was given."""

    dek = b"key"

    def encrypt_for_storage(self, text: str) -> tuple[str, bytes, bytes]:
        return text[::-1], b"n" * 12, b"t" * 16

    def decrypt_from_storage(self, stored: str, nonce: bytes, tag: bytes) -> str:
        assert (nonce, tag) == (b"n" * 12, b"t" * 16)
        return stored[::-1]


def test_setting_and_removing_a_password_rewrites_every_record(tmp_path: Path, note_store: NoteStore) -> None:
    _first_import(_recipes(tmp_path))
    service = _ReversingService()
    with begin_writer() as connection:
        [plain] = fetch_all_import_origins(connection)
        assert import_origins.rewrite_persisted_import_origins(connection=connection, encryption_service=service, force_plaintext=False) == 1
        [encrypted] = fetch_all_import_origins(connection)
        assert import_origins.rewrite_persisted_import_origins(connection=connection, encryption_service=service, force_plaintext=False) == 0
        assert import_origins.rewrite_persisted_import_origins(connection=connection, encryption_service=service, force_plaintext=True) == 1
        [decrypted] = fetch_all_import_origins(connection)

    assert "Bread.md" in plain.state_json and plain.state_encryption_nonce is None
    assert "Bread.md" not in encrypted.state_json and encrypted.state_encryption_nonce == b"n" * 12
    assert decrypted == plain


# --- Links to notes this import does not write (found 2026-11-21, after 0.32.0) -----------------
# A link from a note that comes in to a note the import leaves alone (left out by Changed since,
# or unchanged under Replace) leads to that note where it is in the vault already, and never to
# a note that does not exist.

_REFERENCE_RE = re.compile(r"\[\[([0-9a-f-]{36})")


def _every_reference_leads_somewhere(store: NoteStore) -> bool:
    return all(
        store.has_note(target)
        for note_id in store.snapshot()
        for target in _REFERENCE_RE.findall(html.unescape(store.get_note(note_id).content))
    )


def test_changed_since_links_to_a_note_left_out_that_is_in_the_vault(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    for name in RECIPES:
        _changed_on(folder / name, datetime(2026, 10, 1, 12, 0))
    _first_import(folder)
    bread = _id_of(note_store, "Bread")
    _write(folder, {"Soup.md": "Stock, and see [[Bread]]"})

    _import(folder, earlier_notes="replace", changed_since="2026-11-01", imported_at=SECOND_IMPORT, prefix="")

    assert _titles(note_store) == ["Bread", "Soup", "Tea"]
    assert bread in note_store.get_note(_id_of(note_store, "Soup")).content


def test_changed_since_leaves_a_link_as_written_when_its_note_never_came_in(tmp_path: Path, note_store: NoteStore) -> None:
    folder = _recipes(tmp_path)
    for name in ("Bread.md", "Tea.md"):
        _changed_on(folder / name, datetime(2026, 10, 1, 12, 0))
    # The Summary counts the link as one that stays as written.
    assert _preview(folder, earlier_notes="keep", changed_since="2026-11-01")["missingLinkCount"] == 1

    _import(folder, earlier_notes="keep", changed_since="2026-11-01", imported_at=FIRST_IMPORT, prefix="")

    assert _titles(note_store) == ["Soup"]
    # Now that Soup is in the vault, nothing of the folder changed since the day leads nowhere.
    soup = html.unescape(note_store.get_note(_id_of(note_store, "Soup")).content)
    assert "[[Bread]]" in soup
    assert _REFERENCE_RE.findall(soup) == []


def test_replace_links_to_a_heading_of_an_unchanged_file_lead_to_its_note(tmp_path: Path, note_store: NoteStore) -> None:
    folder = tmp_path / "Recipes"
    _write(folder, {"Bread.md": "Intro\n\n## Dough\n\nFlour and water", "Soup.md": "See [[Bread#Dough]]"})
    CmdImportObsidianVault(
        source="markdown", folder_path=str(folder), split_mode="paragraphs", content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=True, images=KEEP_ORIGINALS, token=TOKEN, imported_at=FIRST_IMPORT,
        folder_name="Recipes", changed_since="", earlier_notes="keep",
    ).execute()
    assert _every_reference_leads_somewhere(note_store)
    bread = _id_of(note_store, "Bread")
    _write(folder, {"Soup.md": "Stock, and see [[Bread#Dough]]"})

    CmdImportObsidianVault(
        source="markdown", folder_path=str(folder), split_mode="paragraphs", content_format=CONTENT_MARKDOWN,
        folder_prefix="", add_to_existing=True, images=KEEP_ORIGINALS, token=TOKEN, imported_at=SECOND_IMPORT,
        folder_name="Recipes", changed_since="", earlier_notes="replace",
    ).execute()

    assert _every_reference_leads_somewhere(note_store)
    soup_notes = [
        html.unescape(note_store.get_note(note_id).content) for note_id in note_store.snapshot()
        if "Stock, and see" in note_store.get_note(note_id).content
    ]
    assert len(soup_notes) == 1 and bread in soup_notes[0]
