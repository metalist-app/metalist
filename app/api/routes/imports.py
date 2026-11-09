"""Importing from other apps: the developer version (PLAN.md) of the Obsidian import and of
the plain Markdown folder import (slice 1c), in every environment (the maintainer,
2026-10-31), and a folder of any files (docs/ready-to-build/folder-import-and-file-previews.md)."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from collections.abc import Mapping
from typing import Annotated, List, Literal

from typing_extensions import TypedDict

from fastapi import APIRouter, Request
from pydantic import ConfigDict, Field, with_config

from app.api.note_requests import Identifier, Text
from app.api.request_auth import require_request_auth_token
from app.api.transactions import transactional_route
from app.api.streaming_upload import FilePart, declared_body_bytes, receive_upload
from app.services import import_uploads
from app.data_directory import resolve_data_directory
from app.services.input_errors import InputRejected
from app.services.native_folder_picker import pick_folder
from app.services.obsidian_import.file_groups import FolderFile, file_groups, folder_files
from app.services.obsidian_import.import_folder import DiskFolder
from app.services.obsidian_import.notes import import_folder_prefix
from app.services.obsidian_import.sources import FILES, IMPORT_SOURCES
from app.services.image_compression import COMPRESSIBLE_SUFFIXES, IMAGE_LONGEST_SIDES, ImageChoice
from app.services.obsidian_import.vault import count_compressible_images, count_markdown_files
from app.services.reference_suggestions import build_catalog_in_background
from app.services.tab_state import tab_state_store
from app.services.disk_space import full_disk_is_rejected, require_room_for_files
from app.upload_limits import MAX_IN_MEMORY_FILE_BYTES
from app.usecases.import_bookmarks import CmdImportBookmarks, CmdPreviewBookmarkImport
from app.usecases.import_obsidian_vault import (
    CmdEstimateImportImages,
    CmdImportFolderOfFiles,
    CmdImportObsidianVault,
    CmdPreviewFolderOfFiles,
    CmdPreviewImport,
    FileSelection,
    drop_context_tags,
    import_folder_exists,
)

router = APIRouter(prefix="/import", tags=["import"])

# A folder path as the operating system's folder dialog gives it.
_MAX_FOLDER_PATH_LENGTH = 4096
# obsidian_import.sources' IMPORT_SOURCES.
ImportSourceKey = Literal["obsidian", "markdown", "files"]
# obsidian_import.file_groups' FILE_GROUP_KINDS: the checklist's rows a folder of files leaves out.
FileGroupKey = Literal[
    "hidden", "dependencies", "build", "text", "images", "pdf", "documents", "spreadsheets", "presentations",
    "audio", "video", "archives", "code", "other",
]


@with_config(ConfigDict(strict=True))
class ImportDropContext(TypedDict):
    """Where files dropped on the page were dropped (the maintainer, 2026-11-03): their notes take
    that search context's tags and show in it. isDrop false for an import from the menu, whose
    notes take none."""

    isDrop: bool
    tabId: Identifier
    # The context's search, '' for none.
    search: Text


@with_config(ConfigDict(strict=True))
class PickImportFolderRequest(TypedDict):
    source: ImportSourceKey


@with_config(ConfigDict(strict=True))
class ImportFolderRequest(TypedDict):
    source: ImportSourceKey
    folderPath: Annotated[str, Field(min_length=1, max_length=_MAX_FOLDER_PATH_LENGTH)]
    # obsidian_import.tree's SPLIT_MODES and CONTENT_FORMATS (import-export-launch.md §2.2).
    splitMode: Literal["none", "headings-and-lists", "paragraphs"]
    contentFormat: Literal["rich", "markdown"]
    # The folder everything goes under, as typed ('' for none), and whether to add to it when
    # it exists already (docs/ready-to-build/import-prefix-folder.md).
    prefixFolder: Annotated[str, Field(max_length=_MAX_FOLDER_PATH_LENGTH)]
    addToExisting: bool
    # A folder of files: the kinds of file unticked in the checklist, and the files ticked
    # against their kind (by path in the folder): left out of a ticked kind, brought in from
    # an unticked one. All empty for the other sources.
    excludedGroups: List[FileGroupKey]
    excludedFiles: List[Annotated[str, Field(min_length=1, max_length=_MAX_FOLDER_PATH_LENGTH)]]
    includedFiles: List[Annotated[str, Field(min_length=1, max_length=_MAX_FOLDER_PATH_LENGTH)]]
    # A folder of files: its Markdown files kept as files instead of turned into notes.
    keepsMarkdownAsFiles: bool
    # Images compressed as they come in, and the longest side they keep (image_compression's
    # IMAGE_LONGEST_SIDES; folder-import-and-file-previews.md, Images compressed).
    compressesImages: bool
    imageLongestSide: int
    dropContext: ImportDropContext


@with_config(ConfigDict(strict=True))
class ScanImportFolderRequest(TypedDict):
    folderPath: Annotated[str, Field(min_length=1, max_length=_MAX_FOLDER_PATH_LENGTH)]


@with_config(ConfigDict(strict=True))
class ListedFile(TypedDict):
    # Its path in the dropped folder ('notes/plan.md') and its size.
    path: Annotated[str, Field(min_length=1, max_length=_MAX_FOLDER_PATH_LENGTH)]
    size: Annotated[int, Field(ge=0)]


@with_config(ConfigDict(strict=True))
class ScanImportListingRequest(TypedDict):
    # A dropped folder's files as the browser listed them.
    files: List[ListedFile]


@with_config(ConfigDict(strict=True))
class BookmarksPreviewRequest(TypedDict):
    # The bookmarks export's text, as the browser read the chosen or dropped file
    # (docs/ready-to-build/bookmark-import.md §4: uploaded, so it works on every deployment).
    fileText: Annotated[str, Field(min_length=1, max_length=MAX_IN_MEMORY_FILE_BYTES)]
    prefixFolder: Annotated[str, Field(max_length=_MAX_FOLDER_PATH_LENGTH)]


@with_config(ConfigDict(strict=True))
class BookmarksImportRequest(TypedDict):
    fileText: Annotated[str, Field(min_length=1, max_length=MAX_IN_MEMORY_FILE_BYTES)]
    prefixFolder: Annotated[str, Field(max_length=_MAX_FOLDER_PATH_LENGTH)]
    addToExisting: bool
    dropContext: ImportDropContext


@with_config(ConfigDict(strict=True))
class ImportPrefixFolderRequest(TypedDict):
    name: Annotated[str, Field(max_length=_MAX_FOLDER_PATH_LENGTH)]


@router.post("/pick-folder")
@transactional_route
def pick_import_folder(request: Request, body: PickImportFolderRequest) -> dict[str, object]:
    """The folder picked and how many files the source reads in it (Markdown files for a
    vault or a Markdown folder; every file for a folder of files)."""
    require_request_auth_token(request)
    folder_path = pick_folder(prompt=IMPORT_SOURCES[body["source"]].folder_prompt)
    if folder_path is None:
        return {"selected": False, "folderPath": "", "fileCount": 0, "imageCount": 0}
    folder = Path(folder_path)
    if body["source"] == FILES.key:
        found = folder_files(DiskFolder(folder))
        image_count = sum(1 for folder_file in found if folder_file.path.suffix.casefold() in COMPRESSIBLE_SUFFIXES)
        return {"selected": True, "folderPath": folder_path, "fileCount": len(found), "imageCount": image_count}
    return {
        "selected": True, "folderPath": folder_path, "fileCount": count_markdown_files(DiskFolder(folder)),
        # Images compression shrinks: the wizard asks about them only when there are some.
        "imageCount": count_compressible_images(DiskFolder(folder)),
    }


@router.post("/scan")
@transactional_route
def scan_import_folder(request: Request, body: ScanImportFolderRequest) -> dict[str, object]:
    """A folder of files grouped by type for the checklist, before anything is copied
    (folder-import-and-file-previews.md §3): each group's files and size, the largest first,
    which start unticked, and the space left where MetaList keeps its files."""
    require_request_auth_token(request)
    folder = Path(body["folderPath"])
    if not folder.is_absolute() or not folder.is_dir():
        raise InputRejected(f"There is no folder at {folder}. Choose the folder again.")
    return _checklist(folder_files(import_uploads.open_import_folder(folder)))


@router.post("/scan-listing")
@transactional_route
def scan_import_listing(request: Request, body: ScanImportListingRequest) -> dict[str, object]:
    """The checklist for a folder dropped on the page, from the browser's list of its files,
    before any of them is sent (docs/ready-to-build/desktop-drops-into-folders.md §4)."""
    require_request_auth_token(request)
    return _checklist(import_uploads.listed_files([[listed["path"], listed["size"]] for listed in body["files"]]))


@router.post("/uploads")
@transactional_route
def start_import_upload(request: Request) -> dict[str, object]:
    """A holding folder for a dropped folder's ticked files; the walkthrough reads it as a
    folder chosen on this computer."""
    require_request_auth_token(request)
    upload_id, folder_path = import_uploads.start_upload()
    return {"uploadId": upload_id, "folderPath": folder_path}


@router.post("/uploads/{upload_id}/file")
@transactional_route
async def upload_import_file(request: Request, upload_id: str) -> dict[str, object]:
    """One ticked file of a dropped folder, at its path in the folder, written as it arrives.
    The form's `path` comes before its file."""
    require_request_auth_token(request)
    declared_bytes = declared_body_bytes(request)
    if declared_bytes is not None:
        require_room_for_files([declared_bytes])

    def open_at_its_path(_part: FilePart, fields: Mapping[str, str]) -> import_uploads.IncomingFile:
        if "path" not in fields or not 0 < len(fields["path"]) <= _MAX_FOLDER_PATH_LENGTH:
            raise InputRejected("That file came without its path in the folder.")
        return incoming.open(fields["path"])

    with full_disk_is_rejected(), import_uploads.receive_file(upload_id) as incoming:
        _file_part, fields = await receive_upload(request, open_sink=open_at_its_path)
    return {"stored": fields["path"]}


