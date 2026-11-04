"""convert-from-legacy.py reads an export the old MetaList encrypted (the maintainer, 2026-11-04:
friend Joe's notes are password protected, and its Backup ticks "Password Protected" by default).

The old MetaList encrypted in the browser (MetaList_old/js/utils/crypto.js): the key is the SHA-256
of the password, and each top-level note's subitems are AES-GCM ciphertext with their own 12-byte
IV. The fixture was written by that code itself, run in Node, with PASSWORD
(make-encrypted-fixture.mjs). The converter asks for the old password until it opens the export,
then offers it for the converted MetaList. The decryption itself is app/services/legacy_metalist.py
(test_legacy_metalist.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from app.services.auth_service import AuthService
from tests.unit.legacy_database_fixture import (
    ENCRYPTED_BUNDLE_PASSWORD as PASSWORD,
    ENCRYPTED_BUNDLE_PATH as _FIXTURE,
    SECRET_TEXT,
    encrypted_bundle as _encrypted_payload,
    plain_bundle,
    write_legacy_database,
)
from tests.unit.test_convert_from_legacy import _PROJECT_ROOT, _load_converter_module

WEAK_PASSWORD = "hunter2"
FIXTURE_NOTE_COUNT = 3


def _answers(monkeypatch, converter, answers: list[str]) -> list[str]:
    """Answer the converter's prompts in order; returns the prompts it asked."""
    asked: list[str] = []
    remaining = iter(answers)

    def answer(*, prompt: str) -> str:
        asked.append(prompt)
        return next(remaining)

    monkeypatch.setattr(converter, "_prompt_secret_input", answer)
    monkeypatch.setattr(converter, "_prompt_input", answer)
    return asked


def test_a_wrong_password_asks_again(monkeypatch, capsys) -> None:
    converter = _load_converter_module()
    asked = _answers(monkeypatch, converter, ["not-it", PASSWORD])
    items, password = converter._legacy_items(_encrypted_payload(), None)
    assert password == PASSWORD
    assert len(items) == 2
    assert asked == ["Password of the old MetaList: ", "Password of the old MetaList: "]
    assert "Incorrect password." in capsys.readouterr().out


def test_an_unencrypted_export_asks_for_no_old_password(monkeypatch) -> None:
    converter = _load_converter_module()
    asked = _answers(monkeypatch, converter, [])
    payload = {"encryption": {"encrypted": False}, "data": [{"id": 1}]}
    assert converter._legacy_items(payload, None) == ([{"id": 1}], None)
    assert asked == []


@pytest.mark.parametrize("field, value", [("alg", "AES-CBC"), ("digest", "SHA-1"), ("encryption_scheme_version", 2)])
def test_an_unknown_encryption_scheme_fails_before_any_prompt(monkeypatch, field: str, value) -> None:
    converter = _load_converter_module()
    asked = _answers(monkeypatch, converter, [])
    payload = _encrypted_payload()
    payload["encryption"][field] = value
    with pytest.raises(ValueError, match=field):
        converter._legacy_items(payload, None)
    assert asked == []


def test_the_old_password_is_offered_for_the_converted_metalist(monkeypatch) -> None:
    converter = _load_converter_module()
    monkeypatch.setattr(converter, "AuthService", AuthService, raising=False)
    asked = _answers(monkeypatch, converter, [""])
    assert converter._prompt_for_password(PASSWORD) == PASSWORD
    assert asked == ["Protect the converted MetaList with the same password? [Y/n]: "]


def test_declining_the_old_password_asks_for_a_new_one(monkeypatch) -> None:
    converter = _load_converter_module()
    monkeypatch.setattr(converter, "AuthService", AuthService, raising=False)
    new_password = "cobalt otter lantern violin"
    asked = _answers(monkeypatch, converter, ["n", "y", new_password, new_password])
    assert converter._prompt_for_password(PASSWORD) == new_password
    assert asked[1:] == ["Enable password protection? [y/N]: ", "Enter new password: ", "Confirm password: "]


def test_an_old_password_too_weak_for_the_new_metalist_is_not_offered(monkeypatch, capsys) -> None:
    converter = _load_converter_module()
    monkeypatch.setattr(converter, "AuthService", AuthService, raising=False)
    asked = _answers(monkeypatch, converter, ["n"])
    assert converter._prompt_for_password(WEAK_PASSWORD) is None
    assert asked == ["Enable password protection? [y/N]: "]
    assert "The old password is too weak for the new MetaList" in capsys.readouterr().out


