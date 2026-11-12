"""A renamed vault's safety backups keep the name they were made under (backups are never
renamed), so the vault records its former names and lists, restores and trims those archives
in its own backups folder (approved 2026-11-11, docs/ready-to-build/unbounded-growth-audit.md, B3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.services import namespace_rename_worker
from app.services.backup_service import (
    create_timestamped_backup_for_paths,
    list_backups_in_directory,
    resolve_backup_directory_for_database,
    restore_own_backup,
    trim_safety_backups_for_database,
)
from app.services.vault_former_names import read_former_vault_names
from tests.unit.test_backup_service import _read_counter, _read_launch_profile_namespace, _write_counter, _write_launch_profile

_OLDEST_TIME = 1_700_000_000
_SECONDS_BETWEEN = 60


@pytest.fixture
def namespaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "namespaces"
    root.mkdir()
    monkeypatch.setattr(
        namespace_rename_worker, "resolve_namespace_directory", lambda *, namespace: root / namespace,
    )
    return root


def _database(namespaces: Path, vault: str) -> Path:
    return namespaces / vault / f"{vault}.metalist.db"


def _vault_with_backups(namespaces: Path, vault: str, count: int) -> list[str]:
    """A vault with count safety backups, oldest first; its counter is the backup's index."""
    database = _database(namespaces, vault)
    _write_launch_profile(database_path=database, namespace=vault, port=8010, https_port=None, mcp_port=8770)
    names = []
    for index in range(count):
        _write_counter(database, index)
        backup = create_timestamped_backup_for_paths(database, resolve_backup_directory_for_database(database))
        stamp = _OLDEST_TIME + index * _SECONDS_BETWEEN
        os.utime(resolve_backup_directory_for_database(database) / backup.filename, (stamp, stamp))
        names.append(backup.filename)
    return names


def _rename(source: str, target: str) -> None:
    namespace_rename_worker._rename_namespace_storage(source_namespace=source, target_namespace=target)


def test_a_rename_records_every_name_the_vault_had(namespaces: Path) -> None:
    _vault_with_backups(namespaces, "obsidian", 1)

    _rename("obsidian", "notes")
    assert read_former_vault_names(namespaces / "notes") == frozenset({"obsidian"})

    _rename("notes", "work")
    assert read_former_vault_names(namespaces / "work") == frozenset({"obsidian", "notes"})

    _rename("work", "obsidian")
    assert read_former_vault_names(namespaces / "obsidian") == frozenset({"notes", "work"})


def test_a_vault_never_renamed_has_no_former_names(namespaces: Path) -> None:
    _vault_with_backups(namespaces, "obsidian", 1)

    assert read_former_vault_names(namespaces / "obsidian") == frozenset()


def test_the_trim_counts_backups_made_under_a_former_name(namespaces: Path) -> None:
    old = _vault_with_backups(namespaces, "obsidian", 3)
    _rename("obsidian", "notes")
    database = _database(namespaces, "notes")
    new = create_timestamped_backup_for_paths(database, resolve_backup_directory_for_database(database))

    deleted = trim_safety_backups_for_database(database)

    assert [backup.filename for backup in deleted] == [old[0]]
    assert {backup.filename for backup in list_backups_in_directory(
        resolve_backup_directory_for_database(database), database_path=database,
    )} == {new.filename, old[1], old[2]}


def test_a_backup_made_under_a_former_name_restores_into_the_renamed_vault(namespaces: Path) -> None:
    old = _vault_with_backups(namespaces, "obsidian", 2)
    _rename("obsidian", "notes")
    database = _database(namespaces, "notes")
    _write_counter(database, 99)

    restore_own_backup(filename=old[0], database_path=database)

    assert _read_counter(database) == 0
    assert _read_launch_profile_namespace(database_path=database) == "notes"


def test_former_names_count_only_in_the_vaults_own_folder(namespaces: Path, tmp_path: Path) -> None:
    """Another vault may take the old name later; in a folder the user chose, its backups are its own."""
    _vault_with_backups(namespaces, "obsidian", 1)
    _rename("obsidian", "notes")
    database = _database(namespaces, "notes")
    chosen_folder = tmp_path / "chosen"
    old_name_database = tmp_path / "elsewhere" / "obsidian" / "obsidian.metalist.db"
    _write_counter(old_name_database, 1)
    create_timestamped_backup_for_paths(old_name_database, chosen_folder)

    assert list_backups_in_directory(chosen_folder, database_path=database) == []


def test_a_name_that_is_not_a_vault_name_is_refused(namespaces: Path) -> None:
    _vault_with_backups(namespaces, "obsidian", 1)
    _rename("obsidian", "notes")
    (namespaces / "notes" / "former-names.json").write_text('{"former_names": ["../escape"]}', encoding="utf-8")

    with pytest.raises(RuntimeError):
        read_former_vault_names(namespaces / "notes")
