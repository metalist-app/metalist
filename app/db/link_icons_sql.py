"""SQLite helpers for cached site icons (beside link titles)."""

from __future__ import annotations

from datetime import datetime
import sqlite3

from app.db.engine import GuardedConnection
from app.db.link_titles_sql import _conn, _parse_datetime, _serialize_datetime
from app.db.schema import LINK_ICONS_TABLE


def fetch_all_link_icon_rows(
    connection: GuardedConnection | sqlite3.Connection,
) -> list[dict[str, object]]:
    conn = _conn(connection)
    rows = conn.execute(
        f"""
        SELECT
            id,
            origin,
            origin_encryption_nonce,
            origin_encryption_tag,
            icon_png,
            icon_png_encryption_nonce,
            icon_png_encryption_tag,
            status,
            last_error_kind,
            failure_count,
            last_checked_at,
            next_check_after,
            created_at,
            updated_at
        FROM {LINK_ICONS_TABLE}
        ORDER BY id ASC
        """,
    ).fetchall()
    return [
        {
            "id": row["id"],
            "origin": row["origin"],
            "origin_encryption_nonce": row["origin_encryption_nonce"],
            "origin_encryption_tag": row["origin_encryption_tag"],
            "icon_png": row["icon_png"],
            "icon_png_encryption_nonce": row["icon_png_encryption_nonce"],
            "icon_png_encryption_tag": row["icon_png_encryption_tag"],
            "status": row["status"],
            "last_error_kind": row["last_error_kind"],
            "failure_count": row["failure_count"],
            "last_checked_at": _parse_datetime(row["last_checked_at"], field_name="link_icons.last_checked_at"),
            "next_check_after": _parse_datetime(row["next_check_after"], field_name="link_icons.next_check_after"),
            "created_at": _parse_datetime(row["created_at"], field_name="link_icons.created_at"),
            "updated_at": _parse_datetime(row["updated_at"], field_name="link_icons.updated_at"),
        }
        for row in rows
    ]


def insert_link_icon_row(
    connection: GuardedConnection | sqlite3.Connection,
    *,
    origin: str,
    origin_encryption_nonce: bytes | None,
    origin_encryption_tag: bytes | None,
    icon_png: str | None,
    icon_png_encryption_nonce: bytes | None,
    icon_png_encryption_tag: bytes | None,
    status: str,
    last_error_kind: str | None,
    failure_count: int,
    last_checked_at: datetime,
    next_check_after: datetime | None,
    created_at: datetime,
    updated_at: datetime,
) -> int:
    conn = _conn(connection)
    cursor = conn.execute(
        f"""
        INSERT INTO {LINK_ICONS_TABLE} (
            origin,
            origin_encryption_nonce,
            origin_encryption_tag,
            icon_png,
            icon_png_encryption_nonce,
            icon_png_encryption_tag,
            status,
            last_error_kind,
            failure_count,
            last_checked_at,
            next_check_after,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            origin,
            origin_encryption_nonce,
            origin_encryption_tag,
            icon_png,
            icon_png_encryption_nonce,
            icon_png_encryption_tag,
            status,
            last_error_kind,
            failure_count,
            _serialize_datetime(last_checked_at),
            _serialize_datetime(next_check_after),
            _serialize_datetime(created_at),
            _serialize_datetime(updated_at),
        ),
    )
    row_id = cursor.lastrowid
    if not isinstance(row_id, int):
        raise RuntimeError("Expected sqlite lastrowid to be int")
    return row_id


def update_link_icon_row(
    connection: GuardedConnection | sqlite3.Connection,
    row_id: int,
    *,
    origin: str,
    origin_encryption_nonce: bytes | None,
    origin_encryption_tag: bytes | None,
    icon_png: str | None,
    icon_png_encryption_nonce: bytes | None,
    icon_png_encryption_tag: bytes | None,
    status: str,
    last_error_kind: str | None,
    failure_count: int,
    last_checked_at: datetime,
    next_check_after: datetime | None,
    updated_at: datetime,
) -> None:
    if not isinstance(row_id, int):
        raise TypeError("row_id must be an int")
    conn = _conn(connection)
    conn.execute(
        f"""
        UPDATE {LINK_ICONS_TABLE}
        SET origin = ?,
            origin_encryption_nonce = ?,
            origin_encryption_tag = ?,
            icon_png = ?,
            icon_png_encryption_nonce = ?,
            icon_png_encryption_tag = ?,
            status = ?,
            last_error_kind = ?,
            failure_count = ?,
            last_checked_at = ?,
            next_check_after = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            origin,
            origin_encryption_nonce,
            origin_encryption_tag,
            icon_png,
            icon_png_encryption_nonce,
            icon_png_encryption_tag,
            status,
            last_error_kind,
            failure_count,
            _serialize_datetime(last_checked_at),
            _serialize_datetime(next_check_after),
            _serialize_datetime(updated_at),
            row_id,
        ),
    )