def test_a_weak_new_password_is_refused_before_anything_is_written(monkeypatch, capsys) -> None:
    # Before, AuthService refused it after the import, leaving the notes unprotected.
    converter = _load_converter_module()
    monkeypatch.setattr(converter, "AuthService", AuthService, raising=False)
    answers = ["y", WEAK_PASSWORD, PASSWORD, PASSWORD]
    asked = _answers(monkeypatch, converter, answers)
    assert converter._prompt_for_password(None) == PASSWORD
    assert asked.count("Enter new password: ") == 2
    assert "Password must be at least" in capsys.readouterr().out


def test_the_converter_turns_an_encrypted_export_into_a_protected_metalist(tmp_path: Path) -> None:
    fresh_home = tmp_path / "home"
    namespace_directory = fresh_home / "MetaList" / "namespaces" / "joe"
    environ = os.environ.copy()
    environ["HOME"] = str(fresh_home)
    environ["METALIST_DATA_DIRECTORY"] = str(fresh_home / "MetaList")
    for name in ("METALIST_NAMESPACE", "METALIST_PORT", "METALIST_HTTPS_PORT"):
        if name in environ:
            del environ[name]

    completed = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "convert-from-legacy.py"), "--namespace", "joe",
         "--port", "8010", "--https-port", "8453", "--kdf-iterations", "1", "--input", str(_FIXTURE)],
        cwd=_PROJECT_ROOT, env=environ, input=f"not-it\n{PASSWORD}\n\n",
        capture_output=True, check=False, encoding="utf-8",
    )

    assert completed.returncode == 0, completed.stderr
    assert "Incorrect password." in completed.stdout
    database_path = namespace_directory / "joe.metalist.db"
    with sqlite3.connect(database_path) as connection:
        settings_row = connection.execute("SELECT encryption_enabled FROM app_settings WHERE id = 1").fetchone()
        note_count_row = connection.execute("SELECT COUNT(*) FROM notes").fetchone()
    assert settings_row == (1,)
    assert note_count_row == (FIXTURE_NOTE_COUNT,)
    assert SECRET_TEXT.encode("utf-8") not in database_path.read_bytes()


# MetaList runs the converter on the old MetaList's own file (legacy_metalist_conversion.py): it
# reads that file, never changes it, takes both passwords as one JSON line and asks nothing.

def _run_on_legacy_database(tmp_path: Path, bundle: dict, passwords: dict) -> tuple[subprocess.CompletedProcess, Path, Path]:
    data_directory = tmp_path / "data"
    legacy_path = write_legacy_database(tmp_path / "metalist.db", bundle)
    environ = {key: value for key, value in os.environ.items() if not key.startswith("METALIST_")}
    environ["METALIST_DATA_DIRECTORY"] = str(data_directory)
    legacy_bytes = legacy_path.read_bytes()
    completed = subprocess.run(
        [sys.executable, str(_PROJECT_ROOT / "convert-from-legacy.py"), "--namespace", "joe", "--kdf-iterations", "1",
         "--legacy-database", str(legacy_path), "--passwords-from-stdin"],
        cwd=_PROJECT_ROOT, env=environ, input=json.dumps(passwords) + "\n",
        capture_output=True, check=False, encoding="utf-8",
    )
    assert legacy_path.read_bytes() == legacy_bytes
    return completed, data_directory / "namespaces" / "joe" / "joe.metalist.db", legacy_path


def test_the_converter_reads_the_old_metalists_own_file_and_asks_nothing(tmp_path: Path) -> None:
    completed, database_path, _ = _run_on_legacy_database(
        tmp_path, _encrypted_payload(), {"legacy_password": PASSWORD, "password": PASSWORD})
    assert completed.returncode == 0, completed.stderr
    assert "Password of the old MetaList" not in completed.stdout
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT encryption_enabled FROM app_settings WHERE id = 1").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone() == (FIXTURE_NOTE_COUNT,)
    assert SECRET_TEXT.encode("utf-8") not in database_path.read_bytes()


def test_old_notes_without_a_password_stay_without_one(tmp_path: Path) -> None:
    completed, database_path, _ = _run_on_legacy_database(
        tmp_path, plain_bundle(), {"legacy_password": None, "password": None})
    assert completed.returncode == 0, completed.stderr
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT encryption_enabled FROM app_settings WHERE id = 1").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone() == (2,)


@pytest.mark.parametrize("passwords, message", [
    ({"legacy_password": "not-it", "password": PASSWORD}, "does not open"),
    ({"legacy_password": PASSWORD, "password": WEAK_PASSWORD}, "password rules"),
    ({"legacy_password": None, "password": None}, "does not open"),
], ids=["wrong old password", "weak new password", "no old password"])
def test_supplied_passwords_that_cannot_work_stop_it_before_anything_is_written(
    tmp_path: Path, passwords: dict, message: str,
) -> None:
    completed, database_path, _ = _run_on_legacy_database(tmp_path, _encrypted_payload(), passwords)
    assert completed.returncode != 0
    assert message in completed.stderr
    assert not database_path.exists()
