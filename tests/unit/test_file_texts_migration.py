"""Migration 12→13: the files database gains file_texts, a file's text kept for search."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from app.db.file_schema import FILE_TEXTS_COLUMNS, initialize_file_schema
from app.db.migrations import run_database_migrations
from app.db.schema import initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION


def _version_12_namespace(tmp_path: Path) -> Path:
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        connection.execute("PRAGMA user_version = 12")
        connection.commit()
    return notes


def _migrate(notes: Path) -> tuple[int, ...]:
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            result = run_database_migrations(connection=connection, encryption_enabled=False, encryption_service=None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
        return result.applied_versions


def _version_12_files(tmp_path: Path) -> Path:
    files = tmp_path / "fixture.metalist.files.db"
    with closing(sqlite3.connect(files)) as connection:
        initialize_file_schema(connection)
        connection.execute("DROP TABLE file_texts")
        connection.execute(
            "INSERT INTO files VALUES ('attachment', 'title', NULL, NULL, '{}', NULL, NULL, ?, NULL, NULL, 'now', 'now', 1)",
            (b"attachment bytes",),
        )
        connection.commit()
    return files


def _file_texts_columns(files: Path) -> set[str]:
    with closing(sqlite3.connect(files)) as connection:
        return {row[1] for row in connection.execute("PRAGMA table_info(file_texts)")}


def test_current_database_version_includes_file_texts() -> None:
    assert CURRENT_DATABASE_VERSION >= 13


def test_migration_adds_file_texts_and_keeps_attachments(tmp_path: Path) -> None:
    notes = _version_12_namespace(tmp_path)
    files = _version_12_files(tmp_path)

    assert _migrate(notes) == (13, 14, 15)

    assert _file_texts_columns(files) == set(FILE_TEXTS_COLUMNS)
    with closing(sqlite3.connect(files)) as connection:
        assert connection.execute("SELECT blob_data FROM files").fetchall() == [(b"attachment bytes",)]
        assert connection.execute("SELECT count(*) FROM file_texts").fetchone() == (0,)


def test_migration_accepts_a_files_database_the_app_already_upgraded(tmp_path: Path) -> None:
    notes = _version_12_namespace(tmp_path)
    files = tmp_path / "fixture.metalist.files.db"
    with closing(sqlite3.connect(files)) as connection:
        initialize_file_schema(connection)
        connection.commit()

    assert _migrate(notes) == (13, 14, 15)
    assert _migrate(notes) == ()
    assert _file_texts_columns(files) == set(FILE_TEXTS_COLUMNS)


def test_migration_does_not_create_a_missing_files_database(tmp_path: Path) -> None:
    notes = _version_12_namespace(tmp_path)

    assert _migrate(notes) == (13, 14, 15)
    assert not (tmp_path / "fixture.metalist.files.db").exists()
