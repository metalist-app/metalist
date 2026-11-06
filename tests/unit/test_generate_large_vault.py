"""scripts/generate_large_vault.py: a vault of N notes, written in seconds, the same for the
same seed, never over an existing one."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
GENERATOR = REPOSITORY / "scripts" / "generate_large_vault.py"
NOTES = 300
FILES = 12
SEED = 7
# generate_large_vault.py: every tenth note starts with "Harbor", trees are three deep.
SEARCH_WORD_EVERY = 10
MAX_DEPTH = 3


def _generate(data_dir: Path, *, notes: int, files: int, seed: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--notes", str(notes), "--data-dir", str(data_dir), "--seed", str(seed),
         "--files", str(files)],
        cwd=REPOSITORY, env=dict(os.environ), capture_output=True, encoding="utf-8", check=False,
    )


def _rows(data_dir: Path) -> list[sqlite3.Row]:
    connection = sqlite3.connect(data_dir / "namespaces" / "default" / "default.metalist.db")
    connection.row_factory = sqlite3.Row
    rows = connection.execute("SELECT id, parent_id, prev_id, next_id, content, tags FROM notes ORDER BY rowid").fetchall()
    connection.close()
    return rows


def _depth(row_by_id: dict[str, sqlite3.Row], note_id: str) -> int:
    depth = 1
    while row_by_id[note_id]["parent_id"] is not None:
        note_id = row_by_id[note_id]["parent_id"]
        depth += 1
    return depth


def test_the_vault_is_written_parents_first_with_siblings_linked(tmp_path: Path) -> None:
    data_dir = tmp_path / "vault"
    completed = _generate(data_dir, notes=NOTES, files=FILES, seed=SEED)
    assert completed.returncode == 0, completed.stderr
    assert f"Wrote {NOTES} notes" in completed.stdout and f"Wrote {FILES} Markdown files" in completed.stdout

    rows = _rows(data_dir)
    assert len(rows) == NOTES
    row_by_id = {row["id"]: row for row in rows}
    written_before: set[str] = set()
    for row in rows:
        assert row["parent_id"] is None or row["parent_id"] in written_before, row["id"]
        written_before.add(row["id"])
        assert _depth(row_by_id, row["id"]) <= MAX_DEPTH
    children_by_parent: dict[str | None, list[sqlite3.Row]] = {}
    for row in rows:
        children_by_parent.setdefault(row["parent_id"], []).append(row)
    for parent_id, children in children_by_parent.items():
        chain = [child for child in children if child["prev_id"] is None]
        assert len(chain) == 1, parent_id
        while chain[-1]["next_id"] is not None:
            chain.append(row_by_id[chain[-1]["next_id"]])
            assert chain[-1]["parent_id"] == parent_id and chain[-1]["prev_id"] == chain[-2]["id"]
        assert len(chain) == len(children), parent_id

    harbor_rows = [index for index, row in enumerate(rows) if "harbor" in row["content"].lower()]
    assert harbor_rows == list(range(0, NOTES, SEARCH_WORD_EVERY))
    assert all(rows[index]["content"].startswith("<div>Harbor ") for index in harbor_rows)
    assert any("/" in row["tags"] for row in rows) and any("@markdown" in row["tags"] for row in rows)
    assert any("@mermaid" in row["tags"] for row in rows) and any(row["parent_id"] is not None for row in rows)
    assert len(list((data_dir / "import-files").rglob("*.md"))) == FILES


def test_the_same_seed_writes_the_same_vault(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    assert _generate(first, notes=NOTES, files=0, seed=SEED).returncode == 0
    assert _generate(second, notes=NOTES, files=0, seed=SEED).returncode == 0

    assert [tuple(row) for row in _rows(first)] == [tuple(row) for row in _rows(second)]


def test_an_existing_vault_is_never_written_over(tmp_path: Path) -> None:
    data_dir = tmp_path / "vault"
    assert _generate(data_dir, notes=NOTES, files=0, seed=SEED).returncode == 0
    before = [tuple(row) for row in _rows(data_dir)]

    completed = _generate(data_dir, notes=NOTES, files=0, seed=SEED)

    assert completed.returncode != 0 and "already holds a vault" in completed.stderr
    assert [tuple(row) for row in _rows(data_dir)] == before
