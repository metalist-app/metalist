"""Migration 16→17 (docs/ready-to-build/file-storage-per-file.md, section 9): every file leaves the
single files database for its own blob, and the old database goes only once all of them check out."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3

from cryptography.exceptions import InvalidTag
import pytest

from app.db import move_files_to_blobs as migration_step
from app.db.blob_store import (
    BlobSeal,
    BlobSealError,
    BlobStore,
    blob_store_for_database,
    resolve_file_catalog_path,
    resolve_legacy_file_database_path,
)
from app.db.legacy_file_schema import initialize_file_schema as initialize_legacy_file_schema
from app.db.migrations import _MIGRATIONS, run_database_migrations
from app.db.schema import initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION
from app.services.encryption import EncryptionService

_NOW = "2026-11-08T00:00:00+00:00"
_PREVIOUS_VERSION = 16
_PDF_BYTES = b"%PDF the report" + bytes(range(256)) * 400
_SCENE_BYTES = b'{"type":"excalidraw","elements":[]}'
_LIGHT_SVG = b"<svg>light</svg>"
_DARK_SVG = b"<svg>dark</svg>"
_TEXT_BYTES = "Rent is due on the first".encode()
_FILTER_BYTES = b"filter bits"


def _service() -> EncryptionService:
    service = EncryptionService()
    service.dek = bytes(range(32))
    return service


def _stored(service: EncryptionService | None, content: bytes) -> tuple[bytes, bytes | None, bytes | None]:
    if service is None:
        return content, None, None
    return service.encrypt_bytes_for_storage(content)


def _stored_text(service: EncryptionService | None, content: str) -> tuple[str, bytes | None, bytes | None]:
    if service is None:
        return content, None, None
    return service.encrypt_for_storage(content)


def _vault_at_previous_version(tmp_path: Path) -> Path:
    directory = tmp_path / "fixture"
    directory.mkdir()
    notes = directory / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        connection.execute(f"PRAGMA user_version = {_PREVIOUS_VERSION}")
        connection.commit()
    return notes


def _add_legacy_file(connection: sqlite3.Connection, service: EncryptionService | None, file_id: str, content: bytes) -> None:
    connection.execute(
        """
        INSERT INTO files (
            id, title, title_encryption_nonce, title_encryption_tag, metadata_json, metadata_encryption_nonce,
            metadata_encryption_tag, blob_data, blob_encryption_nonce, blob_encryption_tag, created_at, updated_at, content_revision
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (file_id, *_stored_text(service, f"{file_id}.bin"), *_stored_text(service, "{}"), *_stored(service, content), _NOW, _NOW, 3),
    )


def _legacy_files(notes: Path, service: EncryptionService | None) -> Path:
    path = resolve_legacy_file_database_path(notes)
    with closing(sqlite3.connect(path)) as connection:
        initialize_legacy_file_schema(connection)
        _add_legacy_file(connection, service, "report", _PDF_BYTES)
        _add_legacy_file(connection, service, "diagram", _SCENE_BYTES)
        for variant, svg in (("light", _LIGHT_SVG), ("dark", _DARK_SVG)):
            connection.execute(
                """
                INSERT INTO file_previews (
                    file_id, variant, mime_type, preview_data, preview_encryption_nonce, preview_encryption_tag, content_revision, updated_at
                ) VALUES ('diagram', ?, 'image/svg+xml', ?, ?, ?, 3, ?)
                """,
                (variant, *_stored(service, svg), _NOW),
            )
        connection.execute(
            """
            INSERT INTO file_texts (
                file_id, text_data, text_encryption_nonce, text_encryption_tag, filter_data, filter_encryption_nonce,
                filter_encryption_tag, is_cut, content_revision, reader_version, filter_version, updated_at
            ) VALUES ('report', ?, ?, ?, ?, ?, ?, 1, 3, 2, 4, ?)
            """,
            (*_stored(service, _TEXT_BYTES), *_stored(service, _FILTER_BYTES), _NOW),
        )
        connection.commit()
    return path


def _migrate(notes: Path, service: EncryptionService | None) -> tuple[int, ...]:
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            return run_database_migrations(
                connection=connection, encryption_enabled=service is not None, encryption_service=service,
            ).applied_versions


