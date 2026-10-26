"""Migration 9→10: the files database gains revisions and diagram previews."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.db.file_schema import initialize_file_schema
from app.db.migrations import run_database_migrations
from app.db.schema import initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION
from app.services.encryption import EncryptionService

_LEGACY_FILES_TABLE = """
CREATE TABLE files (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_encryption_nonce BLOB,
    title_encryption_tag BLOB,
    metadata_json TEXT NOT NULL,
    metadata_encryption_nonce BLOB,
    metadata_encryption_tag BLOB,
    blob_data BLOB NOT NULL,
    blob_encryption_nonce BLOB,
    blob_encryption_tag BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


def _version_9_namespace(tmp_path: Path) -> Path:
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        connection.execute("PRAGMA user_version = 9")
        connection.commit()
    return notes


def _migrate(notes: Path, *, encrypted: bool) -> tuple[int, ...]:
    service = None
    if encrypted:
        service = EncryptionService()
        service.dek = b"k" * 32
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            result = run_database_migrations(connection=connection, encryption_enabled=encrypted, encryption_service=service)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
        return result.applied_versions


def _files_schema(files: Path) -> tuple[set[str], set[str]]:
    with closing(sqlite3.connect(files)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {row[1] for row in connection.execute("PRAGMA table_info(files)")}
    return tables, columns


def test_current_database_version_includes_editable_files() -> None:
    assert CURRENT_DATABASE_VERSION >= 10


@pytest.mark.parametrize("encrypted", [False, True])
def test_migration_upgrades_a_legacy_files_database_and_keeps_attachments(tmp_path: Path, encrypted: bool) -> None:
    notes = _version_9_namespace(tmp_path)
    files = tmp_path / "fixture.metalist.files.db"
    with closing(sqlite3.connect(files)) as connection:
        connection.execute(_LEGACY_FILES_TABLE)
        connection.execute(
            "INSERT INTO files VALUES ('attachment', 'title', NULL, NULL, '{}', NULL, NULL, ?, NULL, NULL, 'now', 'now')",
            (b"attachment bytes",),
        )
        connection.commit()

    assert _migrate(notes, encrypted=encrypted) == (10, 11, 12)

    tables, columns = _files_schema(files)
    assert "file_previews" in tables
    assert "content_revision" in columns
    with closing(sqlite3.connect(files)) as connection:
        assert connection.execute("SELECT blob_data, content_revision FROM files").fetchall() == [(b"attachment bytes", 1)]
        assert connection.execute("SELECT count(*) FROM file_previews").fetchone() == (0,)


def test_migration_accepts_a_files_database_the_app_already_upgraded(tmp_path: Path) -> None:
    notes = _version_9_namespace(tmp_path)
    files = tmp_path / "fixture.metalist.files.db"
    with closing(sqlite3.connect(files)) as connection:
        initialize_file_schema(connection)
        connection.commit()

    assert _migrate(notes, encrypted=True) == (10, 11, 12)
    assert _migrate(notes, encrypted=True) == ()
    tables, columns = _files_schema(files)
    assert "file_previews" in tables and "content_revision" in columns


def test_migration_does_not_create_a_missing_files_database(tmp_path: Path) -> None:
    notes = _version_9_namespace(tmp_path)

    assert _migrate(notes, encrypted=False) == (10, 11, 12)
    assert not (tmp_path / "fixture.metalist.files.db").exists()
