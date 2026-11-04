"""Bringing in the old MetaList's notes from MetaList itself (docs/ui/legacy-import.md):
offered only to a namespace with no notes and no password, checked before anything is written,
installed as a restore installs an archive, the old file only read."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import app.api.routes.legacy_import as legacy_route
from app.db.schema import initialize_schema
from app.db.settings_sql import insert_default_settings
from app.server_runtime import NamespaceLaunchProfile
from app.services import legacy_metalist_conversion
from app.services.input_errors import InputRejected
from app.services.legacy_metalist import LegacyDatabase
from app.services.legacy_metalist_conversion import LegacyConversionRequest, convert_legacy_into_live_namespace
from tests.unit.legacy_database_fixture import (
    ENCRYPTED_BUNDLE_PASSWORD,
    SECRET_TEXT,
    encrypted_bundle,
    plain_bundle,
    write_legacy_database,
)

STRONG_PASSWORD = "cobalt otter lantern violin"
WEAK_PASSWORD = "hunter2"


class _Database:
    def connection(self) -> object:
        return object()


def _offer(monkeypatch: pytest.MonkeyPatch, *, legacy: LegacyDatabase | None, has_password: bool, note_count: int) -> None:
    monkeypatch.setattr(legacy_route, "require_request_auth_token", lambda request: "token")
    monkeypatch.setattr(legacy_route, "find_legacy_database", lambda data_directory: legacy)
    monkeypatch.setattr(legacy_route, "AuthService", type("Auth", (), {
        "__init__": lambda self, db: None,
        "has_password": lambda self: has_password,
        "password_policy_error": staticmethod(legacy_route.AuthService.password_policy_error),
    }))
    monkeypatch.setattr(legacy_route, "count_notes", lambda connection: note_count)


@pytest.mark.parametrize("found, has_password, note_count, offered", [
    (True, False, 0, True),
    (False, False, 0, False),
    (True, True, 0, False),
    (True, False, 1, False),
], ids=["fresh install", "no old file", "has a password", "has notes"])
def test_the_old_notes_are_offered_only_to_an_empty_namespace_without_a_password(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, found: bool, has_password: bool, note_count: int, offered: bool,
) -> None:
    legacy = None
    if found:
        legacy = LegacyDatabase(path=tmp_path / "metalist.db", encrypted=True)
    _offer(monkeypatch, legacy=legacy, has_password=has_password, note_count=note_count)
    status = legacy_route.legacy_import_status(SimpleNamespace(), _Database())
    assert status == legacy_route.LegacyImportStatus(offered=offered, encrypted=offered)


@pytest.mark.parametrize("old, new, opens, problems", [
    (ENCRYPTED_BUNDLE_PASSWORD, ENCRYPTED_BUNDLE_PASSWORD, True, 0),
    ("not-it", ENCRYPTED_BUNDLE_PASSWORD, False, 0),
    (ENCRYPTED_BUNDLE_PASSWORD, WEAK_PASSWORD, True, 1),
], ids=["opens, strong enough", "wrong", "opens, new one too weak"])
def test_the_check_says_whether_the_old_password_opens_and_the_new_one_is_allowed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, old: str, new: str, opens: bool, problems: int,
) -> None:
    path = write_legacy_database(tmp_path / "metalist.db", encrypted_bundle())
    _offer(monkeypatch, legacy=LegacyDatabase(path=path, encrypted=True), has_password=False, note_count=0)
    payload = legacy_route.LegacyPasswordCheckRequest(legacy_password=SecretStr(old), new_password=SecretStr(new))
    check = legacy_route.check_legacy_password.__wrapped__(SimpleNamespace(), payload, _Database())
    assert check.opens is opens
    assert len(check.new_password_problems) == problems


@pytest.mark.parametrize("old, new, message", [
    ("not-it", STRONG_PASSWORD, "Incorrect password"),
    (ENCRYPTED_BUNDLE_PASSWORD, WEAK_PASSWORD, "at least"),
], ids=["wrong old password", "weak new password"])
def test_passwords_that_cannot_work_are_refused_before_anything_is_written(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, old: str, new: str, message: str,
) -> None:
    path = write_legacy_database(tmp_path / "metalist.db", encrypted_bundle())
    _offer(monkeypatch, legacy=LegacyDatabase(path=path, encrypted=True), has_password=False, note_count=0)
    monkeypatch.setattr(legacy_route, "_convert", lambda *args, **kwargs: pytest.fail("nothing is converted"))
    payload = legacy_route.ProtectedConversionRequest(legacy_password=SecretStr(old), new_password=SecretStr(new))
    with pytest.raises(InputRejected, match=message):
        legacy_route.convert_protected_legacy_metalist.__wrapped__(SimpleNamespace(), payload, _Database())


def test_old_notes_are_not_converted_where_they_are_not_offered(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _offer(monkeypatch, legacy=LegacyDatabase(path=tmp_path / "metalist.db", encrypted=False), has_password=False, note_count=1)
    with pytest.raises(legacy_route.HTTPException):
        legacy_route.convert_legacy_metalist.__wrapped__(SimpleNamespace(), _Database())


def test_converting_holds_maintenance_then_restarts_and_a_failure_restarts_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls: list[str] = []
    profile = NamespaceLaunchProfile(namespace="default", port=8000, https_port=None, mcp_port=None)
    monkeypatch.setattr(legacy_route, "resolve_namespace_launch_defaults", lambda **kwargs: profile)
    monkeypatch.setattr(legacy_route, "resolve_live_database_path", lambda: tmp_path / "default.metalist.db")
    monkeypatch.setattr(legacy_route.maintenance_service, "enter_maintenance", lambda reason: calls.append("enter"))
    monkeypatch.setattr(legacy_route.maintenance_service, "exit_maintenance", lambda: calls.append("exit"))
    monkeypatch.setattr(legacy_route, "save_namespace_launch_profile", lambda **kwargs: calls.append("profile"))
    monkeypatch.setattr(legacy_route, "_reset_runtime_state_after_restore", lambda: calls.append("reset"))
    monkeypatch.setattr(legacy_route, "deactivate_authenticated_logging", lambda: calls.append("logging"))
    monkeypatch.setattr(legacy_route, "_schedule_server_restart_after_restore", lambda **kwargs: calls.append("restart"))
    monkeypatch.setattr(legacy_route, "convert_legacy_into_live_namespace", lambda request, **kwargs: calls.append("convert"))
    legacy = LegacyDatabase(path=tmp_path / "metalist.db", encrypted=False)

    legacy_route._convert(legacy, legacy_password=None, password=None)
    assert calls == ["enter", "convert", "profile", "reset", "logging", "exit", "restart"]

    calls.clear()

    def failing_conversion(request, **kwargs) -> None:
        raise RuntimeError("converter failed")

    monkeypatch.setattr(legacy_route, "convert_legacy_into_live_namespace", failing_conversion)
    with pytest.raises(RuntimeError, match="converter failed"):
        legacy_route._convert(legacy, legacy_password=None, password=None)
    assert calls == ["enter", "exit"]


# The conversion itself: the real converter, into a live namespace that has nothing yet.

def _empty_live_namespace(tmp_path: Path) -> Path:
    database_path = tmp_path / "live" / "default" / "default.metalist.db"
    database_path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database_path)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        connection.commit()
    return database_path


def _request(legacy: LegacyDatabase, *, legacy_password: str | None, password: str | None) -> LegacyConversionRequest:
    profile = NamespaceLaunchProfile(namespace="default", port=8000, https_port=None, mcp_port=None)
    return LegacyConversionRequest(
        legacy=legacy, legacy_password=legacy_password, password=password, launch_profile=profile, kdf_time_cost=1,
    )


@pytest.mark.parametrize("bundle, legacy_password, encrypted, note_count", [
    (encrypted_bundle(), ENCRYPTED_BUNDLE_PASSWORD, 1, 3),
    (plain_bundle(), None, 0, 2),
], ids=["protected", "not protected"])
def test_the_old_notes_replace_the_empty_live_namespace(
    tmp_path: Path, bundle: dict, legacy_password: str | None, encrypted: int, note_count: int,
) -> None:
    legacy_path = write_legacy_database(tmp_path / "metalist.db", bundle)
    legacy_bytes = legacy_path.read_bytes()
    database_path = _empty_live_namespace(tmp_path)
    legacy = LegacyDatabase(path=legacy_path, encrypted=legacy_password is not None)

    convert_legacy_into_live_namespace(
        _request(legacy, legacy_password=legacy_password, password=legacy_password), database_path=database_path,
    )

    with closing(sqlite3.connect(database_path)) as connection:
        assert connection.execute("SELECT encryption_enabled FROM app_settings WHERE id = 1").fetchone() == (encrypted,)
        assert connection.execute("SELECT COUNT(*) FROM notes").fetchone() == (note_count,)
    assert database_path.with_name("default.metalist.files.db").is_file()
    assert SECRET_TEXT.encode("utf-8") not in database_path.read_bytes()
    assert legacy_path.read_bytes() == legacy_bytes
    # The staging folder beside the old file is gone.
    assert sorted(entry.name for entry in tmp_path.iterdir()) == ["live", "metalist.db"]


def test_an_old_file_that_changes_meanwhile_installs_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    legacy_path = write_legacy_database(tmp_path / "metalist.db", plain_bundle())
    database_path = _empty_live_namespace(tmp_path)
    live_bytes = database_path.read_bytes()
    real_run = legacy_metalist_conversion._run_converter

    def run_while_the_old_metalist_writes(request, staging_directory) -> None:
        real_run(request, staging_directory)
        with closing(sqlite3.connect(legacy_path)) as connection:
            connection.execute("UPDATE config SET value = value WHERE key = 'bundle'")
            connection.execute("INSERT INTO items (key, value) VALUES (99, '{}')")
            connection.commit()

    monkeypatch.setattr(legacy_metalist_conversion, "_run_converter", run_while_the_old_metalist_writes)
    with pytest.raises(InputRejected, match="Close the old MetaList"):
        convert_legacy_into_live_namespace(
            _request(LegacyDatabase(path=legacy_path, encrypted=False), legacy_password=None, password=None),
            database_path=database_path,
        )
    assert database_path.read_bytes() == live_bytes
