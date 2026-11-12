"""A vault keeps its newest three safety backups (the maintainer, 2026-11-08): upgrades and
updates each made a full copy that nothing ever removed, 3.7 GB on one vault. Older copies
go only once a new backup checks out and the upgrade or update has succeeded."""

from __future__ import annotations

from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys

import pytest

import main as main_entrypoint
from app.services import update_backups
from app.db.version import CURRENT_DATABASE_VERSION
from app.services.backup_service import SAFETY_BACKUPS_KEPT, trim_safety_backups_for_database
from app.services.backup_service import back_up_before_passwordless_upgrade
from app.services.backup_service import trim_safety_backups_once_vault_is_current
from tests.unit.test_update_backups import _create_namespace

_OLDEST_TIME = 1_700_000_000
_SECONDS_BETWEEN = 60


def _vault(root: Path, namespace: str) -> Path:
    _create_namespace(root, namespace, encrypted=False).close()
    return root / namespace / f"{namespace}.metalist.db"


def _older_backups(database: Path, count: int) -> list[Path]:
    """count older backups, oldest first."""
    directory = database.parent / "backups"
    directory.mkdir(exist_ok=True)
    namespace = database.parent.name
    backups = []
    for index in range(count):
        backup = directory / f"{namespace}-2026010{index + 1}-000000-000000.metalist-backup.tar.gz"
        backup.write_bytes(f"older backup {index}".encode())
        os.utime(backup, (_OLDEST_TIME + index * _SECONDS_BETWEEN, _OLDEST_TIME + index * _SECONDS_BETWEEN))
        backups.append(backup)
    return backups


def _file_names(database: Path) -> set[str]:
    return {path.name for path in (database.parent / "backups").iterdir()}


def test_three_are_kept(tmp_path: Path) -> None:
    assert SAFETY_BACKUPS_KEPT == 3
    database = _vault(tmp_path, "work")
    older = _older_backups(database, 5)
    [new] = update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)
    kept_bytes = {path: path.read_bytes() for path in (new, older[3], older[4])}

    deleted = trim_safety_backups_for_database(database)

    assert {backup.filename for backup in deleted} == {older[0].name, older[1].name, older[2].name}
    assert _file_names(database) == {new.name, older[3].name, older[4].name}
    assert {path: path.read_bytes() for path in kept_bytes} == kept_bytes


def test_three_or_fewer_are_left_alone(tmp_path: Path) -> None:
    database = _vault(tmp_path, "work")
    older = _older_backups(database, 2)
    [new] = update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)

    assert trim_safety_backups_for_database(database) == []
    assert _file_names(database) == {new.name, older[0].name, older[1].name}


def test_a_vault_with_no_backups_folder_needs_nothing(tmp_path: Path) -> None:
    assert trim_safety_backups_for_database(_vault(tmp_path, "work")) == []


def test_only_this_vaults_backups_are_counted_or_removed(tmp_path: Path) -> None:
    database = _vault(tmp_path, "work")
    older = _older_backups(database, 4)
    [new] = update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)
    directory = database.parent / "backups"
    others = [
        directory / "other-20200101-000000-000000.metalist-backup.tar.gz",
        directory / f"{older[0].name}.partial",
        directory / "notes-to-self.txt",
    ]
    for other in others:
        other.write_bytes(b"not one of this vault's backups")
        os.utime(other, (_OLDEST_TIME, _OLDEST_TIME))

    trim_safety_backups_for_database(database)

    assert _file_names(database) == {new.name, older[2].name, older[3].name, *(other.name for other in others)}


def test_nothing_is_removed_when_the_newest_backup_does_not_check_out(tmp_path: Path) -> None:
    database = _vault(tmp_path, "work")
    older = _older_backups(database, 5)
    damaged = database.parent / "backups" / "work-20260201-000000-000000.metalist-backup.tar.gz"
    damaged.write_bytes(b"not an archive")
    names_before = _file_names(database)

    with pytest.raises(Exception, match="(?i)gzip|read|archive"):
        trim_safety_backups_for_database(database)

    assert _file_names(database) == names_before
    assert all(path.exists() for path in older)


def test_the_updaters_last_step_trims_every_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    databases = [_vault(tmp_path, "home"), _vault(tmp_path, "work")]
    for database in databases:
        _older_backups(database, 5)
    update_backups.backup_all_namespaces_for_update(namespaces_directory=tmp_path)
    monkeypatch.setattr(main_entrypoint, "resolve_namespaces_directory", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["metalist", "trim-safety-backups"])

    main_entrypoint.cli()

    assert [len(_file_names(database)) for database in databases] == [SAFETY_BACKUPS_KEPT, SAFETY_BACKUPS_KEPT]


def test_the_trim_command_takes_no_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["metalist", "trim-safety-backups", "work"])
    with pytest.raises(RuntimeError, match="Usage: metalist trim-safety-backups"):
        main_entrypoint.cli()


def _upgrade_to_current(database: Path) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(f"PRAGMA user_version = {CURRENT_DATABASE_VERSION}")
        connection.commit()


def test_a_passwordless_vault_keeps_three_once_its_startup_upgrade_succeeded(tmp_path: Path) -> None:
    """Approved 2026-11-11 (docs/ready-to-build/unbounded-growth-audit.md, B2): an upgrade at
    start, by uv, pip or a git pull, added a full copy each time and nothing removed one."""
    database = _vault(tmp_path, "work")
    older = _older_backups(database, 4)

    assert back_up_before_passwordless_upgrade(database) is True
    [new] = _file_names(database) - {path.name for path in older}
    _upgrade_to_current(database)
    deleted = trim_safety_backups_once_vault_is_current(database)

    assert {backup.filename for backup in deleted} == {older[0].name, older[1].name}
    assert _file_names(database) == {new, older[2].name, older[3].name}


def test_a_passwordless_vault_not_yet_upgraded_keeps_every_backup(tmp_path: Path) -> None:
    database = _vault(tmp_path, "work")
    older = _older_backups(database, 4)
    assert back_up_before_passwordless_upgrade(database) is True

    with pytest.raises(RuntimeError, match="has not upgraded"):
        trim_safety_backups_once_vault_is_current(database)

    assert len(_file_names(database)) == len(older) + 1


def test_a_current_passwordless_vault_makes_no_backup_so_start_trims_nothing(tmp_path: Path) -> None:
    database = _vault(tmp_path, "work")
    _upgrade_to_current(database)

    assert back_up_before_passwordless_upgrade(database) is False
