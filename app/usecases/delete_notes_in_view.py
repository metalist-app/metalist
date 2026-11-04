"""Deleting the notes a view shows (the maintainer, 2026-10-31; docs/ui/command-palette.md):
with a search (or the untagged view, a date range, a file filter), each note it finds
with everything under it, a note above a match that does not match itself staying; with
none, every note in the vault. Counted first for the confirmation, then deleted only if
the count still holds. A bulk operation: it clears undo and redo, as others do."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from app.services.input_errors import InputRejected
from app.services.snapshot import ResolvedViewScope
from app.services.store import store
from app.services.sync import generate_new_uuid
from app.services.undo_state import reset_undo_stack
from app.usecases.base import QueryCommand
from app.usecases.delete_subtree import apply_delete_subtree

# The root notes' parent: the top of the list.
_TOP_LEVEL = None


@dataclass(frozen=True)
class NotesToDelete:
    """The notes a deletion takes: the topmost ones, each with its subtree, and how many of
    them, counted as the list counts notes: the notes under them go with them, uncounted (the
    maintainer, 2026-11-01: a count of every note under them was confusing)."""

    top_note_ids: List[str]
    note_count: int
    is_whole_vault: bool


def notes_to_delete(scope: ResolvedViewScope) -> NotesToDelete:
    """What deleting in the view takes: the notes it finds, none under another found one."""
    if not scope.filter_active:
        roots = store.children(_TOP_LEVEL)
        return NotesToDelete(top_note_ids=roots, note_count=len(roots), is_whole_vault=True)
    return topmost_with_subtrees(scope.matched_note_ids)


def topmost_with_subtrees(note_ids: frozenset[str]) -> NotesToDelete:
    """Deleting note_ids, each with everything under it: the ones under no other of them, in
    list order, and how many they are."""
    top = [note_id for note_id in _in_list_order(note_ids) if not _has_matched_ancestor(note_id, note_ids)]
    return NotesToDelete(top_note_ids=top, note_count=len(top), is_whole_vault=False)


def _in_list_order(note_ids: frozenset[str]) -> List[str]:
    """note_ids as the list shows them, top to bottom."""
    ordered: List[str] = []
    stack = list(reversed(store.children(_TOP_LEVEL)))
    while stack:
        note_id = stack.pop()
        if note_id in note_ids:
            ordered.append(note_id)
        stack.extend(reversed(store.children(note_id)))
    return ordered


def _has_matched_ancestor(note_id: str, matched: frozenset[str]) -> bool:
    parent_id = store.get(note_id).parent_id
    while parent_id is not None:
        if parent_id in matched:
            return True
        parent_id = store.get(parent_id).parent_id
    return False


@dataclass
class CmdDeleteNotesInView(QueryCommand):
    """Delete what the view finds, if it is still the expected_note_count the user confirmed."""

    scope: ResolvedViewScope
    expected_note_count: int
    client_id: str
    undo_context: str

    def execute(self) -> Dict[str, object]:
        deletion = notes_to_delete(self.scope)
        if deletion.note_count != self.expected_note_count:
            raise InputRejected(
                f"This view now holds {deletion.note_count} notes, not the {self.expected_note_count} you confirmed. "
                "Nothing was deleted; try again."
            )
        for note_id in deletion.top_note_ids:
            apply_delete_subtree(note_id)
        reset_undo_stack(self.client_id, self.undo_context)
        return {"status": "success", "deletedCount": deletion.note_count, "updateUUID": generate_new_uuid()}
