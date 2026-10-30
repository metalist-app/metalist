"""Back Up Now remembers the vaults left out (docs/ready-to-build/backup-vault-choice.md):
settings saved with the vaults checked are converted once, after unlock."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

import app.services.backup_settings_service as backup_settings_service
from app.db.content_migrations_sql import is_content_migration_complete
from app.db.raw_connection import raw_sqlite_connection
from app.db.session import begin_writer
from app.db.settings_sql import insert_default_settings
from app.models.database import SafeSession
from app.security.encryption import set_encryption_required
from app.services.backup_settings_service import (
    BACKUP_SETTINGS_UNCHECKED_MIGRATION_ID,
    convert_backup_settings_to_unchecked,
    list_available_namespaces,
    load_backup_settings,
    save_backup_settings,
)

RETENTION_COUNT = 30
AVAILABLE = ["default", "home", "work"]


@pytest.fixture
def settings_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    monkeypatch.setattr(backup_settings_service, "ACTIVE_NAMESPACE", "default")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    with begin_writer() as connection:
        insert_default_settings(connection)
    yield
    set_encryption_required(False)
    SafeSession.use_file_db()


def _store_payload(payload: dict[str, object]) -> None:
    with begin_writer() as connection:
        connection.execute(
            "UPDATE app_settings SET backup_settings_json = ?, backup_settings_encryption_nonce = NULL, "
            "backup_settings_encryption_tag = NULL WHERE id = 1",
            (json.dumps(payload),),
        )


def _is_recorded() -> bool:
    with begin_writer() as connection:
        return is_content_migration_complete(raw_sqlite_connection(connection), BACKUP_SETTINGS_UNCHECKED_MIGRATION_ID)


def test_settings_saved_with_the_vaults_checked_keep_the_ones_left_out(settings_database: None) -> None:
    _store_payload({"retention_count": RETENTION_COUNT, "folder_path": "/backups", "selected_namespaces": ["default", "work"]})

    convert_backup_settings_to_unchecked(available_namespaces=AVAILABLE)

    assert load_backup_settings(token="") == {
        "retention_count": RETENTION_COUNT, "folder_path": "/backups", "unchecked_namespaces": ["home"],
        "synced_plaintext_acknowledged": [],
    }
    assert _is_recorded()


def test_the_vault_in_use_is_never_left_out_by_the_conversion(settings_database: None) -> None:
    _store_payload({"retention_count": RETENTION_COUNT, "folder_path": "/backups", "selected_namespaces": ["work"]})

    convert_backup_settings_to_unchecked(available_namespaces=AVAILABLE)

    assert load_backup_settings(token="")["unchecked_namespaces"] == ["home"]


def test_settings_from_before_vaults_could_be_chosen_leave_none_out(settings_database: None) -> None:
    _store_payload({"retention_count": RETENTION_COUNT, "local_enabled": True, "google_drive_enabled": False})

    convert_backup_settings_to_unchecked(available_namespaces=AVAILABLE)

    assert load_backup_settings(token="") == {
        "retention_count": RETENTION_COUNT, "folder_path": "", "unchecked_namespaces": [],
        "synced_plaintext_acknowledged": [],
    }


def test_a_vault_without_saved_settings_is_recorded_as_converted(settings_database: None) -> None:
    convert_backup_settings_to_unchecked(available_namespaces=AVAILABLE)

    assert load_backup_settings(token="")["unchecked_namespaces"] == []
    assert _is_recorded()


def test_settings_cannot_leave_out_the_vault_in_use(settings_database: None) -> None:
    with pytest.raises(RuntimeError, match="must not leave out the vault in use"):
        save_backup_settings(
            token="", settings={
                "retention_count": RETENTION_COUNT, "folder_path": "", "unchecked_namespaces": ["default"],
                "synced_plaintext_acknowledged": [],
            },
        )


def test_list_available_namespaces_requires_an_existing_namespace_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    namespaces_directory = tmp_path / "namespaces"
    for namespace in ("default", "recovered", "cla", "thomas"):
        (namespaces_directory / namespace).mkdir(parents=True)
    (namespaces_directory / "cla" / "cla.metalist.db").touch()
    (namespaces_directory / "thomas" / "thomas.metalist.db").touch()
    monkeypatch.setattr(backup_settings_service, "resolve_namespaces_directory", lambda: namespaces_directory)
    monkeypatch.setattr(
        backup_settings_service,
        "resolve_namespaced_database_path",
        lambda *, namespace: namespaces_directory / namespace / f"{namespace}.metalist.db",
    )

    assert list_available_namespaces() == ["cla", "thomas"]
