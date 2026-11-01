"""Renaming, moving and deleting virtual folders, an experiment
(docs/ready-to-build/virtual-folders.md §4–§5; app/services/virtual_folders.py). A folder is
its tag and every tag below it (`Projects/` and `Projects/Client-A/`): each is renamed or
deleted on every note, with the rules mentioning it, through the tag rename and delete Edit
Tag Relationships uses. Renaming onto a folder that exists merges the two."""

from __future__ import annotations

from typing import Dict, List

from app.services.input_errors import InputRejected
from app.services.note_store import store as note_store
from app.services.search_index import extract_ordered_tags_for_search, search_index
from app.services.search_query import SearchClause
from app.services.sync import generate_new_uuid
from app.services.undo_state import reset_undo_stack
from app.services.virtual_folders import FOLDER_MARK, all_folder_tags, is_folder_tag, virtual_folder_state
from app.usecases.delete_notes_in_view import NotesToDelete, topmost_with_subtrees
from app.usecases.delete_subtree import apply_delete_subtree
from app.usecases.delete_tag import apply_delete_tag_everywhere
from app.usecases.rename_tag import apply_rename_tag_everywhere


def folder_tags_under(folder: str) -> List[str]:
    """The folder's own tag and every folder tag below it that some note carries."""
    assert is_folder_tag(folder), folder
    return [tag for tag in all_folder_tags() if tag.casefold().startswith(folder.casefold())]


def rename_folder(*, folder: str, new_path: str, token: str) -> Dict[str, object]:
    """Rename (or move: the same thing) a folder and everything below it to new_path."""
    if not is_folder_tag(folder) or not is_folder_tag(new_path):
        raise InputRejected("A folder's name is a tag ending in /, with no spaces.")
    if new_path.casefold() == folder.casefold():
        return {"renamedTagCount": 0}
    if new_path.casefold().startswith(folder.casefold()):
        raise InputRejected(f"{folder} can't go into itself or one of its own folders.")
    tags = folder_tags_under(folder)
    for tag in tags:
        apply_rename_tag_everywhere(old=tag, new=new_path + tag[len(folder):], token=token)
    virtual_folder_state.move_filters(folder, new_path)
    return {"renamedTagCount": len(tags)}


def move_folder(*, folder: str, into: str, token: str) -> Dict[str, object]:
    """Move a folder into another ('' for the top), keeping its name."""
    if into != "" and not is_folder_tag(into):
        raise InputRejected(f"{into} is not a folder.")
    name = folder.rstrip(FOLDER_MARK).split(FOLDER_MARK)[-1]
    return rename_folder(folder=folder, new_path=f"{into}{name}{FOLDER_MARK}", token=token)


def notes_in_folder(folder: str) -> NotesToDelete:
    """The notes filed in the folder or a folder below it (carrying its tag themselves), each
    with everything under it: what Delete Folder's "also delete its notes" deletes. A note in
    it only through a note it embeds stays. Delete Folder counts them as the list counts
    notes, the notes under them not on their own (the maintainer, 2026-11-01: the total
    should drop by the number the dialog gave): len(top_note_ids)."""
    tags = folder_tags_under(folder)
    tag_keys = {tag.casefold() for tag in tags}
    filed: set[str] = set()
    for tag in tags:
        for note_id in search_index.query_clause_note_ids(_tag_clause(tag)):
            own = {own_tag.casefold() for own_tag in extract_ordered_tags_for_search(note_store.get_note(note_id).tags)}
            if own & tag_keys:
                filed.add(note_id)
    return topmost_with_subtrees(frozenset(filed))


def _tag_clause(tag: str) -> SearchClause:
    return SearchClause(
        required_tags=frozenset({tag}), forbidden_tags=frozenset(), required_text=(), forbidden_text=(),
        required_properties=(), forbidden_properties=(),
    )


def delete_folder(*, folder: str, token: str) -> Dict[str, object]:
    """Take the folder and every folder below it off every note; the notes stay, unfiled."""
    if not is_folder_tag(folder):
        raise InputRejected(f"{folder} is not a folder.")
    tags = folder_tags_under(folder)
    for tag in tags:
        apply_delete_tag_everywhere(tag=tag, token=token)
    virtual_folder_state.drop_filters_under(folder)
    return {"deletedTagCount": len(tags)}


def delete_folder_and_notes(
    *, folder: str, expected_note_count: int, token: str, client_id: str, undo_context: str,
) -> Dict[str, object]:
    """Delete the notes filed in the folder (notes_in_folder), if still the count the user
    confirmed, then the folder itself. A bulk deletion: it clears undo and redo, as deleting
    the notes in a view does."""
    if not is_folder_tag(folder):
        raise InputRejected(f"{folder} is not a folder.")
    deletion = notes_in_folder(folder)
    note_count = deletion.note_count
    if note_count != expected_note_count:
        raise InputRejected(
            f"{folder} now holds {note_count} notes, not the {expected_note_count} you confirmed. "
            "Nothing was deleted; try again."
        )
    for note_id in deletion.top_note_ids:
        apply_delete_subtree(note_id)
    result = delete_folder(folder=folder, token=token)
    reset_undo_stack(client_id, undo_context)
    return {**result, "deletedNoteCount": note_count, "updateUUID": generate_new_uuid()}