def _catalog(notes: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(resolve_file_catalog_path(notes))
    connection.row_factory = sqlite3.Row
    return connection


def _content(store: BlobStore, row: sqlite3.Row, service: EncryptionService | None) -> bytes:
    seal = row["blob_seal"]
    if service is not None:
        seal = service.decrypt_bytes_from_storage(seal, row["blob_seal_encryption_nonce"], row["blob_seal_encryption_tag"])
    return store.read_all(row["blob_id"], BlobSeal.from_bytes(seal))


@pytest.fixture(params=[False, True], ids=["no-password", "password"])
def service(request) -> EncryptionService | None:
    if request.param:
        return _service()
    return None


def test_this_is_the_current_version() -> None:
    assert CURRENT_DATABASE_VERSION == _PREVIOUS_VERSION + 1


def test_every_item_moves_and_keeps_what_it_was(tmp_path: Path, service) -> None:
    notes = _vault_at_previous_version(tmp_path)
    _legacy_files(notes, service)

    assert _migrate(notes, service) == (_PREVIOUS_VERSION + 1,)

    store = blob_store_for_database(notes)
    with closing(_catalog(notes)) as catalog:
        report = catalog.execute("SELECT * FROM files WHERE id='report'").fetchone()
        assert _content(store, report, service) == _PDF_BYTES
        assert report["content_revision"] == 3 and report["created_at"] == _NOW
        diagram = catalog.execute("SELECT * FROM files WHERE id='diagram'").fetchone()
        assert _content(store, diagram, service) == _SCENE_BYTES
        previews = {row["variant"]: row for row in catalog.execute("SELECT * FROM file_previews WHERE file_id='diagram'")}
        assert _content(store, previews["light"], service) == _LIGHT_SVG
        assert _content(store, previews["dark"], service) == _DARK_SVG
        assert previews["light"]["mime_type"] == "image/svg+xml" and previews["light"]["content_revision"] == 3
        text = catalog.execute("SELECT * FROM file_texts WHERE file_id='report'").fetchone()
        assert _content(store, text, service) == _TEXT_BYTES
        assert (text["is_cut"], text["content_revision"], text["reader_version"], text["filter_version"]) == (1, 3, 2, 4)
        filter_data = text["filter_data"]
        if service is not None:
            filter_data = service.decrypt_bytes_from_storage(filter_data, text["filter_encryption_nonce"], text["filter_encryption_tag"])
        assert filter_data == _FILTER_BYTES


def test_the_title_and_metadata_are_carried_over_as_they_were(tmp_path: Path, service) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, service)
    with closing(sqlite3.connect(legacy)) as connection:
        before = connection.execute("SELECT title, title_encryption_nonce, metadata_json FROM files WHERE id='report'").fetchone()

    _migrate(notes, service)

    with closing(_catalog(notes)) as catalog:
        after = catalog.execute("SELECT title, title_encryption_nonce, metadata_json FROM files WHERE id='report'").fetchone()
    assert tuple(after) == before


def test_the_old_database_is_gone_afterwards(tmp_path: Path, service) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, service)

    _migrate(notes, service)

    assert not legacy.exists()
    assert not Path(f"{legacy}-wal").exists() and not Path(f"{legacy}-shm").exists()


def test_a_vault_with_a_password_has_nothing_readable_on_disk(tmp_path: Path) -> None:
    service = _service()
    notes = _vault_at_previous_version(tmp_path)
    _legacy_files(notes, service)

    _migrate(notes, service)

    blobs = [path.read_bytes() for path in blob_store_for_database(notes).directory.glob("*/*.mlb")]
    assert len(blobs) == 5
    for blob in blobs:
        assert blob.startswith(b"ML\x01\x01")
        assert b"Rent" not in blob and b"%PDF" not in blob and b"<svg" not in blob


def test_a_vault_with_no_password_keeps_its_files_as_they_are(tmp_path: Path) -> None:
    notes = _vault_at_previous_version(tmp_path)
    _legacy_files(notes, None)

    _migrate(notes, None)

    blobs = {path.read_bytes() for path in blob_store_for_database(notes).directory.glob("*/*.mlb")}
    assert blobs == {_PDF_BYTES, _SCENE_BYTES, _LIGHT_SVG, _DARK_SVG, _TEXT_BYTES}


def test_a_vault_that_never_stored_a_file_gets_nothing_created(tmp_path: Path, service) -> None:
    notes = _vault_at_previous_version(tmp_path)

    assert _migrate(notes, service) == (_PREVIOUS_VERSION + 1,)

    assert not resolve_file_catalog_path(notes).parent.exists()


def test_running_after_it_finished_changes_nothing(tmp_path: Path, service) -> None:
    notes = _vault_at_previous_version(tmp_path)
    _legacy_files(notes, service)
    _migrate(notes, service)
    with closing(sqlite3.connect(notes)) as connection:
        connection.execute(f"PRAGMA user_version = {_PREVIOUS_VERSION}")
        connection.commit()
    before = sorted(path.name for path in blob_store_for_database(notes).directory.glob("*/*.mlb"))

    assert _migrate(notes, service) == (_PREVIOUS_VERSION + 1,)

    assert sorted(path.name for path in blob_store_for_database(notes).directory.glob("*/*.mlb")) == before


