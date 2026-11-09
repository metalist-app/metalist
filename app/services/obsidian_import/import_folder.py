"""The folder an import reads, wherever its files are: on this computer, or held encrypted after
being dropped on the page (import_uploads.py). The import reads through this and never touches
the disk itself, so a dropped folder's files are decrypted only as far as memory."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath
from typing import Protocol

from app.upload_limits import UPLOAD_CHUNK_BYTES

ROOT = PurePosixPath(".")


class ImportFolder(Protocol):
    @property
    def name(self) -> str: ...

    def walk(self) -> Iterator[tuple[PurePosixPath, list[str], list[str]]]:
        """As os.walk, top down, paths relative to the folder: names removed from the folders
        list in place are not gone into."""

    def is_plain_file(self, relative: PurePosixPath) -> bool: ...

    def read_bytes(self, relative: PurePosixPath) -> bytes: ...

    def pieces(self, relative: PurePosixPath) -> Iterator[bytes]:
        """The file a piece at a time, whatever its size."""

    def size(self, relative: PurePosixPath) -> int: ...

    def file_times(self, relative: PurePosixPath) -> tuple[datetime, datetime]:
        """When the file was made and last changed."""


class DiskFolder:
    """A folder chosen on this computer. Only read."""

    def __init__(self, path: Path) -> None:
        if not path.is_dir():
            raise ValueError(f"import folder must be a folder: {path}")
        self._path = path

    @property
    def name(self) -> str:
        return self._path.name

    def _at(self, relative: PurePosixPath) -> Path:
        return self._path / Path(relative)

    def walk(self) -> Iterator[tuple[PurePosixPath, list[str], list[str]]]:
        for directory, folder_names, file_names in os.walk(self._path):
            yield PurePosixPath(Path(directory).relative_to(self._path).as_posix()), folder_names, file_names

    def is_plain_file(self, relative: PurePosixPath) -> bool:
        path = self._at(relative)
        return path.is_file() and not path.is_symlink()

    def read_bytes(self, relative: PurePosixPath) -> bytes:
        return self._at(relative).read_bytes()

    def pieces(self, relative: PurePosixPath) -> Iterator[bytes]:
        with self._at(relative).open("rb") as source:
            yield from iter(lambda: source.read(UPLOAD_CHUNK_BYTES), b"")

    def size(self, relative: PurePosixPath) -> int:
        return self._at(relative).stat().st_size

    def file_times(self, relative: PurePosixPath) -> tuple[datetime, datetime]:
        stat = self._at(relative).stat()
        return _file_created_at(stat), datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)


def _file_created_at(stat: os.stat_result) -> datetime:
    # macOS and Windows know when a file was made; elsewhere its last change stands in.
    if hasattr(stat, "st_birthtime"):
        # Read by name: typeshed declares st_birthtime only off Linux, and mypy checks the
        # code as Linux ([tool.mypy] in pyproject.toml), where this branch never runs.
        birthtime = getattr(stat, "st_birthtime")
        assert isinstance(birthtime, float), "st_birthtime is a timestamp in seconds"
        return datetime.fromtimestamp(birthtime, tz=timezone.utc)
    return datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
