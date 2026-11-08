"""Whether the browser's folder tree is open, and so which folder a search context's view applies
(docs/ready-to-build/virtual-folders.md, the folder tree switch; decided 2026-11-07: per browser).

Each browser sends its tree's switch with every request (X-Metalist-Folders-Shown,
session-auth.js); the auth middleware records it for the request. A search context's folder is
kept in tab state either way; it narrows what the context shows only while that browser's tree
is open, so closing the tree shows each context's search alone and reopening it brings each
folder back.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from http import HTTPStatus

from fastapi import HTTPException

from app.services.tab_state import tab_state_store
from app.services.virtual_folders import NO_FOLDER

FOLDERS_SHOWN_HEADER = "x-metalist-folders-shown"
_SHOWN = "true"
_HIDDEN = "false"
# The request did not say: a sign-in request, which never applies a folder.
_NOT_SENT = ""
_folders_shown: ContextVar[str] = ContextVar("folders_shown")


def record_folders_shown(headers: Mapping[str, str]) -> None:
    """Remember for this request whether its browser's folder tree is open."""
    value = _NOT_SENT
    if FOLDERS_SHOWN_HEADER in headers:
        value = headers[FOLDERS_SHOWN_HEADER]
    _folders_shown.set(value)


def applied_folder(tab_id: str) -> str:
    """The folder the tab's view applies: its folder while the tree is open, NO_FOLDER while it
    is closed or the tab has none."""
    folder = tab_state_store.get_folder_filter(tab_id=tab_id)
    if folder == NO_FOLDER:
        return NO_FOLDER
    shown = _folders_shown.get()
    if shown not in (_SHOWN, _HIDDEN):
        raise HTTPException(status_code=HTTPStatus.BAD_REQUEST,
                            detail="X-Metalist-Folders-Shown header required: true or false")
    if shown == _HIDDEN:
        return NO_FOLDER
    return folder
