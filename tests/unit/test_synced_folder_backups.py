"""Backups to synced folders (docs/ui/command-palette.md, `Back Up Now…`; agreed
2026-10-27): Back Up Now suggests a MetaList Backups folder in each synced folder found, and
a backup of a vault without a password into one is refused until the person agrees, once
per folder and vault."""

from __future__ import annotations

from pathlib import Path

import pytest

import app.api.routes.backups as backups_route
from app.services.synced_folders import find_synced_folders, provider_syncing, suggested_backup_folders


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    for folder in (
        "Library/CloudStorage/Dropbox",
        "Library/CloudStorage/GoogleDrive-ada@example.org/My Drive",
        "Library/CloudStorage/OneDrive-Personal",
        "Library/Mobile Documents/com~apple~CloudDocs",
        "Documents",
    ):
        (home / folder).mkdir(parents=True)
    return home


def test_backup_settings_suggest_each_synced_folder(tmp_path: Path) -> None:
    home = _home(tmp_path)
    assert [(folder.label, folder.suggestion) for folder in find_synced_folders(home)] == [
        ("Dropbox › MetaList Backups", home / "Library/CloudStorage/Dropbox/MetaList Backups"),
        ("Google Drive › My Drive › MetaList Backups", home / "Library/CloudStorage/GoogleDrive-ada@example.org/My Drive/MetaList Backups"),
        ("OneDrive › MetaList Backups", home / "Library/CloudStorage/OneDrive-Personal/MetaList Backups"),
        ("iCloud Drive › MetaList Backups", home / "Library/Mobile Documents/com~apple~CloudDocs/MetaList Backups"),
    ]


def test_no_synced_folders_means_no_suggestions(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    assert find_synced_folders(home) == []
    assert suggested_backup_folders(home) == []


def test_downloads_comes_first_and_only_folders_that_exist_are_offered(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    (home / "Dropbox").mkdir()
    assert [(folder.label, folder.path) for folder in suggested_backup_folders(home)] == [
        ("Downloads", home / "Downloads"),
        ("Dropbox › MetaList Backups", home / "Dropbox" / "MetaList Backups"),
    ]


def test_a_folder_inside_a_synced_folder_is_synced(tmp_path: Path) -> None:
    home = _home(tmp_path)
    assert provider_syncing(home / "Library/CloudStorage/Dropbox/MetaList Backups", home=home) == "Dropbox"
    assert provider_syncing(home / "Documents/Backups", home=home) == ""


class _BackupStarted(Exception):
    """The run got past the warning and began writing the archive."""


def _start_backup(database_path: Path, folder: Path) -> None:
    raise _BackupStarted()


@pytest.fixture
def unprotected_vault_in_dropbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    database = tmp_path / "recipes.metalist.db"
    database.touch()
    saved: dict[str, object] = {
        "folder_path": "", "unchecked_namespaces": [], "retention_count": 3, "synced_plaintext_acknowledged": [],
    }
    monkeypatch.setattr(backups_route, "ACTIVE_NAMESPACE", "recipes")
    monkeypatch.setattr(backups_route, "list_available_namespaces", lambda: ["recipes"])
    monkeypatch.setattr(backups_route, "resolve_namespaced_database_path", lambda *, namespace: database)
    monkeypatch.setattr(backups_route, "provider_syncing", lambda path, *, home: "Dropbox")
    monkeypatch.setattr(backups_route, "vault_has_password", lambda path: False)
    monkeypatch.setattr(backups_route, "load_backup_settings", lambda *, token: saved)

    def save(**update: object) -> dict[str, object]:
        saved["synced_plaintext_acknowledged"] = [
            {"namespace": namespace, "folder_path": update["folder_path"]} for namespace in update["newly_acknowledged_namespaces"]
        ]
        return saved

    monkeypatch.setattr(backups_route, "update_backup_settings", save)
    monkeypatch.setattr(backups_route, "create_timestamped_backup_for_paths", _start_backup)
    return saved


def _run(tmp_path: Path, acknowledged: list[str]):
    return backups_route.run_backup(
        payload=backups_route.BackupSettingsUpdateRequest(
            folder_path=str(tmp_path / "Dropbox"), selected_namespaces=["recipes"], retention_count=3,
            plaintext_sync_acknowledged=acknowledged,
        ),
        token="token",
    )


def test_a_vault_without_a_password_is_not_backed_up_to_a_synced_folder_unasked(
    tmp_path: Path, unprotected_vault_in_dropbox: dict[str, object],
) -> None:
    check = backups_route.check_plaintext_sync(
        payload=backups_route.PlaintextSyncCheckRequest(folder_path=str(tmp_path / "Dropbox"), selected_namespaces=["recipes"]),
        token="token",
    )
    assert (check.provider, check.unprotected_namespaces) == ("Dropbox", ["recipes"])
    with pytest.raises(backups_route.HTTPException) as refused:
        _run(tmp_path, acknowledged=[])
    assert refused.value.status_code == 409
    assert refused.value.detail == "This folder syncs to Dropbox, and recipes has no password: confirm before backing up"


def test_once_agreed_the_folder_and_vault_are_not_asked_again(
    tmp_path: Path, unprotected_vault_in_dropbox: dict[str, object],
) -> None:
    with pytest.raises(_BackupStarted):
        _run(tmp_path, acknowledged=["recipes"])
    assert unprotected_vault_in_dropbox["synced_plaintext_acknowledged"] == [
        {"namespace": "recipes", "folder_path": str(tmp_path / "Dropbox")},
    ]
    check = backups_route.check_plaintext_sync(
        payload=backups_route.PlaintextSyncCheckRequest(folder_path=str(tmp_path / "Dropbox"), selected_namespaces=["recipes"]),
        token="token",
    )
    assert check.unprotected_namespaces == []
