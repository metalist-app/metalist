from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile

import pytest

from app.db.blob_store import StoredBlob, blob_store_for_database, resolve_file_catalog_path
from app.db.file_schema import initialize_file_schema
from app.services import backup_service, update_backups
from app.services.backup_service import restore_backup_to_paths


def _create_namespace(root: Path, namespace: str, *, encrypted: bool) -> sqlite3.Connection:
    directory = root / namespace
    directory.mkdir(parents=True)
    connection = sqlite3.connect(directory / f"{namespace}.metalist.db")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE app_settings (id INTEGER PRIMARY KEY, encryption_enabled INTEGER, vault_metadata BLOB)")
    connection.execute("INSERT INTO app_settings VALUES (1, ?, ?)", (int(encrypted), b"retained vault metadata"))
    connection.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, content BLOB, nonce BLOB, tag BLOB)")
    connection.execute("INSERT INTO notes VALUES ('latest', ?, ?, ?)", (b"saved payload", b"nonce", b"tag"))
    connection.execute("PRAGMA user_version=7")
    connection.commit()
    return connection


def _attach_file(database: Path, *, file_id: str, content: bytes) -> StoredBlob:
    """A file in today's layout: a row in files/catalog.db naming one blob."""
    catalog = resolve_file_catalog_path(database)
    catalog.parent.mkdir(exist_ok=True)
    stored = blob_store_for_database(database).write(content, is_encrypted=False)
    with closing(sqlite3.connect(catalog)) as connection:
        initialize_file_schema(connection)
        connection.execute(
            "INSERT INTO files (id, title, metadata_json, blob_id, blob_seal, created_at, updated_at) VALUES (?, 't', '{}', ?, ?, 'now', 'now')",
            (file_id, stored.blob_id, stored.seal.to_bytes()),
        )
        connection.commit()
    return stored


def test_restoring_a_pre_update_backup_brings_back_the_vaults_attachments(tmp_path: Path) -> None:
    _create_namespace(tmp_path, "work", encrypted=False).close()
    database = tmp_path / "work" / "work.metalist.db"
    stored = _attach_file(database, file_id="report", content=b"attachment bytes")

    [archive] = update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)
    restore_backup_to_paths(archive, database)

    assert blob_store_for_database(database).contains(stored.blob_id)
    assert blob_store_for_database(database).read_all(stored.blob_id, stored.seal) == b"attachment bytes"
    with closing(sqlite3.connect(resolve_file_catalog_path(database))) as catalog:
        assert [row[0] for row in catalog.execute("SELECT id FROM files")] == ["report"]


def test_a_pre_update_backup_holds_the_same_members_as_an_ordinary_backup(tmp_path: Path) -> None:
    namespaces = tmp_path / "namespaces"
    _create_namespace(namespaces, "work", encrypted=False).close()
    database = namespaces / "work" / "work.metalist.db"
    stored = _attach_file(database, file_id="report", content=b"attachment bytes")
    ordinary = backup_service.create_timestamped_backup_for_paths(database, tmp_path / "ordinary")

    [archive] = update_backups.backup_all_namespaces_for_update(namespaces_directory=namespaces)

    with tarfile.open(archive, "r:gz") as handle:
        update_names = set(handle.getnames())
    with tarfile.open(tmp_path / "ordinary" / ordinary.filename, "r:gz") as handle:
        ordinary_names = set(handle.getnames())
    assert update_names == ordinary_names
    assert f"files/blobs/{stored.blob_id[:2]}/{stored.blob_id}.mlb" in update_names


def test_a_pre_update_backup_is_published_by_hard_link_from_its_partial_file(tmp_path: Path, monkeypatch) -> None:
    _create_namespace(tmp_path, "work", encrypted=False).close()
    links: list[tuple[str, str]] = []
    real_link = os.link

    def _recording_link(source, target) -> None:
        links.append((Path(source).name, Path(target).name))
        real_link(source, target)

    monkeypatch.setattr(os, "link", _recording_link)

    [archive] = update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)

    assert links == [(f"{archive.name}.partial", archive.name)]
    assert sorted(path.name for path in archive.parent.iterdir()) == [archive.name]


def test_update_imports_do_not_initialize_namespace_runtime() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import sys; import app.services.self_update; assert 'app.config' not in sys.modules; assert 'app.main' not in sys.modules"],
        cwd=Path(__file__).resolve().parents[2], capture_output=True, encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr


