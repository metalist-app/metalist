"""Importing from other apps: the developer version (PLAN.md) of the Obsidian import and of
the plain Markdown folder import (slice 1c), in every environment (the maintainer,
2026-10-31), and a folder of any files (docs/ready-to-build/folder-import-and-file-previews.md)."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Annotated, List, Literal, TypedDict

from fastapi import APIRouter, Request
from pydantic import ConfigDict, Field, with_config

from app.api.request_auth import require_request_auth_token
from app.api.transactions import transactional_route
from app.data_directory import resolve_data_directory
from app.services.input_errors import InputRejected
from app.services.native_folder_picker import pick_folder
from app.services.obsidian_import.file_groups import file_groups, folder_files, is_over_limit
from app.services.obsidian_import.notes import import_folder_prefix
from app.services.obsidian_import.sources import FILES, IMPORT_SOURCES
from app.services.file_text_preview import IMPORT_PREVIEW_KINDS, NO_PREVIEW, preview_kind_of
from app.services.image_compression import COMPRESSIBLE_SUFFIXES, IMAGE_LONGEST_SIDES, ImageChoice
from app.services.obsidian_import.vault import count_compressible_images, count_markdown_files
from app.services.reference_suggestions import build_catalog_in_background
from app.upload_limits import MAX_ATTACHMENT_BYTES
from app.usecases.import_bookmarks import CmdImportBookmarks, CmdPreviewBookmarkImport
from app.usecases.import_obsidian_vault import (
    CmdEstimateImportImages,
    CmdEstimateImportPreviews,
    CmdImportFolderOfFiles,
    CmdImportObsidianVault,
    CmdPreviewFolderOfFiles,
    CmdPreviewImport,
    FileSelection,
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
    # A folder of files: the kinds of file that get a preview (file_text_preview's
    # IMPORT_PREVIEW_KINDS). Empty for the other sources.
    previewKinds: List[Literal["code", "html", "data"]]
    # Images compressed as they come in, and the longest side they keep (image_compression's
    # IMAGE_LONGEST_SIDES; folder-import-and-file-previews.md, Images compressed).
    compressesImages: bool
    imageLongestSide: int


@with_config(ConfigDict(strict=True))
class ScanImportFolderRequest(TypedDict):
    folderPath: Annotated[str, Field(min_length=1, max_length=_MAX_FOLDER_PATH_LENGTH)]


@with_config(ConfigDict(strict=True))
class BookmarksPreviewRequest(TypedDict):
    # The bookmarks export's text, as the browser read the chosen or dropped file
    # (docs/ready-to-build/bookmark-import.md §4: uploaded, so it works on every deployment).
    fileText: Annotated[str, Field(min_length=1, max_length=MAX_ATTACHMENT_BYTES)]
    prefixFolder: Annotated[str, Field(max_length=_MAX_FOLDER_PATH_LENGTH)]


@with_config(ConfigDict(strict=True))
class BookmarksImportRequest(TypedDict):
    fileText: Annotated[str, Field(min_length=1, max_length=MAX_ATTACHMENT_BYTES)]
    prefixFolder: Annotated[str, Field(max_length=_MAX_FOLDER_PATH_LENGTH)]
    addToExisting: bool


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
        found = folder_files(folder)
        image_count = sum(1 for folder_file in found if folder_file.path.suffix.casefold() in COMPRESSIBLE_SUFFIXES)
        return {"selected": True, "folderPath": folder_path, "fileCount": len(found), "imageCount": image_count}
    return {
        "selected": True, "folderPath": folder_path, "fileCount": count_markdown_files(folder),
        # Images compression shrinks: the wizard asks about them only when there are some.
        "imageCount": count_compressible_images(folder),
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
    groups = file_groups(folder_files(folder))
    return {
        "groups": [
            {
                "key": group.kind.key, "label": group.kind.label, "isSkippedByDefault": group.kind.is_skipped_by_default,
                "fileCount": group.file_count, "bytes": group.total_bytes, "importableBytes": group.importable_bytes,
                "overLimitCount": group.over_limit_count,
                # Its files, the largest first: [path in the folder, size, over the limit, the kind of
                # preview it can get ('' for none; the Previews screen shows for those ticked)].
                "files": [
                    [str(folder_file.path), folder_file.size, is_over_limit(folder_file), _import_preview_kind(folder_file.path)]
                    for folder_file in group.files
                ],
            }
            for group in groups
        ],
        "freeBytes": shutil.disk_usage(resolve_data_directory(environ=os.environ)).free,
        "maxFileBytes": MAX_ATTACHMENT_BYTES,
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


@router.post("/previews")
@transactional_route
def estimate_import_previews(request: Request, body: ImportFolderRequest) -> dict[str, object]:
    """A folder of files' files that could get a preview, by kind: how many, and about how much
    note data their previews add (the wizard's Previews screen). Writes nothing."""
    require_request_auth_token(request)
    if body["source"] != FILES.key:
        raise InputRejected("Only a folder of files makes previews.")
    return CmdEstimateImportPreviews(
        folder_path=body["folderPath"], selection=_file_selection(body), split_mode=body["splitMode"],
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


def _import_preview_kind(path: PurePosixPath) -> str:
    kind = preview_kind_of(path.name)
    if kind not in IMPORT_PREVIEW_KINDS:
        return NO_PREVIEW
    return kind


def _file_selection(body: ImportFolderRequest) -> FileSelection:
    return FileSelection(
        excluded_groups=tuple(body["excludedGroups"]), excluded_files=tuple(body["excludedFiles"]),
        included_files=tuple(body["includedFiles"]), keeps_markdown_as_files=body["keepsMarkdownAsFiles"],
        preview_kinds=tuple(body["previewKinds"]),
    )


def _image_choice(body: ImportFolderRequest) -> ImageChoice:
    if body["imageLongestSide"] not in IMAGE_LONGEST_SIDES:
        raise InputRejected("Choose one of the image sizes offered.")
    return ImageChoice(compresses=body["compressesImages"], longest_side_px=body["imageLongestSide"])


def _require_no_excluded_groups(body: ImportFolderRequest) -> None:
    # Only a folder of files has the checklist.
    if any((body["excludedGroups"], body["excludedFiles"], body["includedFiles"], body["keepsMarkdownAsFiles"], body["previewKinds"])):
        raise InputRejected("Only a folder of files leaves kinds of file out, keeps Markdown files as files or makes previews.")


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


@router.post("/folder")
@transactional_route
def import_folder(request: Request, body: ImportFolderRequest) -> dict[str, object]:
    token = require_request_auth_token(request)
    if body["source"] == FILES.key:
        result = CmdImportFolderOfFiles(
            folder_path=body["folderPath"], selection=_file_selection(body), split_mode=body["splitMode"],
            content_format=body["contentFormat"], folder_prefix=body["prefixFolder"], add_to_existing=body["addToExisting"],
            images=_image_choice(body), token=token, imported_at=datetime.now(timezone.utc),
        ).execute()
    else:
        _require_no_excluded_groups(body)
        result = CmdImportObsidianVault(
            source=body["source"], folder_path=body["folderPath"], split_mode=body["splitMode"],
            content_format=body["contentFormat"], folder_prefix=body["prefixFolder"], add_to_existing=body["addToExisting"],
            images=_image_choice(body), token=token, imported_at=datetime.now(timezone.utc),
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
    ).execute()
    build_catalog_in_background()
    return result
