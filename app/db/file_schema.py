"""The catalog of a vault's stored files: `<vault>/files/catalog.db`, everything about each item
except its bytes (docs/ready-to-build/file-storage-per-file.md, section 3). The bytes are blobs
(blob_store.py), named by blob_id. blob_seal holds a blob's key, real size and checksum, encrypted
like the row's other fields while the vault has a password."""

from __future__ import annotations

from sqlite3 import Connection

FILES_TABLE = "files"
FILE_PREVIEWS_TABLE = "file_previews"
FILE_PREVIEW_VARIANTS = ("light", "dark")
FILE_TEXTS_TABLE = "file_texts"
# Every table holds one blob per row under these columns.
BLOB_TABLES = (FILES_TABLE, FILE_PREVIEWS_TABLE, FILE_TEXTS_TABLE)

_CREATE_FILES_TABLE = f"""
CREATE TABLE IF NOT EXISTS {FILES_TABLE} (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_encryption_nonce BLOB,
    title_encryption_tag BLOB,
    metadata_json TEXT NOT NULL,
    metadata_encryption_nonce BLOB,
    metadata_encryption_tag BLOB,
    blob_id TEXT NOT NULL UNIQUE,
    blob_seal BLOB NOT NULL,
    blob_seal_encryption_nonce BLOB,
    blob_seal_encryption_tag BLOB,
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
    blob_id TEXT NOT NULL UNIQUE,
    blob_seal BLOB NOT NULL,
    blob_seal_encryption_nonce BLOB,
    blob_seal_encryption_tag BLOB,
    content_revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (file_id, variant)
);
"""

# A file's text, for search only (docs/ready-to-build/folder-import-and-file-previews.md,
# "Searchable file text"): the text is a blob, because it grows with what is inside the file. The
# bloom filter of its four-letter pieces stays here, encrypted, because login loads them all.
# is_cut: the text stops at the cap. content_revision: the file revision it was read from. A file
# with no text (a scan, a damaged PDF) has a row with an empty blob, so it is not read again.
_CREATE_FILE_TEXTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {FILE_TEXTS_TABLE} (
    file_id TEXT PRIMARY KEY REFERENCES {FILES_TABLE}(id) ON DELETE CASCADE,
    blob_id TEXT NOT NULL UNIQUE,
    blob_seal BLOB NOT NULL,
    blob_seal_encryption_nonce BLOB,
    blob_seal_encryption_tag BLOB,
    filter_data BLOB NOT NULL,
    filter_encryption_nonce BLOB,
    filter_encryption_tag BLOB,
    is_cut INTEGER NOT NULL CHECK (is_cut IN (0, 1)),
    content_revision INTEGER NOT NULL,
    reader_version INTEGER NOT NULL,
    filter_version INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def initialize_file_schema(connection: Connection) -> None:
    connection.execute(_CREATE_FILES_TABLE)
    connection.execute(_CREATE_FILE_PREVIEWS_TABLE)
    connection.execute(_CREATE_FILE_TEXTS_TABLE)
