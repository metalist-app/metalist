"""Importing from other apps: the developer version (PLAN.md) of the Obsidian import and of
the plain Markdown folder import (slice 1c), in every environment (the maintainer,
2026-10-31)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from fastapi import APIRouter, Request
from pydantic import ConfigDict, Field, with_config

from app.api.request_auth import require_request_auth_token
from app.api.transactions import transactional_route
from app.services.native_folder_picker import pick_folder
from app.services.obsidian_import.sources import IMPORT_SOURCES
from app.services.obsidian_import.vault import count_markdown_files
from app.usecases.import_obsidian_vault import CmdImportObsidianVault, CmdPreviewImport

router = APIRouter(prefix="/import", tags=["import"])

# A folder path as the operating system's folder dialog gives it.
_MAX_FOLDER_PATH_LENGTH = 4096
# obsidian_import.sources' IMPORT_SOURCES.
ImportSourceKey = Literal["obsidian", "markdown"]


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


@router.post("/pick-folder")
@transactional_route
def pick_import_folder(request: Request, body: PickImportFolderRequest) -> dict[str, object]:
    """The folder picked and how many Markdown files it holds."""
    require_request_auth_token(request)
    folder_path = pick_folder(prompt=IMPORT_SOURCES[body["source"]].folder_prompt)
    if folder_path is None:
        return {"selected": False, "folderPath": "", "markdownFileCount": 0}
    return {"selected": True, "folderPath": folder_path, "markdownFileCount": count_markdown_files(Path(folder_path))}


@router.post("/preview")
@transactional_route
def preview_import(request: Request, body: ImportFolderRequest) -> dict[str, object]:
    """What importing the folder would do, before anything is written (the wizard's summary)."""
    require_request_auth_token(request)
    return CmdPreviewImport(
        source=body["source"], folder_path=body["folderPath"], split_mode=body["splitMode"],
        content_format=body["contentFormat"], imported_at=datetime.now(timezone.utc),
    ).execute()


@router.post("/folder")
@transactional_route
def import_folder(request: Request, body: ImportFolderRequest) -> dict[str, object]:
    token = require_request_auth_token(request)
    return CmdImportObsidianVault(
        source=body["source"], folder_path=body["folderPath"], split_mode=body["splitMode"],
        content_format=body["contentFormat"], token=token, imported_at=datetime.now(timezone.utc),
    ).execute()
