"""Composable sqlite helpers for the catalog of stored files."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Iterable, Optional

from app.db.file_schema import (
    BLOB_TABLES,
    FILE_FIRST_PAGES_TABLE,
    FILE_PREVIEW_VARIANTS,
    FILE_PREVIEWS_TABLE,
    FILE_TEXTS_TABLE,
    FILES_TABLE,
)


def _serialize_datetime(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TypeError(f"value must be a datetime, got {type(value)}")
    return value.isoformat()


def _deserialize_row(row: sqlite3.Row) -> dict[str, object]:
    file_id = row["id"]

    def _parse_datetime(field: str) -> datetime:
        raw = row[field]
        if not isinstance(raw, str):
            raise TypeError(f"files.{field} must be a string | file_id={file_id} value={raw!r}")
        return datetime.fromisoformat(raw)

    content_revision = row["content_revision"]
    if not isinstance(content_revision, int) or content_revision < 1:
        raise TypeError(f"files.content_revision must be a positive integer | file_id={file_id} value={content_revision!r}")

    return {
        "id": file_id,
        "title": row["title"],
        "title_encryption_nonce": row["title_encryption_nonce"],
        "title_encryption_tag": row["title_encryption_tag"],
        "metadata_json": row["metadata_json"],
        "metadata_encryption_nonce": row["metadata_encryption_nonce"],
        "metadata_encryption_tag": row["metadata_encryption_tag"],
        "blob_id": row["blob_id"],
        "blob_seal": row["blob_seal"],
        "blob_seal_encryption_nonce": row["blob_seal_encryption_nonce"],
        "blob_seal_encryption_tag": row["blob_seal_encryption_tag"],
        "created_at": _parse_datetime("created_at"),
        "updated_at": _parse_datetime("updated_at"),
        "content_revision": content_revision,
    }


def insert_file(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    title: str,
    title_encryption_nonce: Optional[bytes],
    title_encryption_tag: Optional[bytes],
    metadata_json: str,
    metadata_encryption_nonce: Optional[bytes],
    metadata_encryption_tag: Optional[bytes],
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
    created_at: datetime,
    updated_at: datetime,
) -> None:
    connection.execute(
        f"""
        INSERT INTO {FILES_TABLE} (
            id,
            title,
            title_encryption_nonce,
            title_encryption_tag,
            metadata_json,
            metadata_encryption_nonce,
            metadata_encryption_tag,
            blob_id,
            blob_seal,
            blob_seal_encryption_nonce,
            blob_seal_encryption_tag,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            file_id,
            title,
            title_encryption_nonce,
            title_encryption_tag,
            metadata_json,
            metadata_encryption_nonce,
            metadata_encryption_tag,
            blob_id,
            blob_seal,
            blob_seal_encryption_nonce,
            blob_seal_encryption_tag,
            _serialize_datetime(created_at),
            _serialize_datetime(updated_at),
        ),
    )


class AttachmentSizeExceeded(ValueError):
    pass


def fetch_file_metadata(connection: sqlite3.Connection, file_id: str):
    row = connection.execute(f"SELECT * FROM {FILES_TABLE} WHERE id=?", (file_id,)).fetchone()
    if row is None:
        return None
    return _deserialize_row(row)


def fetch_all_file_metadata(connection: sqlite3.Connection):
    return [_deserialize_row(row) for row in connection.execute(f"SELECT * FROM {FILES_TABLE} ORDER BY created_at ASC")]


def fetch_blob_ids_of_files(connection: sqlite3.Connection, file_ids: list[str]) -> list[str]:
    """Each of these files' own content blob, as many as are still present."""
    placeholders = ",".join("?" for _ in file_ids)
    rows = connection.execute(f"SELECT blob_id FROM {FILES_TABLE} WHERE id IN ({placeholders})", tuple(file_ids)).fetchall()
    return [str(row["blob_id"]) for row in rows]


