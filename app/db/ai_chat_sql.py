"""SQLite helpers for the ai_chat table: the vault's AI conversation, one row."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

from app.db.engine import GuardedConnection
from .raw_connection import ConnectionWrapper, raw_sqlite_connection
from app.db.schema import AI_CHAT_TABLE


def _conn(connection: GuardedConnection | sqlite3.Connection | ConnectionWrapper) -> GuardedConnection | sqlite3.Connection:
    if isinstance(connection, GuardedConnection):
        return connection
    return raw_sqlite_connection(connection)


def _serialize_datetime(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError("value must be a datetime")
    return value.isoformat()


def fetch_ai_chat_row(
    connection: GuardedConnection | sqlite3.Connection,
) -> Optional[dict[str, object]]:
    conn = _conn(connection)
    row = conn.execute(
        f"""
        SELECT
            id,
            state_json,
            state_encryption_nonce,
            state_encryption_tag,
            created_at,
            updated_at
        FROM {AI_CHAT_TABLE}
        WHERE id = 1
        """,
    ).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "state_json": row["state_json"],
        "state_encryption_nonce": row["state_encryption_nonce"],
        "state_encryption_tag": row["state_encryption_tag"],
        "created_at": datetime.fromisoformat(row["created_at"]),
        "updated_at": datetime.fromisoformat(row["updated_at"]),
    }


def upsert_ai_chat_row(
    connection: GuardedConnection | sqlite3.Connection | ConnectionWrapper,
    *,
    state_json: str,
    state_encryption_nonce: Optional[bytes],
    state_encryption_tag: Optional[bytes],
    updated_at: datetime,
) -> None:
    conn = _conn(connection)
    serialized_updated_at = _serialize_datetime(updated_at)
    conn.execute(
        f"""
        INSERT INTO {AI_CHAT_TABLE} (
            id,
            state_json,
            state_encryption_nonce,
            state_encryption_tag,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            state_json = excluded.state_json,
            state_encryption_nonce = excluded.state_encryption_nonce,
            state_encryption_tag = excluded.state_encryption_tag,
            updated_at = excluded.updated_at
        """,
        (
            1,
            state_json,
            state_encryption_nonce,
            state_encryption_tag,
            serialized_updated_at,
            serialized_updated_at,
        ),
    )


def delete_ai_chat_row(connection: GuardedConnection | sqlite3.Connection | ConnectionWrapper) -> None:
    conn = _conn(connection)
    conn.execute(f"DELETE FROM {AI_CHAT_TABLE} WHERE id = 1")
