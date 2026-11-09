"""Migration 16→17: a vault's files leave its single `<vault>.metalist.files.db` for one blob each
plus `files/catalog.db` (docs/design/file-storage.md, section 9).

Every item is written as a blob and committed to the catalog one at a time, so a crash resumes
where it stopped. Once all are in, every blob is read back against its seal and the catalog is
compared with the old database; only then is the old database deleted. It goes last: a vault with
one still has all its files in it, and with none the move is finished, so the step is idempotent.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from app.db.blob_store import BlobSeal, BlobStore, blob_store_for_database, resolve_file_catalog_path, resolve_legacy_file_database_path
from app.db.file_schema import FILE_PREVIEWS_TABLE, FILE_TEXTS_TABLE, FILES_TABLE, initialize_file_schema
from app.services.encryption import EncryptionService

# PRAGMA database_list rows are (seq, name, file).
_DATABASE_LIST_FILE_COLUMN = 2
_LEGACY_SIDECAR_SUFFIXES = ("", "-wal", "-shm")


def _plaintext(*, encryption_service: EncryptionService | None, value: bytes, nonce: bytes | None, tag: bytes | None) -> bytes:
    if nonce is None and tag is None:
        return value
    if encryption_service is None:
        raise RuntimeError("Moving an encrypted file to its own blob requires the vault's key")
    return encryption_service.decrypt_bytes_from_storage(value, nonce, tag)


class _FileMove:
    def __init__(
        self, *, legacy: sqlite3.Connection, catalog: sqlite3.Connection, store: BlobStore, encryption_enabled: bool, encryption_service: EncryptionService | None,
    ) -> None:
        self._legacy = legacy
        self._catalog = catalog
        self._store = store
        self._encryption_enabled = encryption_enabled
        self._encryption_service = encryption_service
        self.moved_count = 0

    def _blob_columns(self, *, value: bytes, nonce: bytes | None, tag: bytes | None) -> tuple[str, bytes, bytes | None, bytes | None]:
        """The content written as a blob: its ID, then its seal as the catalog stores it."""
        content = _plaintext(encryption_service=self._encryption_service, value=value, nonce=nonce, tag=tag)
        stored = self._store.write(content, is_encrypted=self._encryption_enabled)
        seal = stored.seal.to_bytes()
        if not self._encryption_enabled:
            return stored.blob_id, seal, None, None
        if self._encryption_service is None:
            raise RuntimeError("Moving files in a vault with a password requires the vault's key")
        return (stored.blob_id, *self._encryption_service.encrypt_bytes_for_storage(seal))

    def _is_moved(self, table: str, where: str, key: tuple[str, ...]) -> bool:
        return self._catalog.execute(f"SELECT 1 FROM {table} WHERE {where}", key).fetchone() is not None

    def move_files(self) -> None:
        for (file_id,) in self._legacy.execute(f"SELECT id FROM {FILES_TABLE}").fetchall():
            if self._is_moved(FILES_TABLE, "id = ?", (file_id,)):
                continue
            row = self._legacy.execute(f"SELECT * FROM {FILES_TABLE} WHERE id = ?", (file_id,)).fetchone()
            blob_columns = self._blob_columns(value=row["blob_data"], nonce=row["blob_encryption_nonce"], tag=row["blob_encryption_tag"])
            self._catalog.execute(
                f"""
                INSERT INTO {FILES_TABLE} (
                    id, title, title_encryption_nonce, title_encryption_tag, metadata_json, metadata_encryption_nonce,
                    metadata_encryption_tag, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag,
                    created_at, updated_at, content_revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id, row["title"], row["title_encryption_nonce"], row["title_encryption_tag"], row["metadata_json"],
                    row["metadata_encryption_nonce"], row["metadata_encryption_tag"], *blob_columns,
                    row["created_at"], row["updated_at"], row["content_revision"],
                ),
            )
            self._catalog.commit()
            self.moved_count += 1

    def move_previews(self) -> None:
        keys = self._legacy.execute(f"SELECT file_id, variant FROM {FILE_PREVIEWS_TABLE}").fetchall()
        for file_id, variant in keys:
            if self._is_moved(FILE_PREVIEWS_TABLE, "file_id = ? AND variant = ?", (file_id, variant)):
                continue
            row = self._legacy.execute(
                f"SELECT * FROM {FILE_PREVIEWS_TABLE} WHERE file_id = ? AND variant = ?", (file_id, variant),
            ).fetchone()
            blob_columns = self._blob_columns(
                value=row["preview_data"], nonce=row["preview_encryption_nonce"], tag=row["preview_encryption_tag"],
            )
            self._catalog.execute(
                f"""
                INSERT INTO {FILE_PREVIEWS_TABLE} (
                    file_id, variant, mime_type, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag,
                    content_revision, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (file_id, variant, row["mime_type"], *blob_columns, row["content_revision"], row["updated_at"]),
            )
            self._catalog.commit()
            self.moved_count += 1

    def move_texts(self) -> None:
        for (file_id,) in self._legacy.execute(f"SELECT file_id FROM {FILE_TEXTS_TABLE}").fetchall():
            if self._is_moved(FILE_TEXTS_TABLE, "file_id = ?", (file_id,)):
                continue
            row = self._legacy.execute(f"SELECT * FROM {FILE_TEXTS_TABLE} WHERE file_id = ?", (file_id,)).fetchone()
            blob_columns = self._blob_columns(value=row["text_data"], nonce=row["text_encryption_nonce"], tag=row["text_encryption_tag"])
            self._catalog.execute(
                f"""
                INSERT INTO {FILE_TEXTS_TABLE} (
                    file_id, blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag, filter_data,
                    filter_encryption_nonce, filter_encryption_tag, is_cut, content_revision, reader_version, filter_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    file_id, *blob_columns, row["filter_data"], row["filter_encryption_nonce"], row["filter_encryption_tag"],
                    row["is_cut"], row["content_revision"], row["reader_version"], row["filter_version"], row["updated_at"],
                ),
            )
            self._catalog.commit()
            self.moved_count += 1

    def require_everything_moved(self) -> None:
        """Every item of the old database is in the catalog, nothing else is, and every blob reads back."""
        for table, key_columns in ((FILES_TABLE, "id"), (FILE_PREVIEWS_TABLE, "file_id, variant"), (FILE_TEXTS_TABLE, "file_id")):
            legacy_keys = {tuple(row) for row in self._legacy.execute(f"SELECT {key_columns} FROM {table}").fetchall()}
            catalog_keys = {tuple(row) for row in self._catalog.execute(f"SELECT {key_columns} FROM {table}").fetchall()}
            if legacy_keys != catalog_keys:
                raise RuntimeError(
                    f"Database migration 16→17 left {table} different from the old files database: "
                    f"{len(legacy_keys - catalog_keys)} missing, {len(catalog_keys - legacy_keys)} unexpected"
                )
            for row in self._catalog.execute(f"SELECT blob_id, blob_seal, blob_seal_encryption_nonce, blob_seal_encryption_tag FROM {table}").fetchall():
                seal = _plaintext(
                    encryption_service=self._encryption_service, value=row["blob_seal"],
                    nonce=row["blob_seal_encryption_nonce"], tag=row["blob_seal_encryption_tag"],
                )
                self._store.verify(row["blob_id"], BlobSeal.from_bytes(seal))


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def move_files_to_blobs(
    *,
    connection: sqlite3.Connection,
    encryption_enabled: bool,
    encryption_service: EncryptionService | None,
) -> int:
    database = connection.execute("PRAGMA database_list").fetchone()[_DATABASE_LIST_FILE_COLUMN]
    # An in-memory notes database's catalog is current from the start.
    if not database:
        return 0
    notes = Path(database)
    legacy_path = resolve_legacy_file_database_path(notes)
    # A vault that never stored a file has none, and one that has moved them no longer does.
    if not legacy_path.exists():
        return 0
    catalog_path = resolve_file_catalog_path(notes)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(_connect(legacy_path)) as legacy, closing(_connect(catalog_path)) as catalog:
        catalog.execute("PRAGMA foreign_keys = ON")
        catalog.execute("PRAGMA journal_mode=WAL")
        catalog.execute("PRAGMA secure_delete=ON")
        # The old database is deleted on the strength of these commits.
        catalog.execute("PRAGMA synchronous=FULL")
        initialize_file_schema(catalog)
        catalog.commit()
        move = _FileMove(
            legacy=legacy, catalog=catalog, store=blob_store_for_database(notes),
            encryption_enabled=encryption_enabled, encryption_service=encryption_service,
        )
        move.move_files()
        move.move_previews()
        move.move_texts()
        move.require_everything_moved()
        catalog.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    for suffix in _LEGACY_SIDECAR_SUFFIXES:
        Path(f"{legacy_path}{suffix}").unlink(missing_ok=True)
    return move.moved_count
