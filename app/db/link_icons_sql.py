"""SQLite helpers for cached site icons (beside link titles)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import sqlite3

from app.db.engine import GuardedConnection
from app.db.link_titles_sql import _parse_datetime, _serialize_datetime
from app.db.raw_connection import raw_sqlite_connection
from app.db.schema import LINK_ICONS_TABLE


@dataclass(frozen=True, slots=True)
class StoredLinkIconRow:
    """A link_icons row as stored: origin and icon are ciphertext when their nonce is set."""

    id: int
    origin: str
    origin_encryption_nonce: bytes | None
    origin_encryption_tag: bytes | None
    icon_png: str | None
    icon_png_encryption_nonce: bytes | None
    icon_png_encryption_tag: bytes | None
    status: str
    last_error_kind: str | None
    failure_count: int
    last_checked_at: datetime
    next_check_after: datetime | None
    created_at: datetime
    updated_at: datetime


def _conn(connection: object) -> GuardedConnection | sqlite3.Connection:
    """The engine's guarded connection as it is; a plain or session-guarded one unwrapped."""
    if isinstance(connection, GuardedConnection):
        return connection
    return raw_sqlite_connection(connection)


def _text(value: object, *, column: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"link_icons.{column} must be a string")
    return value


def _optional_text(value: object, *, column: str) -> str | None:
    if value is None:
        return None
    return _text(value, column=column)


def _optional_bytes(value: object, *, column: str) -> bytes | None:
    if value is not None and not isinstance(value, bytes):
        raise TypeError(f"link_icons.{column} must be bytes or None")
    return value


def _count(value: object, *, column: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise TypeError(f"link_icons.{column} must be a non-negative int")
    return value


def _moment(value: object, *, column: str) -> datetime:
    moment = _parse_datetime(value, field_name=f"link_icons.{column}")
    if moment is None:
        raise TypeError(f"link_icons.{column} must be a datetime")
    return moment


def fetch_all_link_icon_rows(connection: object) -> list[StoredLinkIconRow]:
    rows = _conn(connection).execute(
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
        StoredLinkIconRow(
            id=_count(row[0], column="id"),
            origin=_text(row[1], column="origin"),
            origin_encryption_nonce=_optional_bytes(row[2], column="origin_encryption_nonce"),
            origin_encryption_tag=_optional_bytes(row[3], column="origin_encryption_tag"),
            icon_png=_optional_text(row[4], column="icon_png"),
            icon_png_encryption_nonce=_optional_bytes(row[5], column="icon_png_encryption_nonce"),
            icon_png_encryption_tag=_optional_bytes(row[6], column="icon_png_encryption_tag"),
            status=_text(row[7], column="status"),
            last_error_kind=_optional_text(row[8], column="last_error_kind"),
            failure_count=_count(row[9], column="failure_count"),
            last_checked_at=_moment(row[10], column="last_checked_at"),
            next_check_after=_parse_datetime(row[11], field_name="link_icons.next_check_after"),
            created_at=_moment(row[12], column="created_at"),
            updated_at=_moment(row[13], column="updated_at"),
        )
        for row in rows
    ]


def insert_link_icon_row(connection: object, row: StoredLinkIconRow) -> int:
    """Store a new row (its id is the database's); the new id."""
    cursor = _conn(connection).execute(
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
            row.origin,
            row.origin_encryption_nonce,
            row.origin_encryption_tag,
            row.icon_png,
            row.icon_png_encryption_nonce,
            row.icon_png_encryption_tag,
            row.status,
            row.last_error_kind,
            row.failure_count,
            _serialize_datetime(row.last_checked_at),
            _serialize_datetime(row.next_check_after),
            _serialize_datetime(row.created_at),
            _serialize_datetime(row.updated_at),
        ),
    )
    row_id = cursor.lastrowid
    if not isinstance(row_id, int):
        raise RuntimeError("Expected sqlite lastrowid to be int")
    return row_id


def update_link_icon_row(connection: object, row: StoredLinkIconRow) -> None:
    """Store everything about the row with row.id but when it was created."""
    _conn(connection).execute(
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
            row.origin,
            row.origin_encryption_nonce,
            row.origin_encryption_tag,
            row.icon_png,
            row.icon_png_encryption_nonce,
            row.icon_png_encryption_tag,
            row.status,
            row.last_error_kind,
            row.failure_count,
            _serialize_datetime(row.last_checked_at),
            _serialize_datetime(row.next_check_after),
            _serialize_datetime(row.updated_at),
            row.id,
        ),
    )
