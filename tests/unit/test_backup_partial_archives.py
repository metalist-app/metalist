"""A backup is written to <name>.partial, fsynced, then hard-linked to its name, which fails
if that name exists (docs/security/README.md, "Backups"; agreed 2026-10-27, publication by
hard link approved 2026-10-29). A crash mid-write never leaves a truncated archive under a
backup's name, so Restore never offers one and pruning never counts one; the next backup
removes the leftover .partial."""

from __future__ import annotations

import sqlite3
import tarfile
from pathlib import Path

import pytest

from app.services import backup_service
from app.services.backup_service import create_timestamped_backup_for_paths, delete_partial_archives, list_backups_in_directory


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "vault" / "default.metalist.db"
    database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE notes (id TEXT)")
    return database


def test_a_backup_leaves_only_its_archive(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    backup = create_timestamped_backup_for_paths(_database(tmp_path), folder)
    assert sorted(path.name for path in folder.iterdir()) == [backup.filename]


def test_a_failure_mid_write_leaves_no_backup_and_the_next_backup_cleans_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "Backups"
    database = _database(tmp_path)
    original_add = tarfile.TarFile.add

    # The archive is written with arcname= each time: the manifest goes in, then the disk fills.
    def crash_after_manifest(self, name, **options):
        if options["arcname"] != "manifest.json":
            raise OSError("disk full")
        return original_add(self, name, **options)

    with monkeypatch.context() as patch:
        patch.setattr(tarfile.TarFile, "add", crash_after_manifest)
        with pytest.raises(OSError, match="disk full"):
            create_timestamped_backup_for_paths(database, folder)
    left = [path.name for path in folder.iterdir()]
    assert len(left) == 1 and left[0].endswith(".metalist-backup.tar.gz.partial"), left
    assert list_backups_in_directory(folder, database_path=database) == []

    backup = create_timestamped_backup_for_paths(database, folder)
    assert sorted(path.name for path in folder.iterdir()) == [backup.filename]


def test_another_vaults_partial_is_left_alone(tmp_path: Path) -> None:
    folder = tmp_path / "Backups"
    folder.mkdir()
    other = folder / "work-20261029-120000-000000.metalist-backup.tar.gz.partial"
    other.write_bytes(b"half")
    create_timestamped_backup_for_paths(_database(tmp_path), folder)
    assert other.exists()


def test_only_partial_files_can_be_removed_this_way(tmp_path: Path) -> None:
    backup = tmp_path / "default-20261029-120000-000000.metalist-backup.tar.gz"
    backup.write_bytes(b"a real backup")
    with pytest.raises(AssertionError):
        delete_partial_archives([backup])
    assert backup.exists()


def test_publishing_never_overwrites_an_existing_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "Backups"
    database = _database(tmp_path)
    first = create_timestamped_backup_for_paths(database, folder)
    before = (folder / first.filename).read_bytes()
    monkeypatch.setattr(backup_service, "_format_archive_backup_filename", lambda *, namespace, now_utc: first.filename)
    with pytest.raises(FileExistsError):
        create_timestamped_backup_for_paths(database, folder)
    assert (folder / first.filename).read_bytes() == before
