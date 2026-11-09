"""A folder dropped on the page (docs/ready-to-build/desktop-drops-into-folders.md §4): a
browser gives a page a dropped folder's files, never its path, so the import can't read it
where it is. The browser lists its files first (names, paths in the folder, sizes): the
checklist is made from that list before anything is sent. Then the ticked files are uploaded
one by one into a holding folder of their own, in the data directory and outside the vault,
which the import walkthrough then reads like a folder chosen on this computer. Nothing is in
the vault until Import; cancelling, or importing, discards the holding folder, and a restart
discards any left over (an interrupted upload starts over: the maintainer, 2026-11-02).

The holding folder keeps each file encrypted and under a random name, with a key and a name that
exist only in this process's memory (docs/design/file-storage.md, section 14): no
file's content or name is readable on disk, and a restart or a lock ends the upload."""

from __future__ import annotations

import os
import re
import shutil
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from threading import Lock
from typing import List, Tuple
from uuid import uuid4

from app.data_directory import resolve_data_directory
from app.db.blob_store import BlobStore, BlobWriter, StoredBlob
from app.services.input_errors import InputRejected
from app.services.obsidian_import.file_groups import FolderFile, group_of
from app.services.obsidian_import.import_folder import ROOT, DiskFolder, ImportFolder

HOLDING_FOLDER_NAME = "import-uploads"
_UPLOAD_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# A path segment that would leave the folder, or say nothing.
_NOT_A_NAME = {"", ".", ".."}
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _holding_root() -> Path:
    return resolve_data_directory(environ=os.environ) / HOLDING_FOLDER_NAME


@dataclass(frozen=True, slots=True)
class _HeldFile:
    stored: StoredBlob
    received_at: datetime


class _HeldUploads:
    """Each upload's files by their path in the dropped folder, with their keys: memory only."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._files_by_upload: dict[str, dict[PurePosixPath, _HeldFile]] = {}

    def begin(self, upload_id: str) -> None:
        with self._lock:
            self._files_by_upload[upload_id] = {}

    def is_held(self, upload_id: str) -> bool:
        with self._lock:
            return upload_id in self._files_by_upload

    def has_file(self, upload_id: str, path: PurePosixPath) -> bool:
        with self._lock:
            return path in self._files_by_upload[upload_id]

    def add(self, upload_id: str, path: PurePosixPath, held: _HeldFile) -> bool:
        """Whether it was added: False when the path is taken already."""
        with self._lock:
            files = self._files_by_upload[upload_id]
            if path in files:
                return False
            files[path] = held
            return True

    def files(self, upload_id: str) -> dict[PurePosixPath, _HeldFile]:
        with self._lock:
            return dict(self._files_by_upload[upload_id])

    def forget(self, upload_id: str) -> None:
        with self._lock:
            del self._files_by_upload[upload_id]

    def forget_all(self) -> None:
        with self._lock:
            self._files_by_upload.clear()


_held = _HeldUploads()


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
    _held.begin(upload_id)
    return upload_id, str(folder)


def _upload_folder(upload_id: str) -> Path:
    if not isinstance(upload_id, str) or _UPLOAD_ID_RE.match(upload_id) is None:
        raise InputRejected("That upload is not one.")
    folder = _holding_root() / upload_id
    if not folder.is_dir() or not _held.is_held(upload_id):
        raise InputRejected("That upload is gone. Drop the folder again.")
    return folder


class IncomingFile:
    """One file of a dropped folder arriving a piece at a time, encrypted as it comes."""

    def __init__(self, *, upload_id: str, writer: BlobWriter) -> None:
        self._upload_id = upload_id
        self._writer = writer
        self.path: PurePosixPath | None = None

    def open(self, path: str) -> "IncomingFile":
        """Say where it goes in the folder; never over another."""
        relative = relative_path(path)
        if _held.has_file(self._upload_id, relative):
            raise InputRejected(f"{path} was sent already.")
        self.path = relative
        return self

    def write(self, content: bytes) -> None:
        self._writer.write(content)

    def finish(self) -> None:
        assert self.path is not None, "a file is opened at its path before it is finished"
        stored = self._writer.finish()
        if not _held.add(self._upload_id, self.path, _HeldFile(stored=stored, received_at=datetime.now(timezone.utc))):
            raise InputRejected(f"{self.path} was sent already.")


@contextmanager
def receive_file(upload_id: str) -> Iterator[IncomingFile]:
    """A file on its way into the holding folder. One that doesn't arrive whole leaves nothing."""
    store = BlobStore(_upload_folder(upload_id))
    with store.writer(is_encrypted=True) as writer:
        incoming = IncomingFile(upload_id=upload_id, writer=writer)
        yield incoming
        incoming.finish()


class HeldFolder:
    """A dropped folder as the import reads it: decrypted only as far as memory."""

    def __init__(self, upload_id: str) -> None:
        self._upload_id = upload_id
        self._store = BlobStore(_upload_folder(upload_id))
        self._files = _held.files(upload_id)

    @property
    def name(self) -> str:
        return self._upload_id

    def walk(self) -> Iterator[tuple[PurePosixPath, list[str], list[str]]]:
        folders: dict[PurePosixPath, set[str]] = {ROOT: set()}
        files_in: dict[PurePosixPath, list[str]] = {ROOT: []}
        for path in self._files:
            for parent in reversed(path.parents):
                if parent not in folders:
                    folders[parent] = set()
                    files_in[parent] = []
                if parent != ROOT:
                    folders[parent.parent].add(parent.name)
            files_in[path.parent].append(path.name)
        waiting = [ROOT]
        while waiting:
            here = waiting.pop()
            folder_names = sorted(folders[here])
            yield here, folder_names, sorted(files_in[here])
            waiting.extend(here / name for name in reversed(folder_names))

    def is_plain_file(self, relative: PurePosixPath) -> bool:
        return relative in self._files

    def read_bytes(self, relative: PurePosixPath) -> bytes:
        stored = self._files[relative].stored
        return self._store.read_all(stored.blob_id, stored.seal)

    def pieces(self, relative: PurePosixPath) -> Iterator[bytes]:
        stored = self._files[relative].stored
        return self._store.read_range(stored.blob_id, stored.seal, start=0, length=stored.seal.real_size)

    def size(self, relative: PurePosixPath) -> int:
        return self._files[relative].stored.seal.real_size

    def file_times(self, relative: PurePosixPath) -> tuple[datetime, datetime]:
        received_at = self._files[relative].received_at
        return received_at, received_at


def open_import_folder(folder: Path) -> ImportFolder:
    """What an import reads at folder: a dropped folder's held files, or the folder on disk."""
    if folder.parent == _holding_root():
        return HeldFolder(folder.name)
    return DiskFolder(folder)


def discard_upload(upload_id: str) -> None:
    folder = _upload_folder(upload_id)
    _held.forget(upload_id)
    shutil.rmtree(folder)


def discard_every_upload() -> None:
    """At startup and when the vault locks: nothing an upload held outlives its keys."""
    _held.forget_all()
    root = _holding_root()
    if root.is_dir():
        shutil.rmtree(root)
