"""Migration 19→20: each vault's launch profile gains shared_on_network, read before unlock to
choose where its server listens (docs/security/README.md, "Sharing on the Network")."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.db.migrations import run_database_migrations
from app.db.schema import NAMESPACE_LAUNCH_PROFILE_TABLE, SHARED_ON_NETWORK_COLUMN, initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION

_PREVIOUS_VERSION = 19
_LAUNCH_PROFILE_COLUMNS_BEFORE = {"namespace", "port", "https_port", "mcp_port", "created_at", "updated_at"}


def _version_19_vault(tmp_path: Path, *, has_column: bool) -> Path:
    """A vault at version 19 with its ports saved; opening it with this MetaList may already have
    added the column."""
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        if not has_column:
            connection.execute(f"ALTER TABLE {NAMESPACE_LAUNCH_PROFILE_TABLE} DROP COLUMN {SHARED_ON_NETWORK_COLUMN}")
        connection.execute(
            f"INSERT INTO {NAMESPACE_LAUNCH_PROFILE_TABLE} (namespace, port, https_port, mcp_port, created_at, updated_at)"
            " VALUES ('thomas', 9000, 9443, NULL, '2026-11-01', '2026-11-01')"
        )
        connection.execute(f"PRAGMA user_version = {_PREVIOUS_VERSION}")
        connection.commit()
    return notes


def _migrate(notes: Path) -> tuple[int, ...]:
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            result = run_database_migrations(connection=connection, encryption_enabled=False, encryption_service=None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
        return result.applied_versions


def test_this_is_the_current_version() -> None:
    assert CURRENT_DATABASE_VERSION == _PREVIOUS_VERSION + 1


@pytest.mark.parametrize("has_column", [False, True], ids=["before-open", "added-on-open"])
def test_migration_adds_the_sharing_choice_and_a_vault_is_not_shared(tmp_path: Path, has_column: bool) -> None:
    notes = _version_19_vault(tmp_path, has_column=has_column)

    assert _migrate(notes) == (20,)
    assert _migrate(notes) == ()

    with closing(sqlite3.connect(notes)) as connection:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({NAMESPACE_LAUNCH_PROFILE_TABLE})")}
        rows = connection.execute(
            f"SELECT namespace, port, https_port, {SHARED_ON_NETWORK_COLUMN} FROM {NAMESPACE_LAUNCH_PROFILE_TABLE}"
        ).fetchall()
    assert columns == _LAUNCH_PROFILE_COLUMNS_BEFORE | {SHARED_ON_NETWORK_COLUMN}
    assert rows == [("thomas", 9000, 9443, 0)]


def test_the_column_holds_only_yes_or_no(tmp_path: Path) -> None:
    notes = _version_19_vault(tmp_path, has_column=False)
    _migrate(notes)
    with closing(sqlite3.connect(notes)) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(f"UPDATE {NAMESPACE_LAUNCH_PROFILE_TABLE} SET {SHARED_ON_NETWORK_COLUMN} = 2")