@router.post("/uploads/{upload_id}/discard")
@transactional_route
def discard_import_upload(request: Request, upload_id: str) -> dict[str, object]:
    """The holding folder goes: the walkthrough was cancelled, or its import is done."""
    require_request_auth_token(request)
    import_uploads.discard_upload(upload_id)
    return {"discarded": upload_id}


def _checklist(found: List[FolderFile]) -> dict[str, object]:
    groups = file_groups(found)
    return {
        "groups": [
            {
                "key": group.kind.key, "label": group.kind.label, "isSkippedByDefault": group.kind.is_skipped_by_default,
                "fileCount": group.file_count, "bytes": group.total_bytes,
                # Its files, the largest first: [path in the folder, size].
                "files": [[str(folder_file.path), folder_file.size] for folder_file in group.files],
            }
            for group in groups
        ],
        "freeBytes": shutil.disk_usage(resolve_data_directory(environ=os.environ)).free,
    }


@router.post("/preview")
@transactional_route
def preview_import(request: Request, body: ImportFolderRequest) -> dict[str, object]:
    """What importing the folder would do, before anything is written (the wizard's summary)."""
    require_request_auth_token(request)
    if body["source"] == FILES.key:
        return CmdPreviewFolderOfFiles(
            folder_path=body["folderPath"], selection=_file_selection(body), split_mode=body["splitMode"],
            content_format=body["contentFormat"], folder_prefix=body["prefixFolder"], imported_at=datetime.now(timezone.utc),
        ).execute()
    _require_no_excluded_groups(body)
    return CmdPreviewImport(
        source=body["source"], folder_path=body["folderPath"], split_mode=body["splitMode"],
        content_format=body["contentFormat"], folder_prefix=body["prefixFolder"], imported_at=datetime.now(timezone.utc),
    ).execute()


