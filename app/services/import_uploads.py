"""A folder dropped on the page (docs/ready-to-build/desktop-drops-into-folders.md §4): a
browser gives a page a dropped folder's files, never its path, so the import can't read it
where it is. The browser lists its files first (names, paths in the folder, sizes): the
checklist is made from that list before anything is sent. Then the ticked files are uploaded
one by one into a holding folder of their own, in the data directory and outside the vault,
which the import walkthrough then reads like a folder chosen on this computer. Nothing is in
the vault until Import; cancelling, or importing, discards the holding folder, and a restart
discards any left over (an interrupted upload starts over: the maintainer, 2026-11-02).

The holding folder keeps the files as sent, unencrypted, until it is discarded."""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import BinaryIO, List, Tuple
from uuid import uuid4

from app.data_directory import resolve_data_directory
from app.services.input_errors import InputRejected
from app.services.obsidian_import.file_groups import FolderFile, group_of

HOLDING_FOLDER_NAME = "import-uploads"
_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# A path segment that would leave the folder, or say nothing.
_NOT_A_NAME = {"", ".", ".."}
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _holding_root() -> Path:
    return resolve_data_directory(environ=os.environ) / HOLDING_FOLDER_NAME


def relative_path(path: object) -> PurePosixPath:
    """A file's path inside the dropped folder, as the browser gave it ('notes/plan.md'),
    refused if it could point anywhere else."""
    if not isinstance(path, str) or path == "" or path.startswith("/") or "\\" in path or _DRIVE_RE.match(path):
        raise InputRejected(f"{path!r} is not a path inside the folder.")
    parts = path.split("/")
    if any(part in _NOT_A_NAME for part in parts):
        raise InputRejected(f"{path!r} is not a path inside the folder.")
    return PurePosixPath(unicodedata.normalize("NFC", path))


def listed_files(listing: List[List[object]]) -> List[FolderFile]:
    """The browser's list of a dropped folder's files ([path, size] each) as the checklist
    takes them, in path order (case ignored), as folder_files gives a folder on disk."""
    found: List[FolderFile] = []
    for path, size in listing:
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise InputRejected(f"{path!r} has no size.")
        relative = relative_path(path)
        found.append(FolderFile(path=relative, size=size, group=group_of(relative)))
    found.sort(key=lambda folder_file: str(folder_file.path).casefold())
    return found


def start_upload() -> Tuple[str, str]:
    """A new holding folder: its id, and its path for the import to read."""
    upload_id = str(uuid4())
    folder = _holding_root() / upload_id
    folder.mkdir(parents=True, exist_ok=False)
    return upload_id, str(folder)


def _upload_folder(upload_id: str) -> Path:
    if not isinstance(upload_id, str) or _UPLOAD_ID_RE.match(upload_id) is None:
        raise InputRejected("That upload is not one.")
    folder = _holding_root() / upload_id
    if not folder.is_dir():
        raise InputRejected("That upload is gone. Drop the folder again.")
    return folder


class IncomingFile:
    """One file of a dropped folder arriving a piece at a time, at its path in the holding folder."""

    def __init__(self, upload_id: str) -> None:
        self._folder = _upload_folder(upload_id)
        self._handle: BinaryIO | None = None
        self.target: Path | None = None

    def open(self, path: str) -> "IncomingFile":
        """Start the file at path; never over another, and one sent twice at once fails loudly."""
        target = self._folder.joinpath(*relative_path(path).parts)
        assert self._folder in target.parents, target
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise InputRejected(f"{path} was sent already.")
        self._handle = open(target, "xb")
        self.target = target
        return self

    def write(self, content: bytes) -> None:
        assert self._handle is not None
        self._handle.write(content)

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None


@contextmanager
def receive_file(upload_id: str) -> Iterator[IncomingFile]:
    """A file on its way into the holding folder. One that doesn't arrive whole leaves nothing."""
    incoming = IncomingFile(upload_id)
    is_whole = False
    try:
        yield incoming
        incoming.close()
        is_whole = True
    finally:
        if not is_whole:
            # Closing can fail on a full disk; the partial file goes anyway.
            try:
                incoming.close()
            finally:
                if incoming.target is not None:
                    incoming.target.unlink()


def discard_upload(upload_id: str) -> None:
    shutil.rmtree(_upload_folder(upload_id))


def discard_every_upload() -> None:
    """At startup: holding folders an earlier run left (an interrupted upload starts over)."""
    root = _holding_root()
    if root.is_dir():
        shutil.rmtree(root)
