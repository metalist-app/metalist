"""A test server answers the operating system's folder dialog from METALIST_TEST_PICK_FOLDER
(app/services/native_folder_picker.py): only with its own data folder, only with a folder that
exists, and without opening the dialog."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import native_folder_picker
from app.services.native_folder_picker import TEST_FOLDER_PICK_ENVIRONMENT_VARIABLE, answered_folder_pick, pick_folder

PROMPT = "Choose a folder of Markdown files to import into MetaList"


def test_without_the_variable_the_dialog_opens() -> None:
    assert answered_folder_pick(environ={"METALIST_DATA_DIRECTORY": "/data"}) is None


def test_a_server_on_the_users_vault_refuses_an_answered_dialog(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="this server uses the user's vault"):
        answered_folder_pick(environ={TEST_FOLDER_PICK_ENVIRONMENT_VARIABLE: str(tmp_path)})


def test_the_answer_must_be_an_existing_absolute_folder(tmp_path: Path) -> None:
    environ = {"METALIST_DATA_DIRECTORY": str(tmp_path)}
    with pytest.raises(RuntimeError, match="absolute path of a folder"):
        answered_folder_pick(environ={**environ, TEST_FOLDER_PICK_ENVIRONMENT_VARIABLE: "relative/folder"})
    with pytest.raises(RuntimeError, match="absolute path of a folder"):
        answered_folder_pick(environ={**environ, TEST_FOLDER_PICK_ENVIRONMENT_VARIABLE: str(tmp_path / "missing")})
    assert answered_folder_pick(environ={**environ, TEST_FOLDER_PICK_ENVIRONMENT_VARIABLE: str(tmp_path)}) == str(tmp_path)


def test_pick_folder_answers_from_the_variable_without_a_dialog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def no_dialog(*, command: list[str]) -> str | None:
        raise AssertionError(f"the dialog must not open, got {command}")

    monkeypatch.setattr(native_folder_picker, "_run_native_folder_picker_command", no_dialog)
    monkeypatch.setenv("METALIST_DATA_DIRECTORY", str(tmp_path))
    monkeypatch.setenv(TEST_FOLDER_PICK_ENVIRONMENT_VARIABLE, str(tmp_path))

    assert pick_folder(prompt=PROMPT) == str(tmp_path)