def fetch_every_blob_id_of_files(connection: sqlite3.Connection, file_ids: list[str]) -> list[str]:
    """The content, preview, text and first-page blobs of these files: everything deleting them leaves behind."""
    if not file_ids:
        return []
    placeholders = ",".join("?" for _ in file_ids)
    parameters = tuple(file_ids)
    blob_ids = fetch_blob_ids_of_files(connection, file_ids)
    for table in (FILE_PREVIEWS_TABLE, FILE_TEXTS_TABLE, FILE_FIRST_PAGES_TABLE):
        rows = connection.execute(f"SELECT blob_id FROM {table} WHERE file_id IN ({placeholders})", parameters).fetchall()
        blob_ids.extend(str(row["blob_id"]) for row in rows)
    return blob_ids


def fetch_all_blob_ids(connection: sqlite3.Connection) -> set[str]:
    """Every blob the catalog names. Plaintext columns only: needs no key. A catalog from before
    version 18 (a safety backup taken before the upgrade, a restored backup) has no first pages."""
    blob_ids: set[str] = set()
    present = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    for table in BLOB_TABLES:
        if table == FILE_FIRST_PAGES_TABLE and table not in present:
            continue
        blob_ids.update(str(row[0]) for row in connection.execute(f"SELECT blob_id FROM {table}").fetchall())
    return blob_ids


