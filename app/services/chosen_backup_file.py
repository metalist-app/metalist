"""The backup file chosen with Restore From Backup's Choose File… (the operating system's own
file dialog, opened on this computer): remembered here, so a restore names it by its file name
and the browser never sends a path for the server to read.

One file at a time: choosing another forgets the one before. The file is only ever read.
"""

from __future__ import annotations

import threading
from pathlib import Path


class ChosenBackupFile:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: Path | None = None

    def remember(self, path: Path) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError(f"a chosen backup file is an absolute path, got {path!r}")
        with self._lock:
            self._path = path

    def path_named(self, filename: str) -> Path | None:
        """The chosen file when it has this name, else None (none chosen, or another since)."""
        if not isinstance(filename, str) or filename == "":
            raise ValueError("filename must be a non-empty string")
        with self._lock:
            chosen = self._path
        if chosen is None or chosen.name != filename:
            return None
        return chosen


chosen_backup_file = ChosenBackupFile()