@router.post("/images")
@transactional_route
def estimate_import_images(request: Request, body: ImportFolderRequest) -> dict[str, object]:
    """The images the import would compress: how many, their size, and about their size
    compressed (the wizard's Images screen). Writes nothing."""
    require_request_auth_token(request)
    if body["source"] != FILES.key:
        _require_no_excluded_groups(body)
    return CmdEstimateImportImages(
        source=body["source"], folder_path=body["folderPath"], selection=_file_selection(body), split_mode=body["splitMode"],
        content_format=body["contentFormat"], folder_prefix=body["prefixFolder"], imported_at=datetime.now(timezone.utc),
    ).execute()


def _file_selection(body: ImportFolderRequest) -> FileSelection:
    return FileSelection(
        excluded_groups=tuple(body["excludedGroups"]), excluded_files=tuple(body["excludedFiles"]),
        included_files=tuple(body["includedFiles"]), keeps_markdown_as_files=body["keepsMarkdownAsFiles"],
    )


def _image_choice(body: ImportFolderRequest) -> ImageChoice:
    if body["imageLongestSide"] not in IMAGE_LONGEST_SIDES:
        raise InputRejected("Choose one of the image sizes offered.")
    return ImageChoice(compresses=body["compressesImages"], longest_side_px=body["imageLongestSide"])