def fetch_file(connection: sqlite3.Connection, file_id: str) -> Optional[dict[str, object]]:
    row = connection.execute(
        f"SELECT * FROM {FILES_TABLE} WHERE id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    return _deserialize_row(row)


def fetch_all_file_ids(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(f"SELECT id FROM {FILES_TABLE} ORDER BY created_at ASC").fetchall()
    ids: list[str] = []
    for row in rows:
        file_id = row["id"]
        if not isinstance(file_id, str):
            raise TypeError(f"files.id must be a string, got {type(file_id)}")
        ids.append(file_id)
    return ids


def update_file_storage_fields(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    title: str,
    title_encryption_nonce: Optional[bytes],
    title_encryption_tag: Optional[bytes],
    metadata_json: str,
    metadata_encryption_nonce: Optional[bytes],
    metadata_encryption_tag: Optional[bytes],
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
    updated_at: datetime,
) -> None:
    connection.execute(
        f"""
        UPDATE {FILES_TABLE}
        SET
            title = ?,
            title_encryption_nonce = ?,
            title_encryption_tag = ?,
            metadata_json = ?,
            metadata_encryption_nonce = ?,
            metadata_encryption_tag = ?,
            blob_id = ?,
            blob_seal = ?,
            blob_seal_encryption_nonce = ?,
            blob_seal_encryption_tag = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            title,
            title_encryption_nonce,
            title_encryption_tag,
            metadata_json,
            metadata_encryption_nonce,
            metadata_encryption_tag,
            blob_id,
            blob_seal,
            blob_seal_encryption_nonce,
            blob_seal_encryption_tag,
            _serialize_datetime(updated_at),
            file_id,
        ),
    )


def update_file_name_fields(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    title: str,
    title_encryption_nonce: Optional[bytes],
    title_encryption_tag: Optional[bytes],
    metadata_json: str,
    metadata_encryption_nonce: Optional[bytes],
    metadata_encryption_tag: Optional[bytes],
    updated_at: datetime,
) -> int:
    """A rename: the title and the metadata naming the file; content, revision and
    previews stay as they are. Returns the number of rows changed."""
    cursor = connection.execute(
        f"""
        UPDATE {FILES_TABLE}
        SET
            title = ?,
            title_encryption_nonce = ?,
            title_encryption_tag = ?,
            metadata_json = ?,
            metadata_encryption_nonce = ?,
            metadata_encryption_tag = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            title,
            title_encryption_nonce,
            title_encryption_tag,
            metadata_json,
            metadata_encryption_nonce,
            metadata_encryption_tag,
            _serialize_datetime(updated_at),
            file_id,
        ),
    )
    return int(cursor.rowcount)


def delete_files(connection: sqlite3.Connection, file_ids: Iterable[str]) -> int:
    identifiers = list(file_ids)
    if not identifiers:
        return 0
    placeholders = ",".join(["?"] * len(identifiers))
    cursor = connection.execute(
        f"DELETE FROM {FILES_TABLE} WHERE id IN ({placeholders})",
        tuple(identifiers),
    )
    return int(cursor.rowcount)


def replace_file_content_fields(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    metadata_json: str,
    metadata_encryption_nonce: Optional[bytes],
    metadata_encryption_tag: Optional[bytes],
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
    expected_revision: int,
    updated_at: datetime,
) -> int:
    """Replace a file's content when it is still at expected_revision; returns the updated row count."""
    if not isinstance(expected_revision, int) or expected_revision < 1:
        raise TypeError(f"expected_revision must be a positive integer, got {expected_revision!r}")
    cursor = connection.execute(
        f"""
        UPDATE {FILES_TABLE}
        SET
            metadata_json = ?,
            metadata_encryption_nonce = ?,
            metadata_encryption_tag = ?,
            blob_id = ?,
            blob_seal = ?,
            blob_seal_encryption_nonce = ?,
            blob_seal_encryption_tag = ?,
            updated_at = ?,
            content_revision = content_revision + 1
        WHERE id = ? AND content_revision = ?
        """,
        (
            metadata_json,
            metadata_encryption_nonce,
            metadata_encryption_tag,
            blob_id,
            blob_seal,
            blob_seal_encryption_nonce,
            blob_seal_encryption_tag,
            _serialize_datetime(updated_at),
            file_id,
            expected_revision,
        ),
    )
    return int(cursor.rowcount)


def _require_preview_variant(variant: str) -> None:
    if variant not in FILE_PREVIEW_VARIANTS:
        raise ValueError(f"file preview variant must be one of {FILE_PREVIEW_VARIANTS}, got {variant!r}")


def _deserialize_preview_row(row: sqlite3.Row) -> dict[str, object]:
    file_id = row["file_id"]
    content_revision = row["content_revision"]
    if not isinstance(content_revision, int) or content_revision < 1:
        raise TypeError(f"file_previews.content_revision invalid | file_id={file_id} value={content_revision!r}")
    updated_at = row["updated_at"]
    if not isinstance(updated_at, str):
        raise TypeError(f"file_previews.updated_at must be a string | file_id={file_id}")
    return {
        "file_id": file_id,
        "variant": row["variant"],
        "mime_type": row["mime_type"],
        "blob_id": row["blob_id"],
        "blob_seal": row["blob_seal"],
        "blob_seal_encryption_nonce": row["blob_seal_encryption_nonce"],
        "blob_seal_encryption_tag": row["blob_seal_encryption_tag"],
        "content_revision": content_revision,
        "updated_at": datetime.fromisoformat(updated_at),
    }


def upsert_file_preview(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    variant: str,
    mime_type: str,
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
    content_revision: int,
    updated_at: datetime,
) -> None:
    _require_preview_variant(variant)
    connection.execute(
        f"""
        INSERT INTO {FILE_PREVIEWS_TABLE} (
            file_id, variant, mime_type, blob_id, blob_seal, blob_seal_encryption_nonce,
            blob_seal_encryption_tag, content_revision, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id, variant) DO UPDATE SET
            mime_type = excluded.mime_type,
            blob_id = excluded.blob_id,
            blob_seal = excluded.blob_seal,
            blob_seal_encryption_nonce = excluded.blob_seal_encryption_nonce,
            blob_seal_encryption_tag = excluded.blob_seal_encryption_tag,
            content_revision = excluded.content_revision,
            updated_at = excluded.updated_at
        """,
        (
            file_id,
            variant,
            mime_type,
            blob_id,
            blob_seal,
            blob_seal_encryption_nonce,
            blob_seal_encryption_tag,
            content_revision,
            _serialize_datetime(updated_at),
        ),
    )


def delete_file_previews(connection: sqlite3.Connection, file_id: str) -> int:
    cursor = connection.execute(f"DELETE FROM {FILE_PREVIEWS_TABLE} WHERE file_id = ?", (file_id,))
    return cursor.rowcount


def fetch_file_preview(connection: sqlite3.Connection, file_id: str, variant: str) -> Optional[dict[str, object]]:
    _require_preview_variant(variant)
    row = connection.execute(
        f"SELECT * FROM {FILE_PREVIEWS_TABLE} WHERE file_id = ? AND variant = ?",
        (file_id, variant),
    ).fetchone()
    if row is None:
        return None
    return _deserialize_preview_row(row)


def fetch_all_file_previews(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(f"SELECT * FROM {FILE_PREVIEWS_TABLE} ORDER BY file_id ASC, variant ASC").fetchall()
    return [_deserialize_preview_row(row) for row in rows]


def update_file_preview_storage_fields(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    variant: str,
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
) -> None:
    """Rewrite preview ciphertext during encryption migrations without changing its revision."""
    _require_preview_variant(variant)
    cursor = connection.execute(
        f"""
        UPDATE {FILE_PREVIEWS_TABLE}
        SET blob_id = ?, blob_seal = ?, blob_seal_encryption_nonce = ?, blob_seal_encryption_tag = ?
        WHERE file_id = ? AND variant = ?
        """,
        (blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, file_id, variant),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(f"file preview rewrite expected one row | file_id={file_id} variant={variant}")



# --- A file's text for search (file_schema's FILE_TEXTS_TABLE) ------------------------------


def upsert_file_text(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
    filter_data: bytes,
    filter_encryption_nonce: Optional[bytes],
    filter_encryption_tag: Optional[bytes],
    is_cut: bool,
    content_revision: int,
    reader_version: int,
    filter_version: int,
    updated_at: datetime,
) -> None:
    if not isinstance(content_revision, int) or content_revision < 1:
        raise TypeError(f"file_texts.content_revision must be a positive integer | file_id={file_id}")
    for name, version in (("reader_version", reader_version), ("filter_version", filter_version)):
        if not isinstance(version, int) or version < 1:
            raise TypeError(f"file_texts.{name} must be a positive integer | file_id={file_id}")
    connection.execute(
        f"""
        INSERT INTO {FILE_TEXTS_TABLE} (
            file_id, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, filter_data,
            filter_encryption_nonce, filter_encryption_tag, is_cut, content_revision, reader_version,
            filter_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            blob_id = excluded.blob_id,
            blob_seal = excluded.blob_seal,
            blob_seal_encryption_nonce = excluded.blob_seal_encryption_nonce,
            blob_seal_encryption_tag = excluded.blob_seal_encryption_tag,
            filter_data = excluded.filter_data,
            filter_encryption_nonce = excluded.filter_encryption_nonce,
            filter_encryption_tag = excluded.filter_encryption_tag,
            is_cut = excluded.is_cut,
            content_revision = excluded.content_revision,
            reader_version = excluded.reader_version,
            filter_version = excluded.filter_version,
            updated_at = excluded.updated_at
        """,
        (
            file_id, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, filter_data,
            filter_encryption_nonce, filter_encryption_tag, int(is_cut), content_revision, reader_version, filter_version,
            _serialize_datetime(updated_at),
        ),
    )


def fetch_file_text(connection: sqlite3.Connection, file_id: str) -> Optional[dict[str, object]]:
    """A file's stored text (still encrypted), or None when it has none yet."""
    row = connection.execute(
        f"SELECT file_id, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, is_cut, content_revision, reader_version "
        f"FROM {FILE_TEXTS_TABLE} WHERE file_id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_all_file_text_filters(connection: sqlite3.Connection) -> list[dict[str, object]]:
    """Every stored file text's filter (still encrypted), cut flag and revision: what login loads."""
    rows = connection.execute(
        f"SELECT file_id, filter_data, filter_encryption_nonce, filter_encryption_tag, is_cut, content_revision, "
        f"reader_version, filter_version FROM {FILE_TEXTS_TABLE} ORDER BY file_id ASC"
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_all_file_texts(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(f"SELECT * FROM {FILE_TEXTS_TABLE} ORDER BY file_id ASC").fetchall()
    return [dict(row) for row in rows]


def update_file_text_storage_fields(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
    filter_data: bytes,
    filter_encryption_nonce: Optional[bytes],
    filter_encryption_tag: Optional[bytes],
) -> None:
    """Rewrite a file text's ciphertext during encryption migrations, nothing else."""
    cursor = connection.execute(
        f"""
        UPDATE {FILE_TEXTS_TABLE}
        SET blob_id = ?, blob_seal = ?, blob_seal_encryption_nonce = ?, blob_seal_encryption_tag = ?,
            filter_data = ?, filter_encryption_nonce = ?, filter_encryption_tag = ?
        WHERE file_id = ?
        """,
        (blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, filter_data, filter_encryption_nonce, filter_encryption_tag, file_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(f"file text rewrite expected one row | file_id={file_id}")



# --- A PDF's first page as a picture (file_schema's FILE_FIRST_PAGES_TABLE) ---------------------


def upsert_file_first_page(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    mime_type: str,
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
    content_revision: int,
    drawer_version: int,
    updated_at: datetime,
) -> None:
    """mime_type is "" for a PDF that could not be drawn (its blob is empty)."""
    if not isinstance(mime_type, str):
        raise TypeError(f"file_first_pages.mime_type must be a string | file_id={file_id}")
    for name, value in (("content_revision", content_revision), ("drawer_version", drawer_version)):
        if not isinstance(value, int) or value < 1:
            raise TypeError(f"file_first_pages.{name} must be a positive integer | file_id={file_id}")
    connection.execute(
        f"""
        INSERT INTO {FILE_FIRST_PAGES_TABLE} (
            file_id, mime_type, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag,
            content_revision, drawer_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            mime_type = excluded.mime_type,
            blob_id = excluded.blob_id,
            blob_seal = excluded.blob_seal,
            blob_seal_encryption_nonce = excluded.blob_seal_encryption_nonce,
            blob_seal_encryption_tag = excluded.blob_seal_encryption_tag,
            content_revision = excluded.content_revision,
            drawer_version = excluded.drawer_version,
            updated_at = excluded.updated_at
        """,
        (
            file_id, mime_type, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag,
            content_revision, drawer_version, _serialize_datetime(updated_at),
        ),
    )


def fetch_file_first_page(connection: sqlite3.Connection, file_id: str) -> Optional[dict[str, object]]:
    """A PDF's stored first page (its seal still encrypted), or None when it has none yet."""
    row = connection.execute(
        f"SELECT file_id, mime_type, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, "
        f"content_revision, drawer_version FROM {FILE_FIRST_PAGES_TABLE} WHERE file_id = ?",
        (file_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def fetch_first_page_versions(connection: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    """(content revision, drawer version) of every stored first page, by file: plaintext, no key needed."""
    rows = connection.execute(f"SELECT file_id, content_revision, drawer_version FROM {FILE_FIRST_PAGES_TABLE}").fetchall()
    return {str(row["file_id"]): (int(row["content_revision"]), int(row["drawer_version"])) for row in rows}


def fetch_all_file_first_pages(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows = connection.execute(f"SELECT * FROM {FILE_FIRST_PAGES_TABLE} ORDER BY file_id ASC").fetchall()
    return [dict(row) for row in rows]


def update_file_first_page_storage_fields(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    blob_id: str,
    blob_seal: bytes,
    blob_seal_encryption_nonce: Optional[bytes],
    blob_seal_encryption_tag: Optional[bytes],
) -> None:
    """Rewrite a first page's blob and seal during encryption migrations, nothing else."""
    cursor = connection.execute(
        f"""
        UPDATE {FILE_FIRST_PAGES_TABLE}
        SET blob_id = ?, blob_seal = ?, blob_seal_encryption_nonce = ?, blob_seal_encryption_tag = ?
        WHERE file_id = ?
        """,
        (blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, file_id),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(f"first page rewrite expected one row | file_id={file_id}")


def fetch_content_revisions(connection: sqlite3.Connection, file_ids: list[str]) -> dict[str, int]:
    """The content revision of each of these files still present, by id."""
    revisions: dict[str, int] = {}
    for file_id in file_ids:
        row = connection.execute(f"SELECT content_revision FROM {FILES_TABLE} WHERE id = ?", (file_id,)).fetchone()
        if row is not None:
            revisions[file_id] = int(row["content_revision"])
    return revisions
