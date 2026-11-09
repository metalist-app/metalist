"""Dedicated sqlite session helpers for the catalog of a vault's stored files."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from functools import cache
from pathlib import Path
import tempfile
from threading import RLock
import os
import traceback
from typing import Iterator, Optional

from loguru import logger

from app.db.blob_store import BlobStore, blob_store_for_database, resolve_file_catalog_path
from app.db.file_schema import initialize_file_schema
from app.models.database import SafeSession

_FILE_MEMORY_URI = "file:metalist_files_memory?mode=memory&cache=shared"
_ROLLBACK_STACK_FRAME_LIMIT = 50


@cache
def _memory_blobs_directory() -> tempfile.TemporaryDirectory:
    """Where an in-memory notes database (the test harness) keeps its blobs, for the process's life."""
    return tempfile.TemporaryDirectory(prefix="metalist-memory-blobs-")


def live_blob_store() -> BlobStore:
    if SafeSession._use_memory:  # type: ignore[attr-defined]
        return BlobStore(Path(_memory_blobs_directory().name))
    return blob_store_for_database(SafeSession._db_path)  # type: ignore[attr-defined]


class FileSession:
    _lock = RLock()
    _memory_anchor: Optional[sqlite3.Connection] = None
    _use_memory = False

    def __init__(self) -> None:
        self._connection = self._create_connection()
        self._closed = False

    @classmethod
    def _sync_mode_with_notes_db(cls) -> None:
        use_memory = bool(SafeSession._use_memory)  # type: ignore[attr-defined]
        with cls._lock:
            if use_memory:
                cls._use_memory = True
                if cls._memory_anchor is None:
                    anchor = sqlite3.connect(
                        _FILE_MEMORY_URI,
                        uri=True,
                        check_same_thread=False,
                        isolation_level="DEFERRED",
                    )
                    anchor.row_factory = sqlite3.Row
                    anchor.execute("PRAGMA journal_mode=WAL")
                    anchor.execute("PRAGMA secure_delete=ON")
                    anchor.execute("PRAGMA synchronous=NORMAL")
                    initialize_file_schema(anchor)
                    anchor.commit()
                    cls._memory_anchor = anchor
                return

            cls._use_memory = False
            if cls._memory_anchor is not None:
                cls._memory_anchor.close()
                cls._memory_anchor = None

    @classmethod
    def _create_connection(cls) -> sqlite3.Connection:
        cls._sync_mode_with_notes_db()

        if cls._use_memory:
            connection = sqlite3.connect(
                _FILE_MEMORY_URI,
                uri=True,
                check_same_thread=False,
                isolation_level="DEFERRED",
            )
        else:
            database_path = resolve_file_catalog_path(SafeSession._db_path)  # type: ignore[attr-defined]
            database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(
                str(database_path),
                check_same_thread=False,
                isolation_level="DEFERRED",
            )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA secure_delete=ON")
        # A deleted blob must never come back into the catalog after a power cut.
        connection.execute("PRAGMA synchronous=FULL")
        initialize_file_schema(connection)
        connection.commit()
        return connection

    def connection(self) -> sqlite3.Connection:
        return self._connection

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()
        stack = "".join(traceback.format_stack(limit=_ROLLBACK_STACK_FRAME_LIMIT))
        exc_type, _, _ = sys.exc_info()
        if exc_type is None:
            logger.error(
                "FATAL: file DB rollback executed; crashing process",
                extra={"stack": stack},
            )
        else:
            logger.error(
                "FATAL: file DB rollback executed; crashing process",
                extra={"stack": stack, "error_type": exc_type.__name__},
            )
        sys.stderr.write("FATAL: file DB rollback executed; crashing process\n")
        sys.stderr.flush()
        os._exit(1)

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True


@contextmanager
def begin_file_writer() -> Iterator[sqlite3.Connection]:
    session = FileSession()
    succeeded = False
    try:
        yield session.connection()
        session.commit()
        succeeded = True
    finally:
        try:
            if not succeeded:
                session.connection().rollback()
        finally:
            session.close()


@contextmanager
def connect_file_reader() -> Iterator[sqlite3.Connection]:
    session = FileSession()
    try:
        yield session.connection()
    finally:
        session.close()
