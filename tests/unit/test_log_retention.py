"""The logs folder stays bounded: each vault keeps its newest 2 rotated server logs, and logs
of a vault that no longer exists go a day after they were last written (agreed 2026-11-11,
docs/ready-to-build/unbounded-growth-audit.md, L1-L6)."""

import os
from pathlib import Path

from loguru import logger

from app.services import log_retention
from app.utils.time_units import SECONDS_PER_DAY, SECONDS_PER_HOUR

NOW = 2_000_000_000.0
OLD = NOW - 2 * SECONDS_PER_DAY
FRESH = NOW - SECONDS_PER_HOUR


def _write(directory: Path, name: str, *, modified_at: float) -> Path:
    path = directory / name
    path.write_bytes(b"log line\n")
    os.utime(path, (modified_at, modified_at))
    return path


def _folders(tmp_path: Path, *vaults: str) -> tuple[Path, Path]:
    logs_directory = tmp_path / "logs"
    logs_directory.mkdir()
    namespaces_directory = tmp_path / "namespaces"
    namespaces_directory.mkdir()
    for vault in vaults:
        (namespaces_directory / vault).mkdir()
    return logs_directory, namespaces_directory


def _trim(logs_directory: Path, namespaces_directory: Path, *, own_vault: str) -> tuple[Path, ...]:
    return log_retention.trim_logs_directory(
        logs_directory=logs_directory,
        namespaces_directory=namespaces_directory,
        own_vault=own_vault,
        now=NOW,
    )


def _names(directory: Path) -> set[str]:
    return {path.name for path in directory.iterdir() if path.name != log_retention.LOCK_FILE_NAME}


def test_retention_keeps_the_newest_two_rotated_server_logs_and_never_the_fault_log(tmp_path: Path) -> None:
    names = [
        "work-server.2026-10-01_10-00-00_000001.log",
        "work-server.2026-10-02_10-00-00_000001.log",
        "work-server.2026-10-02_10-00-00_000001.2.log",
        "work-server.2026-10-03_10-00-00_000001.log",
        "work-server.fault.log",
        "work-server.log",
    ]
    paths = [_write(tmp_path, name, modified_at=OLD) for name in names]

    log_retention.retain_newest_rotated_server_logs([str(path) for path in paths])

    assert _names(tmp_path) == {
        "work-server.2026-10-02_10-00-00_000001.2.log",
        "work-server.2026-10-03_10-00-00_000001.log",
        "work-server.fault.log",
        "work-server.log",
    }


def test_loguru_rotation_with_this_retention_keeps_two_rotated_files_and_the_fault_log(tmp_path: Path) -> None:
    fault_log = _write(tmp_path, "work-server.fault.log", modified_at=OLD)
    sink_id = logger.add(
        str(tmp_path / "work-server.log"),
        rotation="200 B",
        retention=log_retention.retain_newest_rotated_server_logs,
        format="{message}",
    )
    try:
        for line_number in range(40):
            logger.info(f"line {line_number:03d} " + "x" * 40)
    finally:
        logger.remove(sink_id)

    rotated = [name for name in _names(tmp_path) if log_retention.is_rotated_server_log(name)]
    assert len(rotated) == log_retention.ROTATED_SERVER_LOGS_KEPT
    assert fault_log.exists()
    assert (tmp_path / "work-server.log").exists()


def test_logs_of_a_removed_vault_go_once_a_day_has_passed_since_their_last_write(tmp_path: Path) -> None:
    logs_directory, namespaces_directory = _folders(tmp_path, "work")
    for name in (
        "gone-server.log",
        "gone-server.fault.log",
        "gone-server.2026-10-01_10-00-00_000001.log",
        "namespace-gone.log",
        "namespace-delete-gone.log",
        "namespace-rename-gone-to-work.log",
        "ollama-managed.log",
    ):
        _write(logs_directory, name, modified_at=OLD)
    _write(logs_directory, "namespace-delete-recent.log", modified_at=FRESH)
    _write(logs_directory, "recent-server.log", modified_at=FRESH)

    deleted = _trim(logs_directory, namespaces_directory, own_vault="work")

    assert _names(logs_directory) == {"namespace-delete-recent.log", "recent-server.log"}
    assert len(deleted) == 7


