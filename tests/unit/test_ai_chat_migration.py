"""Migration 18→19: the vault gains the ai_chat table, its saved AI conversation."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.db.migrations import run_database_migrations
from app.db.schema import AI_CHAT_COLUMNS, AI_CHAT_TABLE, initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION

_PREVIOUS_VERSION = 18


def _version_18_vault(tmp_path: Path, *, has_table: bool) -> Path:
    """A vault at version 18; opening it with this MetaList may already have added the table."""
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        if not has_table:
            connection.execute(f"DROP TABLE {AI_CHAT_TABLE}")
        connection.execute(f"PRAGMA user_version = {_PREVIOUS_VERSION}")
        connection.commit()
    return notes


def _migrate(notes: Path) -> tuple[int, ...]:
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            result = run_database_migrations(connection=connection, encryption_enabled=False, encryption_service=None)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
        return result.applied_versions


def _columns(notes: Path) -> set[str]:
    with closing(sqlite3.connect(notes)) as connection:
        return {row[1] for row in connection.execute(f"PRAGMA table_info({AI_CHAT_TABLE})")}


def test_this_is_the_current_version() -> None:
    assert CURRENT_DATABASE_VERSION == _PREVIOUS_VERSION + 1


@pytest.mark.parametrize("has_table", [False, True], ids=["before-open", "added-on-open"])
def test_migration_adds_the_conversation_table(tmp_path: Path, has_table: bool) -> None:
    notes = _version_18_vault(tmp_path, has_table=has_table)

    assert _migrate(notes) == (19,)
    assert _migrate(notes) == ()

    assert _columns(notes) == set(AI_CHAT_COLUMNS)
    with closing(sqlite3.connect(notes)) as connection:
        assert connection.execute(f"SELECT count(*) FROM {AI_CHAT_TABLE}").fetchone() == (0,)


def test_migration_refuses_a_table_of_another_shape(tmp_path: Path) -> None:
    notes = _version_18_vault(tmp_path, has_table=False)
    with closing(sqlite3.connect(notes)) as connection:
        connection.execute(f"CREATE TABLE {AI_CHAT_TABLE} (id INTEGER PRIMARY KEY, other TEXT)")
        connection.commit()

    with pytest.raises(RuntimeError, match="other columns"):
        _migrate(notes)
