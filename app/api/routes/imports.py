"""Importing from other apps: the Obsidian import's developer version (PLAN.md), which exists
only in development (METALIST_ENVIRONMENT=development); elsewhere its routes answer 404."""

from __future__ import annotations

from datetime import datetime, timezone
from http import HTTPStatus
from typing import Annotated, Literal, TypedDict

from fastapi import APIRouter, HTTPException, Request
from pydantic import ConfigDict, Field, with_config

from app.api.request_auth import require_request_auth_token
from app.api.transactions import transactional_route
from app.services.native_folder_picker import pick_folder
from app.startup_environment import is_development_environment
from app.usecases.import_obsidian_vault import CmdImportObsidianVault

router = APIRouter(prefix="/import", tags=["import"])

# A folder path as the operating system's folder dialog gives it.
_MAX_FOLDER_PATH_LENGTH = 4096
_FOLDER_PROMPT = "Choose an Obsidian vault to import into MetaList"


@with_config(ConfigDict(strict=True))
class ObsidianImportRequest(TypedDict):
    folderPath: Annotated[str, Field(min_length=1, max_length=_MAX_FOLDER_PATH_LENGTH)]
    # obsidian_import.tree's SPLIT_MODES and CONTENT_FORMATS (import-export-launch.md §2.2).
    splitMode: Literal["none", "headings-and-lists", "paragraphs"]
    contentFormat: Literal["rich", "markdown"]


def _require_development() -> None:
    if not is_development_environment():
        raise HTTPException(status_code=HTTPStatus.NOT_FOUND, detail="Not Found")


@router.post("/obsidian/pick-folder")
@transactional_route
def pick_obsidian_vault_folder(request: Request) -> dict[str, object]:
    _require_development()
    require_request_auth_token(request)
    folder_path = pick_folder(prompt=_FOLDER_PROMPT)
    if folder_path is None:
        return {"selected": False, "folderPath": ""}
    return {"selected": True, "folderPath": folder_path}


@router.post("/obsidian")
@transactional_route
def import_obsidian_vault(request: Request, body: ObsidianImportRequest) -> dict[str, object]:
    _require_development()
    token = require_request_auth_token(request)
    return CmdImportObsidianVault(
        folder_path=body["folderPath"], split_mode=body["splitMode"], content_format=body["contentFormat"],
        token=token, imported_at=datetime.now(timezone.utc),
    ).execute()