def test_logs_of_existing_vaults_and_of_the_starting_vault_stay(tmp_path: Path) -> None:
    logs_directory, namespaces_directory = _folders(tmp_path, "work", "home")
    kept = {
        "work-server.log",
        "work-server.fault.log",
        "namespace-work.log",
        "home-server.log",
        "home-server.fault.log",
        "namespace-home.log",
        "namespace-delete-home.log",
        "namespace-rename-home-to-gone.log",
        # The vault starting now may have no folder yet; its child log is already open.
        "new-server.log",
        "namespace-new.log",
        # A rename log belongs to the vault it renamed; with "-to-" twice, the source is
        # "home" or "home-to-gone", and "home" exists.
        "namespace-rename-home-to-gone-to-x.log",
        # Not MetaList's naming: untouched. (Old encrypted logs go: the next test.)
        "notes.txt",
    }
    for name in kept:
        _write(logs_directory, name, modified_at=OLD)

    deleted = _trim(logs_directory, namespaces_directory, own_vault="new")

    assert deleted == ()
    assert _names(logs_directory) == kept


def test_a_file_any_of_whose_owners_exists_stays(tmp_path: Path) -> None:
    logs_directory, namespaces_directory = _folders(tmp_path, "x-server")
    # "namespace-x-server.log" is vault "namespace-x"'s server log or vault "x-server"'s child output.
    _write(logs_directory, "namespace-x-server.log", modified_at=OLD)

    assert _trim(logs_directory, namespaces_directory, own_vault="work") == ()
    assert _names(logs_directory) == {"namespace-x-server.log"}


def test_the_starting_vault_trims_its_own_rotated_logs_to_two_and_leaves_other_vaults_to_theirs(tmp_path: Path) -> None:
    logs_directory, namespaces_directory = _folders(tmp_path, "work", "home")
    for day in range(1, 6):
        _write(logs_directory, f"work-server.2026-10-0{day}_10-00-00_000001.log", modified_at=OLD)
        _write(logs_directory, f"home-server.2026-10-0{day}_10-00-00_000001.log", modified_at=OLD)

    deleted = _trim(logs_directory, namespaces_directory, own_vault="work")

    assert {path.name for path in deleted} == {
        "work-server.2026-10-01_10-00-00_000001.log",
        "work-server.2026-10-02_10-00-00_000001.log",
        "work-server.2026-10-03_10-00-00_000001.log",
    }
    assert len([name for name in _names(logs_directory) if name.startswith("home-server.2026")]) == 5


def test_a_folder_grown_past_every_bound_comes_back_to_the_bounded_set(tmp_path: Path) -> None:
    """The maintainer's Mac on 2026-11-11, in miniature: two live vaults, nine removed ones."""
    logs_directory, namespaces_directory = _folders(tmp_path, "thomas", "cla")
    removed = ("codex", "default", "obsidian", "obsidian-2", "obsidian-3", "obs-4", "temp", "test", "test2")
    for vault in removed:
        for name in (f"{vault}-server.log", f"{vault}-server.fault.log", f"namespace-{vault}.log"):
            _write(logs_directory, name, modified_at=OLD)
    for vault in ("thomas", "cla"):
        for name in (f"{vault}-server.log", f"{vault}-server.fault.log", f"namespace-{vault}.log"):
            _write(logs_directory, name, modified_at=OLD)
    for day in range(1, 8):
        _write(logs_directory, f"thomas-server.2026-10-0{day}_10-00-00_000001.log", modified_at=OLD)
    _write(logs_directory, "ollama-managed.log", modified_at=OLD)

    _trim(logs_directory, namespaces_directory, own_vault="thomas")

    assert _names(logs_directory) == {
        "thomas-server.log",
        "thomas-server.fault.log",
        "namespace-thomas.log",
        "thomas-server.2026-10-06_10-00-00_000001.log",
        "thomas-server.2026-10-07_10-00-00_000001.log",
        "cla-server.log",
        "cla-server.fault.log",
        "namespace-cla.log",
    }


def test_start_up_deletes_every_old_encrypted_log_and_nothing_named_like_one(tmp_path: Path) -> None:
    """Encrypted per-login logs were dropped 2026-11-11 and nothing could read them: the first
    start after an update deletes them, a fresh one too (decided 2026-11-12,
    docs/ready-to-build/error-reports.md section 6). Only that exact name goes."""
    logs_directory, namespaces_directory = _folders(tmp_path, "work")
    kept = {
        "work-server.log",
        "work-server.auth-notes.log.enc",
        "work-server.auth-20261111T230759.998258Z-105b8e5d87e331c4.log",
    }
    retired = {
        "work-server.auth-20261111T230759.998258Z-105b8e5d87e331c4.log.enc",
        "gone-server.auth-20260812T151011.164544Z-5339483b36930d47.log.enc",
    }
    for name in kept:
        _write(logs_directory, name, modified_at=FRESH)
    for name in retired:
        _write(logs_directory, name, modified_at=FRESH)

    deleted = _trim(logs_directory, namespaces_directory, own_vault="work")

    assert {path.name for path in deleted} == retired
    assert _names(logs_directory) == kept
