"""Restore From Backup's Choose File… (the maintainer, 2026-11-19): a backup kept anywhere on
this computer is picked in the system's file dialog and restored from where it is. The backup
folder setting stays as it is, the browser never sends a path, and the file is only read."""

from __future__ import annotations

from http import HTTPStatus
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.api.routes.backups as backups_route
from app.services import native_folder_picker
from app.services.chosen_backup_file import ChosenBackupFile
from app.services.native_folder_picker import TEST_FILE_PICK_ENVIRONMENT_VARIABLE, answered_file_pick, pick_file

THIS_COMPUTER = Request({"type": "http", "client": ("127.0.0.1", 50000), "headers": []})
# An address reserved for documentation (RFC 5737): never one of this computer's own.
ANOTHER_COMPUTER = Request({"type": "http", "client": ("203.0.113.9", 50000), "headers": []})
BACKUP_NAME = "source-20260419-090000-000000.metalist-backup.tar.gz"
BACKUP_BYTES = b"a backup kept in Downloads"


@pytest.fixture(autouse=True)
def nothing_chosen(monkeypatch: pytest.MonkeyPatch) -> ChosenBackupFile:
    chosen = ChosenBackupFile()
    monkeypatch.setattr(backups_route, "chosen_backup_file", chosen)
    return chosen


@pytest.fixture
def downloaded_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A backup outside the backup folder, which is not set."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    backup_path = downloads / BACKUP_NAME
    backup_path.write_bytes(BACKUP_BYTES)
    monkeypatch.setattr(backups_route, "_pick_backup_file_path", lambda: str(backup_path))
    monkeypatch.setattr(
        backups_route, "load_backup_settings",
        lambda *, token: {"folder_path": "", "selected_namespaces": ["source"], "retention_count": 30},
    )
    return backup_path


def _restore_request(*, source: str, filename: str) -> backups_route.BackupRestoreRequest:
    return backups_route.BackupRestoreRequest(
        backup_id=f"{source}::source::{filename}", source=source, backup_filename=filename,
        backup_namespace="source", target_namespace="source",
    )


def test_a_chosen_file_comes_back_as_a_backup_to_restore(downloaded_backup: Path) -> None:
    response = backups_route.pick_backup_file(request=THIS_COMPUTER, token="token")

    assert response.selected is True
    assert response.file_path == str(downloaded_backup)
    assert [(backup.backup_id, backup.source, backup.filename, backup.namespace, backup.size_bytes) for backup in response.backups] == [
        (f"file::source::{BACKUP_NAME}", "file", BACKUP_NAME, "source", len(BACKUP_BYTES)),
    ]


def test_cancelling_the_file_dialog_chooses_nothing(monkeypatch: pytest.MonkeyPatch, nothing_chosen: ChosenBackupFile) -> None:
    monkeypatch.setattr(backups_route, "_pick_backup_file_path", lambda: None)

    response = backups_route.pick_backup_file(request=THIS_COMPUTER, token="token")

    assert (response.selected, response.backups, response.file_path) == (False, [], "")
    assert nothing_chosen.path_named(BACKUP_NAME) is None


def test_a_file_that_is_not_a_backup_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, nothing_chosen: ChosenBackupFile,
) -> None:
    renamed = tmp_path / "my old notes.tar.gz"
    renamed.write_bytes(BACKUP_BYTES)
    monkeypatch.setattr(backups_route, "_pick_backup_file_path", lambda: str(renamed))

    with pytest.raises(HTTPException) as refused:
        backups_route.pick_backup_file(request=THIS_COMPUTER, token="token")

    assert refused.value.status_code == HTTPStatus.BAD_REQUEST
    assert "my old notes.tar.gz is not a MetaList backup" in refused.value.detail
    assert nothing_chosen.path_named(renamed.name) is None


def test_another_computer_cannot_open_the_file_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dialog() -> str | None:
        raise AssertionError("the file dialog must not open for another computer")

    monkeypatch.setattr(backups_route, "_pick_backup_file_path", no_dialog)

    with pytest.raises(HTTPException) as refused:
        backups_route.pick_backup_file(request=ANOTHER_COMPUTER, token="token")

    assert refused.value.status_code == HTTPStatus.FORBIDDEN


def test_the_list_offers_choose_file_only_to_this_computer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(backups_route, "_backups_in_folder", lambda *, token: [])
    monkeypatch.setattr(backups_route, "namespaces_shown_to_requester", lambda request: None)

    assert backups_route.list_backups(request=THIS_COMPUTER, token="token").current_namespace == backups_route.ACTIVE_NAMESPACE
    assert backups_route.list_backups(request=THIS_COMPUTER, token="token").can_choose_file is True
    assert backups_route.list_backups(request=ANOTHER_COMPUTER, token="token").can_choose_file is False


def test_a_restore_reads_the_chosen_file_where_it_is(downloaded_backup: Path) -> None:
    backups_route.pick_backup_file(request=THIS_COMPUTER, token="token")

    backup_path = backups_route._backup_path_to_restore(
        source="file", backup_id=f"file::source::{BACKUP_NAME}", backup_filename=BACKUP_NAME,
        backup_namespace="source", token="token",
    )

    assert backup_path == downloaded_backup
    assert downloaded_backup.read_bytes() == BACKUP_BYTES, "the chosen file is only read"
    assert sorted(path.name for path in downloaded_backup.parent.iterdir()) == [BACKUP_NAME], "nothing is written beside it"


def test_a_restore_naming_a_file_that_was_not_chosen_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(backups_route, "resolve_namespaced_database_path", lambda *, namespace: tmp_path / f"{namespace}.metalist.db")

    with pytest.raises(HTTPException) as refused:
        backups_route.restore_backup(payload=_restore_request(source="file", filename=BACKUP_NAME), request=THIS_COMPUTER, token="token")

    assert refused.value.status_code == HTTPStatus.NOT_FOUND
    assert "choose it again" in refused.value.detail


def test_a_restore_from_an_unknown_source_is_refused() -> None:
    with pytest.raises(HTTPException) as refused:
        backups_route.restore_backup_preflight(
            payload=_restore_request(source="elsewhere", filename=BACKUP_NAME), request=THIS_COMPUTER, token="token",
        )

    assert refused.value.status_code == HTTPStatus.BAD_REQUEST


def test_a_test_server_answers_the_file_dialog_from_the_variable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dialog(*, command: list[str]) -> str | None:
        raise AssertionError(f"the dialog must not open, got {command}")

    monkeypatch.setattr(native_folder_picker, "_run_native_folder_picker_command", no_dialog)
    chosen = tmp_path / BACKUP_NAME
    assert answered_file_pick(environ={"METALIST_DATA_DIRECTORY": str(tmp_path)}) is None
    with pytest.raises(RuntimeError, match="uses the user's vault"):
        answered_file_pick(environ={TEST_FILE_PICK_ENVIRONMENT_VARIABLE: str(chosen)})
    with pytest.raises(RuntimeError, match="absolute path"):
        answered_file_pick(environ={"METALIST_DATA_DIRECTORY": str(tmp_path), TEST_FILE_PICK_ENVIRONMENT_VARIABLE: "relative.tar.gz"})
    monkeypatch.setenv("METALIST_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(TEST_FILE_PICK_ENVIRONMENT_VARIABLE, str(chosen))
    assert pick_file(prompt="Choose a MetaList backup file to restore") == str(chosen)