def _failing_after(real_write, successes: int):
    remaining = [successes]

    def write(store, content, *, is_encrypted):
        if remaining[0] == 0:
            raise OSError("injected crash")
        remaining[0] -= 1
        return real_write(store, content, is_encrypted=is_encrypted)

    return write


@pytest.mark.parametrize("successes", [0, 1, 2, 3, 4])
def test_a_crash_part_way_keeps_the_old_database_and_the_next_run_finishes(tmp_path: Path, service, monkeypatch, successes: int) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, service)
    real_write = BlobStore.write
    monkeypatch.setattr(BlobStore, "write", _failing_after(real_write, successes))

    with pytest.raises(OSError, match="injected crash"):
        _migrate(notes, service)

    assert legacy.exists()
    with closing(sqlite3.connect(notes)) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == _PREVIOUS_VERSION

    monkeypatch.setattr(BlobStore, "write", real_write)
    assert _migrate(notes, service) == (_PREVIOUS_VERSION + 1,)

    assert not legacy.exists()
    store = blob_store_for_database(notes)
    with closing(_catalog(notes)) as catalog:
        row = catalog.execute("SELECT * FROM files WHERE id='report'").fetchone()
        assert _content(store, row, service) == _PDF_BYTES
        assert catalog.execute("SELECT count(*) FROM file_previews").fetchone()[0] == 2
        assert catalog.execute("SELECT count(*) FROM file_texts").fetchone()[0] == 1


def test_a_blob_that_does_not_read_back_keeps_the_old_database(tmp_path: Path, service, monkeypatch) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, service)
    real_verify = BlobStore.verify

    def damage_then_verify(store, blob_id, seal):
        path = store.path_of(blob_id)
        data = bytearray(path.read_bytes())
        data[min(20, len(data) - 1)] ^= 1
        path.write_bytes(bytes(data))
        real_verify(store, blob_id, seal)

    monkeypatch.setattr(BlobStore, "verify", damage_then_verify)

    with pytest.raises((InvalidTag, BlobSealError)):
        _migrate(notes, service)

    assert legacy.exists()


def test_a_catalog_with_a_row_the_old_database_lacks_keeps_the_old_database(tmp_path: Path, service) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, service)
    _migrate_to_catalog_only(notes, service)
    with closing(sqlite3.connect(legacy)) as connection:
        connection.execute("DELETE FROM file_texts WHERE file_id='report'")
        connection.execute("DELETE FROM files WHERE id='report'")
        connection.commit()

    with pytest.raises(RuntimeError, match="different from the old files database"):
        _migrate(notes, service)

    assert legacy.exists()


def _migrate_to_catalog_only(notes: Path, service) -> None:
    """Everything moved, as a crash just before the old database is deleted leaves it."""
    legacy = resolve_legacy_file_database_path(notes)
    kept = legacy.read_bytes()
    _migrate(notes, service)
    legacy.write_bytes(kept)
    with closing(sqlite3.connect(notes)) as connection:
        connection.execute(f"PRAGMA user_version = {_PREVIOUS_VERSION}")
        connection.commit()


def test_a_crash_just_before_deleting_the_old_database_finishes_without_writing_again(tmp_path: Path, service) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, service)
    _migrate_to_catalog_only(notes, service)
    before = sorted(path.name for path in blob_store_for_database(notes).directory.glob("*/*.mlb"))

    assert _migrate(notes, service) == (_PREVIOUS_VERSION + 1,)

    assert not legacy.exists()
    assert sorted(path.name for path in blob_store_for_database(notes).directory.glob("*/*.mlb")) == before


def test_an_encrypted_file_cannot_move_without_the_key(tmp_path: Path) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, _service())

    with pytest.raises(RuntimeError, match="requires the vault's key"):
        _migrate(notes, None)

    assert legacy.exists()


def test_the_wrong_key_keeps_the_old_database(tmp_path: Path) -> None:
    notes = _vault_at_previous_version(tmp_path)
    legacy = _legacy_files(notes, _service())
    wrong = EncryptionService()
    wrong.dek = os.urandom(32)

    with pytest.raises(InvalidTag):
        _migrate(notes, wrong)

    assert legacy.exists()


def test_the_step_is_registered_after_model_timings() -> None:
    assert _MIGRATIONS[_PREVIOUS_VERSION] is migration_step.move_files_to_blobs
