"""scripts/full_checks.py keeps only the newest runs' log folders (docs/ready-to-build/unbounded-growth-audit.md, T3)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "full_checks.py"


def _full_checks() -> ModuleType:
    spec = importlib.util.spec_from_file_location("full_checks_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses look their module up by name.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_folder(check_logs: Path, name: str) -> Path:
    folder = check_logs / name
    folder.mkdir()
    (folder / "pytest-local.log").write_text("passed\n", encoding="utf-8")
    return folder


def test_a_run_keeps_the_newest_run_folders_by_their_time(tmp_path: Path) -> None:
    full_checks = _full_checks()
    names = [f"202610{day:02d}T120000" for day in range(1, 16)]
    # Made out of order: the folder's name is its run's time, not when it was made.
    for name in reversed(names):
        _run_folder(tmp_path, name)
    removed = full_checks.remove_old_run_logs(tmp_path, full_checks.KEPT_RUN_LOGS)
    assert full_checks.KEPT_RUN_LOGS == 10
    assert [folder.name for folder in removed] == names[:5]
    assert sorted(entry.name for entry in tmp_path.iterdir()) == names[5:]


def test_fewer_runs_than_kept_are_all_kept(tmp_path: Path) -> None:
    full_checks = _full_checks()
    _run_folder(tmp_path, "20261101T090000")
    assert full_checks.remove_old_run_logs(tmp_path, full_checks.KEPT_RUN_LOGS) == []
    assert [entry.name for entry in tmp_path.iterdir()] == ["20261101T090000"]


def test_only_run_folders_are_touched(tmp_path: Path) -> None:
    full_checks = _full_checks()
    for day in range(1, 4):
        _run_folder(tmp_path, f"202610{day:02d}T120000")
    others = [_run_folder(tmp_path, "notes"), _run_folder(tmp_path, "20261001T1200")]
    (tmp_path / "20260101T000000").write_text("a file named as a run is not a run folder\n", encoding="utf-8")
    removed = full_checks.remove_old_run_logs(tmp_path, 1)
    assert [folder.name for folder in removed] == ["20261001T120000", "20261002T120000"]
    assert all(other.is_dir() for other in others)
    assert (tmp_path / "20260101T000000").is_file()
    assert (tmp_path / "20261003T120000").is_dir()


def test_the_run_that_is_starting_is_always_kept(tmp_path: Path) -> None:
    full_checks = _full_checks()
    with pytest.raises(ValueError, match="keep must be at least 1"):
        full_checks.remove_old_run_logs(tmp_path, 0)
