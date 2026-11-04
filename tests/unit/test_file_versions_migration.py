"""Migration 13→14: kept file text records its reader and filter versions
(docs/ready-to-build/folder-import-and-file-previews.md, "Text versions")."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from app.db.file_schema import FILE_TEXTS_COLUMNS, initialize_file_schema
from app.db.migrations import run_database_migrations
from app.db.schema import initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION


def _version_13_namespace(tmp_path: Path) -> Path:
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        connection.execute("PRAGMA user_version = 13")
        connection.commit()
    return notes


def _migrate(notes: Path) -> tuple[int, ...]:
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            result = run_database_migrations(connection=connection, encryption_enabled=False, encryption_service=None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
        return result.applied_versions


def _version_13_files(tmp_path: Path) -> Path:
    """A files database as version 13 left it: file_texts without versions."""
    files = tmp_path / "fixture.metalist.files.db"
    with closing(sqlite3.connect(files)) as connection:
        initialize_file_schema(connection)
        connection.execute("ALTER TABLE file_texts DROP COLUMN reader_version")
        connection.execute("ALTER TABLE file_texts DROP COLUMN filter_version")
        for file_id in ("letter", "photo"):
            connection.execute(
                "INSERT INTO files VALUES (?, 'title', NULL, NULL, '{}', NULL, NULL, ?, NULL, NULL, 'now', 'now', 1)",
                (file_id, b"attachment bytes"),
            )
        connection.execute("INSERT INTO file_texts VALUES ('letter', ?, NULL, NULL, ?, NULL, NULL, 0, 1, 'now')", (b"text", b"filter"))
        connection.commit()
    return files


def _columns(files: Path, table: str) -> set[str]:
    with closing(sqlite3.connect(files)) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def test_current_database_version_includes_text_and_preview_versions() -> None:
    assert CURRENT_DATABASE_VERSION >= 14


def test_kept_text_was_read_by_the_first_reader_and_filter(tmp_path: Path) -> None:
    notes = _version_13_namespace(tmp_path)
    files = _version_13_files(tmp_path)

    assert _migrate(notes) == (14,)

    assert _columns(files, "file_texts") == set(FILE_TEXTS_COLUMNS)
    with closing(sqlite3.connect(files)) as connection:
        assert connection.execute("SELECT file_id, text_data, reader_version, filter_version FROM file_texts").fetchall() == [
            ("letter", b"text", 1, 1),
        ]


def test_migration_accepts_a_files_database_the_app_already_upgraded(tmp_path: Path) -> None:
    notes = _version_13_namespace(tmp_path)
    files = tmp_path / "fixture.metalist.files.db"
    with closing(sqlite3.connect(files)) as connection:
        initialize_file_schema(connection)
        connection.commit()

    assert _migrate(notes) == (14,)
    assert _migrate(notes) == ()
    assert _columns(files, "file_texts") == set(FILE_TEXTS_COLUMNS)


def test_migration_does_not_create_a_missing_files_database(tmp_path: Path) -> None:
    notes = _version_13_namespace(tmp_path)

    assert _migrate(notes) == (14,)
    assert not (tmp_path / "fixture.metalist.files.db").exists()
