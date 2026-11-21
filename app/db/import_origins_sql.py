"""SQLite helpers for the import_origins table: where each import's notes came from, a row per import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3

from app.db.engine import GuardedConnection
from app.db.raw_connection import raw_sqlite_connection
from app.db.schema import IMPORT_ORIGINS_COLUMNS, IMPORT_ORIGINS_TABLE


@dataclass(frozen=True, slots=True)
class StoredImportOrigins:
    """A row as stored: state_json is ciphertext when its nonce is set."""

    id: int
    state_json: str
    state_encryption_nonce: bytes | None
    state_encryption_tag: bytes | None
    created_at: datetime


def _conn(connection: object) -> GuardedConnection | sqlite3.Connection:
    if isinstance(connection, GuardedConnection):
        return connection
    return raw_sqlite_connection(connection)


def _optional_bytes(value: object, *, column: str) -> bytes | None:
    if value is not None and not isinstance(value, bytes):
        raise TypeError(f"import_origins.{column} must be bytes or None")
    return value


def fetch_all_import_origins(connection: object) -> list[StoredImportOrigins]:
    """Every import's row, the oldest first."""
    rows = _conn(connection).execute(
        f"SELECT {', '.join(IMPORT_ORIGINS_COLUMNS)} FROM {IMPORT_ORIGINS_TABLE} ORDER BY id ASC",
    ).fetchall()
    stored: list[StoredImportOrigins] = []
    for row in rows:
        values = dict(zip(IMPORT_ORIGINS_COLUMNS, row, strict=True))
        if not isinstance(values["id"], int) or not isinstance(values["state_json"], str) or not isinstance(values["created_at"], str):
            raise TypeError("import_origins row has a column of another type")
        stored.append(StoredImportOrigins(
            id=values["id"], state_json=values["state_json"],
            state_encryption_nonce=_optional_bytes(values["state_encryption_nonce"], column="state_encryption_nonce"),
            state_encryption_tag=_optional_bytes(values["state_encryption_tag"], column="state_encryption_tag"),
            created_at=datetime.fromisoformat(values["created_at"]),
        ))
    return stored


def insert_import_origins(
    connection: object, *, state_json: str, state_encryption_nonce: bytes | None, state_encryption_tag: bytes | None,
    created_at: datetime,
) -> None:
    _conn(connection).execute(
        f"""
        INSERT INTO {IMPORT_ORIGINS_TABLE} (state_json, state_encryption_nonce, state_encryption_tag, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (state_json, state_encryption_nonce, state_encryption_tag, created_at.isoformat()),
    )


def update_import_origins_state(
    connection: object, *, row_id: int, state_json: str, state_encryption_nonce: bytes | None,
    state_encryption_tag: bytes | None,
) -> None:
    _conn(connection).execute(
        f"""
        UPDATE {IMPORT_ORIGINS_TABLE}
        SET state_json = ?, state_encryption_nonce = ?, state_encryption_tag = ?
        WHERE id = ?
        """,
        (state_json, state_encryption_nonce, state_encryption_tag, row_id),
    )
