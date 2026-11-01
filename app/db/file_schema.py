"""SQLite schema helpers for encrypted file storage."""

from __future__ import annotations

from sqlite3 import Connection

FILES_TABLE = "files"
FILE_PREVIEWS_TABLE = "file_previews"
FILE_PREVIEW_VARIANTS = ("light", "dark")
FILE_TEXTS_TABLE = "file_texts"
FILE_TEXTS_COLUMNS = (
    "file_id", "text_data", "text_encryption_nonce", "text_encryption_tag", "filter_data",
    "filter_encryption_nonce", "filter_encryption_tag", "is_cut", "content_revision", "updated_at",
)

_CREATE_FILES_TABLE = f"""
CREATE TABLE IF NOT EXISTS {FILES_TABLE} (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_encryption_nonce BLOB,
    title_encryption_tag BLOB,
    metadata_json TEXT NOT NULL,
    metadata_encryption_nonce BLOB,
    metadata_encryption_tag BLOB,
    blob_data BLOB NOT NULL,
    blob_encryption_nonce BLOB,
    blob_encryption_tag BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    content_revision INTEGER NOT NULL DEFAULT 1
);
"""

# Rendered previews for files edited inside MetaList (Excalidraw diagrams).
# One row per theme variant; content_revision records which file revision was rendered.
_CREATE_FILE_PREVIEWS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {FILE_PREVIEWS_TABLE} (
    file_id TEXT NOT NULL REFERENCES {FILES_TABLE}(id) ON DELETE CASCADE,
    variant TEXT NOT NULL CHECK (variant IN ('light', 'dark')),
    mime_type TEXT NOT NULL,
    preview_data BLOB NOT NULL,
    preview_encryption_nonce BLOB,
    preview_encryption_tag BLOB,
    content_revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (file_id, variant)
);
"""


# A file's text, for search only (docs/ready-to-build/folder-import-and-file-previews.md,
# "Searchable file text"): the text (UTF-8, encrypted as the file is) and a bloom filter of its
# four-letter pieces (encrypted too: it tells whether a file holds a word). is_cut: the text
# stops at the cap. content_revision: the file revision it was read from. A file with no text
# (a scan, a damaged PDF) has a row with empty text, so it is not read again.
_CREATE_FILE_TEXTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {FILE_TEXTS_TABLE} (
    file_id TEXT PRIMARY KEY REFERENCES {FILES_TABLE}(id) ON DELETE CASCADE,
    text_data BLOB NOT NULL,
    text_encryption_nonce BLOB,
    text_encryption_tag BLOB,
    filter_data BLOB NOT NULL,
    filter_encryption_nonce BLOB,
    filter_encryption_tag BLOB,
    is_cut INTEGER NOT NULL CHECK (is_cut IN (0, 1)),
    content_revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def create_file_texts_table(connection: Connection) -> None:
    connection.execute(_CREATE_FILE_TEXTS_TABLE)


def _add_content_revision_column_if_missing(connection: Connection) -> None:
    """Upgrade live file databases created before in-place file updates existed."""
    column_names = {row[1] for row in connection.execute(f"PRAGMA table_info({FILES_TABLE})").fetchall()}
    assert "id" in column_names, "files table must exist before its columns are upgraded"
    if "content_revision" in column_names:
        return
    connection.execute(f"ALTER TABLE {FILES_TABLE} ADD COLUMN content_revision INTEGER NOT NULL DEFAULT 1")


def initialize_file_schema(connection: Connection) -> None:
    connection.execute(_CREATE_FILES_TABLE)
    _add_content_revision_column_if_missing(connection)
    connection.execute(_CREATE_FILE_PREVIEWS_TABLE)
    create_file_texts_table(connection)
