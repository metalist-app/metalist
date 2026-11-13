"""Database schema version constants without runtime configuration imports, and the check that
refuses a vault saved by a newer MetaList before anything is written to it."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.version import __version__

CURRENT_DATABASE_VERSION = 20
# A vault has no version before its database exists.
NO_DATABASE_VERSION = 0
# The exit status of a vault's server that found its vault saved by a newer MetaList: the
# launcher shows the reason instead of a crash (main.py, namespace_switcher.child_exit_error).
EXIT_VAULT_NEEDS_NEWER_METALIST = 3


class VaultNeedsNewerMetaList(Exception):
    """A vault saved by a newer MetaList: an expected refusal, its message for the person."""


def _checked_version(version: object) -> int:
    if not isinstance(version, int) or version < NO_DATABASE_VERSION:
        raise RuntimeError(f"Invalid database user_version: {version!r}")
    return version


def database_version_on_disk(database_path: Path) -> int:
    """The version a vault's database was saved at, read without writing anything (a read-only
    connection); NO_DATABASE_VERSION when it doesn't exist yet."""
    if not database_path.is_file():
        return NO_DATABASE_VERSION
    with closing(sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)) as connection:
        row = connection.execute("PRAGMA user_version").fetchone()
    return _checked_version(row[0])


def is_saved_by_newer_metalist(database_path: Path) -> bool:
    """Whether a vault was saved by a newer MetaList, read without writing anything."""
    return database_version_on_disk(database_path) > CURRENT_DATABASE_VERSION


def newer_vault_message(database_path: Path) -> str:
    """What to tell the person about a vault saved by a newer MetaList."""
    return _newer_vault_message(vault=database_path.parent.name, version=database_version_on_disk(database_path))


def _newer_vault_message(*, vault: str, version: int) -> str:
    assert version > CURRENT_DATABASE_VERSION, "only a vault saved by a newer MetaList"
    return (
        f"Vault {vault} was saved by a newer MetaList (database version {version}); "
        f"this MetaList, {__version__}, opens versions up to {CURRENT_DATABASE_VERSION}. "
        "Update MetaList to open it: metalist update, or uv tool upgrade metalist."
    )


def require_database_not_newer(database_path: Path) -> None:
    """Refuse, before anything opens it for writing, a vault saved by a newer MetaList: an older
    MetaList would set up its own tables in it (2026-11-11)."""
    if is_saved_by_newer_metalist(database_path):
        raise VaultNeedsNewerMetaList(newer_vault_message(database_path))


# PRAGMA database_list: the main database's row, and its file's column ('' for one in memory).
_MAIN_DATABASE_ROW = 0
_DATABASE_FILE_COLUMN = 2


def require_connection_not_newer(connection: sqlite3.Connection) -> None:
    """The same refusal for a database already open, before its tables are set up (schema.py):
    every way of opening a vault passes here, so an older MetaList never sets up its tables in a
    newer vault."""
    version = _checked_version(connection.execute("PRAGMA user_version").fetchone()[0])
    if version <= CURRENT_DATABASE_VERSION:
        return
    database_file = connection.execute("PRAGMA database_list").fetchall()[_MAIN_DATABASE_ROW][_DATABASE_FILE_COLUMN]
    raise VaultNeedsNewerMetaList(_newer_vault_message(vault=Path(database_file).parent.name, version=version))
