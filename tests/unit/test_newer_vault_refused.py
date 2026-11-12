"""A vault saved by a newer MetaList is refused before anything is written to it, with a plain
message instead of a traceback (2026-11-11: the installed 0.25.0 set up its own tables in a
version 18 vault, then printed a traceback ending in "Database version 18 is newer than supported")."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

import main as main_module
from app.db.version import (
    CURRENT_DATABASE_VERSION,
    EXIT_VAULT_NEEDS_NEWER_METALIST,
    VaultNeedsNewerMetaList,
    database_version_on_disk,
    require_database_not_newer,
)
from app.services import namespace_switcher

_REPO_ROOT = Path(__file__).resolve().parents[2]
_NEWER = CURRENT_DATABASE_VERSION + 1


def _vault(directory: Path, *, namespace: str, version: int) -> Path:
    database_path = directory / "namespaces" / namespace / f"{namespace}.metalist.db"
    database_path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(database_path)) as connection:
        connection.execute("CREATE TABLE written_by_a_newer_metalist (id INTEGER PRIMARY KEY)")
        connection.execute(f"PRAGMA user_version = {version}")
        connection.commit()
    return database_path


def _fingerprint(folder: Path) -> dict[str, tuple[str, int]]:
    """Every file in the folder: its bytes' hash and when it was last written."""
    return {
        str(path.relative_to(folder)): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
        for path in sorted(folder.rglob("*")) if path.is_file()
    }


def test_a_vaults_version_is_read_without_writing(tmp_path: Path) -> None:
    database_path = _vault(tmp_path, namespace="cla", version=_NEWER)
    before = _fingerprint(database_path.parent)
    assert database_version_on_disk(database_path) == _NEWER
    assert database_version_on_disk(tmp_path / "none.metalist.db") == 0
    assert _fingerprint(database_path.parent) == before


def test_a_newer_vault_is_refused_in_plain_words(tmp_path: Path) -> None:
    database_path = _vault(tmp_path, namespace="cla", version=_NEWER)
    with pytest.raises(VaultNeedsNewerMetaList) as refused:
        require_database_not_newer(database_path)
    message = str(refused.value)
    assert "Vault cla was saved by a newer MetaList" in message
    assert "Update MetaList" in message
    require_database_not_newer(_vault(tmp_path / "current", namespace="thomas", version=CURRENT_DATABASE_VERSION))


def test_startup_refuses_a_newer_vault_before_writing_to_it(tmp_path: Path) -> None:
    database_path = _vault(tmp_path, namespace="cla", version=_NEWER)
    before = _fingerprint(database_path.parent)
    environ = {key: value for key, value in os.environ.items() if key != "PYTHONOPTIMIZE"}
    environ.update({"METALIST_DATA_DIRECTORY": str(tmp_path), "METALIST_NAMESPACE": "cla"})
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=_REPO_ROOT, env=environ, capture_output=True, encoding="utf-8", check=False,
    )
    assert result.returncode != 0
    # Imported directly, the refusal is the process's last error (its log names the type).
    assert "VaultNeedsNewerMetaList" in result.stdout + result.stderr
    assert _fingerprint(database_path.parent) == before


def test_the_launcher_names_a_child_that_found_its_vault_too_new(tmp_path: Path) -> None:
    refused = namespace_switcher.child_exit_error(
        namespace="cla", exit_code=EXIT_VAULT_NEEDS_NEWER_METALIST, log_path=tmp_path / "namespace-cla.log",
        log_tail="Vault cla was saved by a newer MetaList (database version 19).",
    )
    assert isinstance(refused, VaultNeedsNewerMetaList)
    assert str(refused) == "Vault cla was saved by a newer MetaList (database version 19)."
    other = namespace_switcher.child_exit_error(namespace="cla", exit_code=1, log_path=tmp_path / "x.log", log_tail="boom")
    assert type(other) is RuntimeError and "exited with code 1" in str(other)


def test_the_command_says_it_plainly_and_stops(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(argv: list[str]) -> None:
        raise VaultNeedsNewerMetaList("Vault cla was saved by a newer MetaList. Update MetaList to open it.")

    monkeypatch.setattr(main_module, "main", refuse)
    monkeypatch.setattr(sys, "argv", ["metalist"])
    monkeypatch.delenv("METALIST_ORCHESTRATED_CHILD", raising=False)
    with pytest.raises(SystemExit) as stopped:
        main_module.cli()
    assert stopped.value.code == EXIT_VAULT_NEEDS_NEWER_METALIST
    assert capsys.readouterr().err.strip() == "Vault cla was saved by a newer MetaList. Update MetaList to open it."


# Every way of opening a vault sets up its tables through initialize_schema: the refusal is there too.
def test_no_tables_are_set_up_in_a_newer_vault(tmp_path: Path) -> None:
    from app.db.schema import initialize_schema

    database_path = _vault(tmp_path, namespace="cla", version=_NEWER)
    before = _fingerprint(database_path.parent)
    with closing(sqlite3.connect(database_path)) as connection:
        with pytest.raises(VaultNeedsNewerMetaList, match="Vault cla was saved by a newer MetaList"):
            initialize_schema(connection)
    assert _fingerprint(database_path.parent) == before


# The launcher and a vault's server read the vault's ports first (its launch profile): that read
# opened the vault for writing and set up its tables before anything checked its version.
def test_reading_a_newer_vaults_ports_refuses_it_untouched(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app import server_runtime

    database_path = _vault(tmp_path, namespace="cla", version=_NEWER)
    before = _fingerprint(database_path.parent)
    monkeypatch.setattr(server_runtime, "resolve_namespaced_database_path", lambda *, namespace: database_path)
    with pytest.raises(VaultNeedsNewerMetaList, match="Vault cla was saved by a newer MetaList"):
        server_runtime.load_namespace_launch_profile(namespace="cla")
    assert _fingerprint(database_path.parent) == before
