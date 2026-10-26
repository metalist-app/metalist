"""Migration 11→12: the link_icons table (site icons beside link titles); the
encryption audit before and after it is in test_encrypted_namespace_audit.py."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.db.migrations import run_database_migrations
from app.db.schema import LINK_ICONS_COLUMNS, LINK_ICONS_TABLE, initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION
from app.services.encryption import EncryptionService


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({LINK_ICONS_TABLE})")}


def _version_11_namespace(tmp_path: Path, *, has_table: bool) -> Path:
    """A version-11 notes database, with the table already added by the on-open schema
    helper or without it."""
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        if not has_table:
            connection.execute(f"DROP TABLE {LINK_ICONS_TABLE}")
        connection.execute("PRAGMA user_version = 11")
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
        assert _columns(connection) == set(LINK_ICONS_COLUMNS)
        return result.applied_versions


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("has_table", [False, True], ids=["absent", "added-on-open"])
def test_version_11_gains_the_link_icons_table(tmp_path: Path, encrypted: bool, has_table: bool) -> None:
    notes = _version_11_namespace(tmp_path, has_table=has_table)

    assert _migrate(notes, encrypted=encrypted) == (12,)
    assert _migrate(notes, encrypted=encrypted) == ()


def test_a_half_built_link_icons_table_stops_the_migration(tmp_path: Path) -> None:
    notes = _version_11_namespace(tmp_path, has_table=False)
    with closing(sqlite3.connect(notes)) as connection:
        connection.execute(f"CREATE TABLE {LINK_ICONS_TABLE} (id INTEGER PRIMARY KEY)")
        connection.commit()

    with pytest.raises(RuntimeError, match="link_icons"):
        _migrate(notes, encrypted=False)
