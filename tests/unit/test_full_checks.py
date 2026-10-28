"""scripts/full_checks.py tests the Python versions the release matrix does."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _supported_pythons(script: str) -> tuple[str, ...]:
    tree = ast.parse((_SCRIPTS / script).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and [target.id for target in node.targets if isinstance(target, ast.Name)] == ["SUPPORTED_PYTHONS"]:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{script} defines no SUPPORTED_PYTHONS")


def test_the_full_checks_run_the_release_matrix_pythons() -> None:
    assert _supported_pythons("full_checks.py") == _supported_pythons("release.py")


def _string_constant(script: str, name: str) -> str:
    tree = ast.parse((_SCRIPTS / script).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and [target.id for target in node.targets if isinstance(target, ast.Name)] == [name]:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{script} defines no {name}")


def test_notes_dropped_in_the_inbox_do_not_count_as_uncommitted(tmp_path: Path) -> None:
    # The maintainer drops design notes into docs/inbox at any time; they stopped the full
    # checks and the 0.25.0 release (2026-10-28). Anything else uncommitted still counts.
    pathspec = _string_constant("full_checks.py", "INBOX_PATHSPEC")
    assert pathspec == _string_constant("release.py", "INBOX_PATHSPEC")
    run = lambda *arguments: subprocess.run(("git", *arguments), cwd=tmp_path, capture_output=True, encoding="utf-8", check=True).stdout  # noqa: E731
    run("init", "-q")
    (tmp_path / "docs" / "inbox").mkdir(parents=True)
    (tmp_path / "docs" / "inbox" / "2026-10-28-note.md").write_text("# A note\n", encoding="utf-8")
    assert run("status", "--porcelain", "--", ".", pathspec) == ""
    (tmp_path / "stray.py").write_text("x = 1\n", encoding="utf-8")
    assert run("status", "--porcelain", "--", ".", pathspec) == "?? stray.py\n"
