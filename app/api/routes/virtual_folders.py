"""Virtual folders, an experiment (docs/ready-to-build/virtual-folders.md;
app/services/virtual_folders.py): the folders in a view and a tab's
folder filter. Nothing here is stored: the experiment may be dropped."""

from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, Request
from typing_extensions import TypedDict

from app.api.note_requests import Identifier, Nonnegative, Text, UndoContext, ViewScope
from app.api.request_auth import require_request_auth_token
from app.api.transactions import transactional_route
from app.services.undo_state import reset_undo_stack
from app.services.input_errors import InputRejected
from app.services.virtual_folders import NO_FOLDER, all_folder_tags, folder_note_counts, folder_paths, is_folder_tag, virtual_folder_state
from app.usecases.virtual_folders import delete_folder, delete_folder_and_notes, move_folder, notes_in_folder, rename_folder

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


class VirtualFolderFilterRequest(TypedDict):
    tabId: Identifier
    # The folder tag ('Projects/Client-A/'), or '' for every folder again.
    folder: Text
    clientId: Identifier
    undoContext: UndoContext


@router.post("")
@transactional_route
def list_virtual_folders(request: Request, body: ViewScope) -> Dict[str, object]:
    """The tab's folder filter, and every folder in the vault: the whole tree whatever the
    view shows (the maintainer, 2026-11-01: a tree following the search was confusing), each
    with how many notes clicking it would show (the top's under '')."""
    require_request_auth_token(request)
    if body["isUntaggedView"]:
        # Untagged notes are in no folder.
        counts = {path: 0 for path in [NO_FOLDER, *folder_paths()]}
    else:
        counts = folder_note_counts(body["search"])
    return {
        "folder": virtual_folder_state.filter_of(body["tabId"]),
        "folders": all_folder_tags(),
        "noteCounts": counts,
    }


@router.post("/filter")
@transactional_route
def set_virtual_folder_filter(request: Request, body: VirtualFolderFilterRequest) -> Dict[str, object]:
    """Narrow a tab to exactly one folder ('' for every folder again): a new view, so its
    undo history starts again, as for a Files filter."""
    require_request_auth_token(request)
    tab_id = body["tabId"]
    changed = virtual_folder_state.filter_of(tab_id) != body["folder"]
    virtual_folder_state.set_filter(tab_id, body["folder"])
    if changed:
        reset_undo_stack(body["clientId"], body["undoContext"])
    return {"folder": virtual_folder_state.filter_of(tab_id), "changed": changed}


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
    return {"noteCount": len(notes_in_folder(body["folder"]).top_note_ids)}

