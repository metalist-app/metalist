"""The files that go with notes deleted in bulk (the maintainer, 2026-11-18): Delete Folder with
its notes and Delete Notes (Current View) say how many files and how much space go with the
notes, and delete them in the same step, with no Trim Unused Files afterwards.

A file goes when the deleted notes use it and nothing else could: no note that stays, no
other tab's undo or redo history, no tab's copied note (unused_files.py). The deletion clears
the deleting tab's own undo, so that history keeps nothing. Files already unused before the
deletion are not its files: Trim Unused Files still removes those."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.file_registry import file_registry
from app.services.file_storage import delete_unused_files, stored_size_of_files, unused_file_ids
from app.services.note_store import store as note_store
from app.services.unused_files import files_undo_or_paste_could_restore, files_undo_or_paste_could_restore_once_cleared


@dataclass(frozen=True)
class FilesOfNotes:
    """The files a bulk deletion takes with its notes, and the space their content takes."""

    file_ids: frozenset[str]
    size_bytes: int

    @property
    def count(self) -> int:
        return len(self.file_ids)


def _with_notes_under(top_note_ids: Sequence[str]) -> frozenset[str]:
    note_ids: set[str] = set()
    waiting = list(top_note_ids)
    while waiting:
        note_id = waiting.pop()
        assert note_id not in note_ids, f"note {note_id} is under two of the notes to delete"
        note_ids.add(note_id)
        waiting.extend(note_store.get_children(note_id))
    return frozenset(note_ids)


def files_of_notes_to_delete(top_note_ids: Sequence[str], *, client_id: str) -> FilesOfNotes:
    """The files deleting these notes, each with everything under it, would take: counted for
    the confirmation, and read again, before the notes go, by the deletion itself."""
    assert isinstance(client_id, str) and client_id != "", "the deleting tab is named"
    only_theirs = note_store.targets_referenced_only_by(_with_notes_under(top_note_ids)) & file_registry.list_ids()
    file_ids = frozenset(only_theirs - files_undo_or_paste_could_restore_once_cleared(client_id))
    return FilesOfNotes(file_ids=file_ids, size_bytes=stored_size_of_files(set(file_ids)))


def delete_files_of_deleted_notes(files: FilesOfNotes) -> int:
    """Delete the files found before their notes were deleted and the tab's undo cleared: those
    of them still unused now. Returns how many went."""
    if not files.file_ids:
        return 0
    still_unused = unused_file_ids(kept_file_ids=files_undo_or_paste_could_restore()) & files.file_ids
    deleted = delete_unused_files(still_unused)
    assert deleted.deleted_count == len(still_unused), "every file found unused was deleted"
    return deleted.deleted_count
