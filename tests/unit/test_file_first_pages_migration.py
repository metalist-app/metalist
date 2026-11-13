"""Migration 17→18: the files catalog gains file_first_pages, a PDF's first page as a picture."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from app.db.blob_store import resolve_file_catalog_path
from app.db.file_schema import FILE_FIRST_PAGES_COLUMNS, initialize_file_schema
from app.db.migrations import run_database_migrations
from app.db.schema import initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION

_PREVIOUS_VERSION = 17


def _version_17_vault(tmp_path: Path) -> Path:
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        connection.execute(f"PRAGMA user_version = {_PREVIOUS_VERSION}")
        connection.commit()
    return notes


def _catalog(notes: Path, *, has_first_pages: bool) -> Path:
    catalog = resolve_file_catalog_path(notes)
    catalog.parent.mkdir(parents=True)
    with closing(sqlite3.connect(catalog)) as connection:
        initialize_file_schema(connection)
        if not has_first_pages:
            connection.execute("DROP TABLE file_first_pages")
        connection.execute(
            "INSERT INTO files (id, title, metadata_json, blob_id, blob_seal, created_at, updated_at) "
            "VALUES ('report', 'report.pdf', '{}', 'blob-1', x'00', 'now', 'now')"
        )
        connection.commit()
    return catalog


def _migrate(notes: Path) -> tuple[int, ...]:
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            result = run_database_migrations(connection=connection, encryption_enabled=False, encryption_service=None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
        return result.applied_versions


def _first_page_columns(catalog: Path) -> set[str]:
    with closing(sqlite3.connect(catalog)) as connection:
        return {row[1] for row in connection.execute("PRAGMA table_info(file_first_pages)")}


def test_migration_adds_first_pages_and_keeps_the_files(tmp_path: Path) -> None:
    notes = _version_17_vault(tmp_path)
    catalog = _catalog(notes, has_first_pages=False)

    assert _migrate(notes) == (18, 19, 20)

    assert _first_page_columns(catalog) == set(FILE_FIRST_PAGES_COLUMNS)
    with closing(sqlite3.connect(catalog)) as connection:
        assert connection.execute("SELECT id, blob_id FROM files").fetchall() == [("report", "blob-1")]
        assert connection.execute("SELECT count(*) FROM file_first_pages").fetchone() == (0,)


def test_migration_accepts_a_catalog_the_app_already_upgraded(tmp_path: Path) -> None:
    notes = _version_17_vault(tmp_path)
    catalog = _catalog(notes, has_first_pages=True)

    assert _migrate(notes) == (18, 19, 20)
    assert _migrate(notes) == ()
    assert _first_page_columns(catalog) == set(FILE_FIRST_PAGES_COLUMNS)


def test_migration_does_not_create_a_missing_catalog(tmp_path: Path) -> None:
    notes = _version_17_vault(tmp_path)

    assert _migrate(notes) == (18, 19, 20)
    assert not resolve_file_catalog_path(notes).exists()