def test_all_namespaces_include_wal_data_settings_files_sounds_and_legacy_sidecar(tmp_path: Path) -> None:
    namespaces = tmp_path / "namespaces"
    plain = _create_namespace(namespaces, "default", encrypted=False)
    locked = _create_namespace(namespaces, "locked", encrypted=True)
    try:
        # Neither namespace has a saved launch profile or a password/DEK in process memory.
        locked.execute("UPDATE notes SET content = ? WHERE id = 'latest'", (b"opaque encrypted content from WAL",))
        locked.commit()
        directory = namespaces / "locked"
        with sqlite3.connect(directory / "locked.metalist.files.db") as files:
            files.execute("CREATE TABLE files (payload BLOB)")
            files.execute("INSERT INTO files VALUES (?)", (b"encrypted attachment",))
            files.execute("CREATE TABLE sounds (payload BLOB)")
            files.execute("INSERT INTO sounds VALUES (?)", (b"encrypted sound",))
        with sqlite3.connect(directory / "locked.metalist.search-history.db") as history:
            history.execute("CREATE TABLE history (payload BLOB)")
            history.execute("INSERT INTO history VALUES (?)", (b"old history",))
        old_backup = directory / "backups" / "locked-20260801-000000-000000.metalist-backup.tar.gz"
        old_backup.parent.mkdir()
        with old_backup.open("xb") as handle:
            handle.write(b"immutable historical backup")
        old_backup_bytes = old_backup.read_bytes()
        history_bytes = (directory / "locked.metalist.search-history.db").read_bytes()

        archives = update_backups.backup_all_namespaces_for_update(namespaces_directory=namespaces)

        assert len(archives) == 2
        assert {archive.parent.parent.name for archive in archives} == {"default", "locked"}
        assert all(archive.is_absolute() and archive.parent.name == "backups" for archive in archives)
        assert old_backup.read_bytes() == old_backup_bytes
        assert (directory / "locked.metalist.search-history.db").read_bytes() == history_bytes
        # The WAL is folded into the live database before the copy (as for every backup): same data.
        with closing(sqlite3.connect(directory / "locked.metalist.db")) as live:
            assert live.execute("SELECT content FROM notes").fetchall() == [(b"opaque encrypted content from WAL",)]
        archive_path = next(path for path in archives if path.parent.parent.name == "locked")
        with tarfile.open(archive_path, "r:gz") as archive:
            manifest_stream = archive.extractfile("manifest.json")
            assert manifest_stream is not None
            manifest = json.load(manifest_stream)
            assert manifest["encryption_enabled"] is True
            # A leftover search-history database is ignored, as by every backup since 2 → 3.
            assert {entry["database_role"] for entry in manifest["files"]} == {"notes", "files"}
            for entry in manifest["files"]:
                stream = archive.extractfile(entry["archive_name"])
                assert stream is not None
                payload = stream.read()
                assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
                assert len(payload) == entry["size_bytes"]
        archive_bytes = archive_path.read_bytes()
        restored = tmp_path / "restore" / "locked.metalist.db"
        restore_backup_to_paths(archive_path, restored)
        with sqlite3.connect(restored) as notes:
            assert notes.execute("SELECT content, nonce, tag FROM notes").fetchone() == (b"opaque encrypted content from WAL", b"nonce", b"tag")
            assert notes.execute("SELECT vault_metadata FROM app_settings").fetchone() == (b"retained vault metadata",)
            assert notes.execute("PRAGMA user_version").fetchone() == (7,)
        with sqlite3.connect(restored.with_name("locked.metalist.files.db")) as files:
            assert files.execute("SELECT payload FROM files").fetchone() == (b"encrypted attachment",)
            assert files.execute("SELECT payload FROM sounds").fetchone() == (b"encrypted sound",)
        assert archive_path.read_bytes() == archive_bytes
    finally:
        locked.close()
        plain.close()


def test_backup_collision_leaves_existing_archive_untouched(tmp_path: Path, monkeypatch) -> None:
    connection = _create_namespace(tmp_path, "default", encrypted=False)
    connection.close()

    class FixedDatetime:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2026, 9, 11, tzinfo=timezone.utc)

    monkeypatch.setattr(backup_service, "datetime", FixedDatetime)
    archive = tmp_path / "default" / "backups" / "default-20260911-000000-000000.metalist-backup.tar.gz"
    archive.parent.mkdir()
    with archive.open("xb") as handle:
        handle.write(b"original backup")
    with pytest.raises(FileExistsError, match="already exists"):
        update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)
    assert archive.read_bytes() == b"original backup"


def test_legacy_settings_are_backed_up_without_schema_changes(tmp_path: Path) -> None:
    connection = _create_namespace(tmp_path, "legacy", encrypted=True)
    connection.execute("ALTER TABLE app_settings RENAME TO settings")
    connection.execute("UPDATE settings SET id = 9")
    connection.commit()
    connection.close()
    database = tmp_path / "legacy" / "legacy.metalist.db"
    original_bytes = database.read_bytes()

    archives = update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)

    assert database.read_bytes() == original_bytes
    with tarfile.open(archives[0], "r:gz") as archive:
        stream = archive.extractfile("manifest.json")
        assert stream is not None
        with stream:
            assert json.load(stream)["encryption_enabled"] is True


def test_checksum_verification_failure_is_fatal(tmp_path: Path, monkeypatch) -> None:
    connection = _create_namespace(tmp_path, "default", encrypted=False)
    connection.close()
    monkeypatch.setattr(backup_service, "_sha256_for_file", lambda _path: "0" * 64)
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)


def test_corrupt_database_prevents_backup_success(tmp_path: Path) -> None:
    directory = tmp_path / "broken"
    directory.mkdir()
    with (directory / "broken.metalist.db").open("xb") as source:
        source.write(b"not a SQLite database")
    with pytest.raises(sqlite3.DatabaseError):
        update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)


def test_missing_namespace_database_is_not_silently_skipped(tmp_path: Path) -> None:
    (tmp_path / "missing").mkdir()
    with pytest.raises(RuntimeError, match="database is missing"):
        update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)


def test_no_saved_namespaces_needs_no_backups(tmp_path: Path) -> None:
    assert update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path / "absent") == ()
