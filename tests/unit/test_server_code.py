"""The server says when the Python code on disk changed since it started (asked for
2026-10-30), so a page newer than its server explains its errors (error-overlay.js)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import server_code


def test_the_server_notices_its_code_changed_on_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "app").mkdir()
    module = tmp_path / "app" / "module.py"
    module.write_text("VALUE = 1\n")
    monkeypatch.setattr(server_code, "_ROOT", tmp_path)
    monkeypatch.setattr(server_code, "_STARTED_WITH", server_code._code_fingerprint())
    assert server_code.is_server_code_stale() is False

    module.write_text("VALUE = 2  # a longer line\n")
    assert server_code.is_server_code_stale() is True


def test_a_new_file_counts_as_a_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "app").mkdir()
    monkeypatch.setattr(server_code, "_ROOT", tmp_path)
    monkeypatch.setattr(server_code, "_STARTED_WITH", server_code._code_fingerprint())
    (tmp_path / "app" / "added.py").write_text("")
    assert server_code.is_server_code_stale() is True


def test_this_server_runs_the_code_on_disk() -> None:
    assert server_code.is_server_code_stale() is False