def _require_no_excluded_groups(body: ImportFolderRequest) -> None:
    # Only a folder of files has the checklist.
    if any((body["excludedGroups"], body["excludedFiles"], body["includedFiles"], body["keepsMarkdownAsFiles"])):
        raise InputRejected("Only a folder of files leaves kinds of file out or keeps Markdown files as files.")


@router.post("/prefix-folder")
@transactional_route
def check_import_prefix_folder(request: Request, body: ImportPrefixFolderRequest) -> dict[str, object]:
    """The folder a typed name makes (cleaned as folder names are; '' for none), whether it
    exists already, and what is wrong with the name ('' when nothing): the import's folder
    step shows them as the name is typed, so a name it can't use is said there, not as an
    error after each keystroke."""
    require_request_auth_token(request)
    try:
        folder = import_folder_prefix(body["name"])
    except InputRejected as rejected:
        return {"folder": "", "exists": False, "problem": str(rejected)}
    return {"folder": folder, "exists": import_folder_exists(folder), "problem": ""}


def _context_tags(context: ImportDropContext, prefix_folder: str) -> str:
    """The tags a drop's import gives its top notes (drop_context_tags); none from the menu."""
    if not context["isDrop"]:
        return ""
    return drop_context_tags(
        search=context["search"], folder_filter=tab_state_store.get_folder_filter(tab_id=context["tabId"]),
        folder_prefix=prefix_folder,
    )


@router.post("/folder")
@transactional_route
def import_folder(request: Request, body: ImportFolderRequest) -> dict[str, object]:
    token = require_request_auth_token(request)
    if body["source"] == FILES.key:
        result = CmdImportFolderOfFiles(
            folder_path=body["folderPath"], selection=_file_selection(body), split_mode=body["splitMode"],
            content_format=body["contentFormat"], folder_prefix=body["prefixFolder"], add_to_existing=body["addToExisting"],
            images=_image_choice(body), token=token, imported_at=datetime.now(timezone.utc),
            context_tags=_context_tags(body["dropContext"], body["prefixFolder"]),
        ).execute()
    else:
        _require_no_excluded_groups(body)
        result = CmdImportObsidianVault(
            source=body["source"], folder_path=body["folderPath"], split_mode=body["splitMode"],
            content_format=body["contentFormat"], folder_prefix=body["prefixFolder"], add_to_existing=body["addToExisting"],
            images=_image_choice(body), token=token, imported_at=datetime.now(timezone.utc),
            context_tags=_context_tags(body["dropContext"], body["prefixFolder"]),
        ).execute()
    # The imported notes join the `[[` catalog now, not at the first `[[`.
    build_catalog_in_background()
    return result


@router.post("/bookmarks/preview")
@transactional_route
def preview_bookmark_import(request: Request, body: BookmarksPreviewRequest) -> dict[str, object]:
    """What importing a bookmarks export would do (the File and Summary screens); writes nothing.
    A file that isn't one is refused with a sentence saying so."""
    require_request_auth_token(request)
    return CmdPreviewBookmarkImport(
        file_text=body["fileText"], folder_prefix=body["prefixFolder"], imported_at=datetime.now(timezone.utc),
    ).execute()


@router.post("/bookmarks")
@transactional_route
def import_bookmarks(request: Request, body: BookmarksImportRequest) -> dict[str, object]:
    token = require_request_auth_token(request)
    result = CmdImportBookmarks(
        file_text=body["fileText"], folder_prefix=body["prefixFolder"], add_to_existing=body["addToExisting"],
        token=token, imported_at=datetime.now(timezone.utc),
        context_tags=_context_tags(body["dropContext"], body["prefixFolder"]),
    ).execute()
    build_catalog_in_background()
    return result
