"""Virtual folders, an experiment (docs/ready-to-build/virtual-folders.md;
app/services/virtual_folders.py): the folders in a view and the folder its search chooses
(docs/ready-to-build/folder-tags-in-search.md)."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Request
from typing_extensions import TypedDict

from app.api.note_requests import Identifier, Nonnegative, Text, UndoContext, Viewport, ViewScope
from app.api.request_auth import require_request_auth_token
from app.api.transactions import transactional_route
from app.services.undo_state import reset_undo_stack
from app.services.input_errors import InputRejected
from app.services.tab_state import tab_state_store
from app.services.virtual_folders import (
    NO_FOLDER, all_folder_tags, chosen_folder_of, folder_note_counts, folder_note_totals, folder_paths, is_folder_tag,
    without_folder_terms,
)
from app.usecases.virtual_folders import (
    delete_folder, delete_folder_and_notes, file_note_in_folder, move_folder, notes_in_folder, rename_folder,
)

router = APIRouter(prefix="/virtual-folders", tags=["virtual-folders"])


class RenameVirtualFolderRequest(TypedDict):
    folder: Text
    # The whole new path, ending in / ('Archive/Client-A/').
    newPath: Text


class MoveVirtualFolderRequest(TypedDict):
    folder: Text
    # The folder to move it into, or '' for the top.
    into: Text


class DeleteVirtualFolderRequest(TypedDict):
    folder: Text
    # Also delete the notes filed in it (unchecked unless the user ticks it), if there are
    # still expectedNoteCount of them (0 when not deleting notes).
    deleteNotes: bool
    expectedNoteCount: Nonnegative
    clientId: Identifier
    undoContext: UndoContext


class FolderNotesRequest(TypedDict):
    folder: Text


class ChooseFolderRequest(TypedDict):
    # The folder context the folder was clicked in.
    tabId: Identifier
    # The folder tag ('Projects/Client-A/'), or '' for the top, `/`: every note.
    folder: Text
    clientId: Identifier
    undoContext: UndoContext


@router.post("")
@transactional_route
def list_virtual_folders(request: Request, body: ViewScope) -> Dict[str, object]:
    """The folder the search chooses, and every folder in the vault: the whole tree whatever the
    view shows (the maintainer, 2026-11-01: a tree following the search was confusing), each
    with how many notes clicking it would show (the top's under ''). The chosen folder is read
    from the search (`Projects/`), and the counts read the search without its folders, so choosing
    one doesn't dim the others (folder-tags-in-search.md §3)."""
    require_request_auth_token(request)
    if body["isUntaggedView"]:
        # Untagged notes are in no folder.
        counts = {path: 0 for path in [NO_FOLDER, *folder_paths()]}
    else:
        counts = folder_note_counts(without_folder_terms(body["search"]))
    chosen = chosen_folder_of(body["search"])
    return {
        # "folder": its one folder term; "top": none (`/`); "none": two, or folders joined by OR.
        "chosenKind": chosen.kind,
        "folder": chosen.folder,
        # The search contexts that are folder contexts, with the tree.
        "folderContexts": tab_state_store.folder_contexts(),
        "folders": all_folder_tags(),
        "noteCounts": counts,
        # Each folder's count with no search: a count the search narrows reads out of it
        # (docs/ready-to-build/folder-counts.md).
        "noteTotals": folder_note_totals(),
    }


@router.post("/folder-context/new")
@transactional_route
def create_folder_context(request: Request) -> Dict[str, object]:
    """Open folders tab with no folder context: a new one at the end of the list, on every note
    (docs/ready-to-build/virtual-folders.md, "Folder contexts"). The tab state answered; the browser switches to it."""
    require_request_auth_token(request)
    return tab_state_store.create_folder_context()


@router.post("/folder-context")
@transactional_route
def choose_folder(request: Request, body: ChooseFolderRequest) -> Dict[str, object]:
    """A folder clicked in the tree: the folder context it was clicked in searches it, its search
    before replaced. A new view, so its undo history starts again. The tab state answered."""
    require_request_auth_token(request)
    snapshot = tab_state_store.choose_folder(tab_id=body["tabId"], folder=body["folder"])
    reset_undo_stack(body["clientId"], body["undoContext"])
    return snapshot


class FileNoteInFolderRequest(TypedDict):
    noteId: Identifier
    # The folder tag ('Projects/Client-A/'), or '' for no folder (the tree's top).
    folder: Text
    clientId: Identifier
    undoContext: UndoContext
    viewport: Viewport


@router.post("/file-note")
@transactional_route
def file_note_in_virtual_folder(request: Request, body: FileNoteInFolderRequest) -> Dict[str, object]:
    """A root note dragged from the column onto a folder: in exactly that folder, one undo step."""
    token = require_request_auth_token(request)
    return file_note_in_folder(
        note_id=body["noteId"], folder=body["folder"], token=token,
        client_id=body["clientId"], undo_context=body["undoContext"], viewport=dict(body["viewport"]),
    )


@router.post("/rename")
@transactional_route
def rename_virtual_folder(request: Request, body: RenameVirtualFolderRequest) -> Dict[str, object]:
    """Rename a folder and every folder below it on every note (onto an existing one: a merge)."""
    token = require_request_auth_token(request)
    return rename_folder(folder=body["folder"], new_path=body["newPath"], token=token)


@router.post("/move")
@transactional_route
def move_virtual_folder(request: Request, body: MoveVirtualFolderRequest) -> Dict[str, object]:
    """Move a folder, with everything below it, into another ('' for the top)."""
    token = require_request_auth_token(request)
    return move_folder(folder=body["folder"], into=body["into"], token=token)


@router.post("/delete")
@transactional_route
def delete_virtual_folder(request: Request, body: DeleteVirtualFolderRequest) -> Dict[str, object]:
    """Take a folder, and every folder below it, off every note; the notes stay, unless the
    user chose to delete them too."""
    token = require_request_auth_token(request)
    if not body["deleteNotes"]:
        return delete_folder(folder=body["folder"], token=token)
    return delete_folder_and_notes(
        folder=body["folder"], expected_note_count=body["expectedNoteCount"], token=token,
        client_id=body["clientId"], undo_context=body["undoContext"],
    )


@router.post("/notes")
@transactional_route
def count_virtual_folder_notes(request: Request, body: FolderNotesRequest) -> Dict[str, object]:
    """How many notes deleting the folder's notes would delete, as the list counts notes (the
    notes under them go with them): Delete Folder's checkbox."""
    require_request_auth_token(request)
    if not is_folder_tag(body["folder"]):
        raise InputRejected(f"{body['folder']} is not a folder.")
    return {"noteCount": notes_in_folder(body["folder"]).note_count}

