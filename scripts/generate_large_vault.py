#!/usr/bin/env python3
"""A large vault for scale checks (docs/future-plans/scale-testing.md, part 1): N notes written straight
into a fresh data folder's default namespace, deterministic from a seed, in seconds (the
import path takes a minute per 100,000 notes). A mix of short and long notes, trees three
deep, folder tags, a few tables and diagrams, so search, scopes and rendering all have work;
every tenth note starts with the word "Harbor" (in no other), so a search for it matches a
known share.
With --files, a folder of Markdown files for the import flow is written beside the vault.

    .venv/bin/python scripts/generate_large_vault.py --notes 100000 --data-dir /abs/folder [--seed 1] [--files 1200]

The folder must hold no vault yet: an existing one is never touched.
"""

from __future__ import annotations

import argparse
import html
import os
import random
import sqlite3
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_NAMESPACE = "default"
NAMESPACES_FOLDER = "namespaces"
# The import folder written beside the vault with --files, and its subfolders.
IMPORT_FILES_FOLDER = "import-files"
_IMPORT_SUBFOLDERS = ("", "Harbor", "Journal", "Reading")
SEARCH_WORD = "Harbor"
SEARCH_WORD_EVERY = 10
_COMMIT_EVERY = 5_000
_PROGRESS_EVERY = 10_000
_MAX_DEPTH = 3
_CHILDREN_CHANCE = 0.3
_FEWEST_CHILDREN = 1
_MOST_CHILDREN = 5
_FOLDER_TAG_CHANCE = 0.4
_TOPIC_TAG_CHANCE = 0.5
_FEWEST_LONG_NOTE_SENTENCES = 10
_MOST_LONG_NOTE_SENTENCES = 30
_FEWEST_SENTENCE_WORDS = 6
_MOST_SENTENCE_WORDS = 12
_FEWEST_TABLE_ROWS = 2
_MOST_TABLE_ROWS = 6
_FEWEST_DIAGRAM_STEPS = 3
_MOST_DIAGRAM_STEPS = 6
_FEWEST_FILE_SENTENCES = 3
_MOST_FILE_SENTENCES = 10
# The share of each kind of note, in a hundred.
_SHORT_NOTES_SHARE = 70
_LONG_NOTES_SHARE = 20
_TABLE_NOTES_SHARE = 5
_DIAGRAM_NOTES_SHARE = 5
_NOTE_KINDS = ("short", "long", "table", "diagram")
_NOTE_KIND_WEIGHTS = (_SHORT_NOTES_SHARE, _LONG_NOTES_SHARE, _TABLE_NOTES_SHARE, _DIAGRAM_NOTES_SHARE)
# The first note's creation time; each later note is a second younger.
_BASE_YEAR = 2026
_BASE_TIME = datetime(_BASE_YEAR, 1, 1, tzinfo=timezone.utc)
_UUID_BITS = 128
_UUID_VERSION = 4
_VOCABULARY = (
    "tide", "pool", "anemone", "crab", "kelp", "gull", "pier", "rope", "lantern", "fog", "chart", "compass",
    "ferry", "mooring", "net", "oar", "sail", "salt", "shell", "shore", "storm", "wave", "wind",
    "morning", "evening", "repair", "paint", "plank", "varnish", "engine", "radio", "weather", "tomorrow",
    "yesterday", "market", "bread", "coffee", "letter", "map", "walk", "cliff", "path", "bridge", "town",
    "village", "island", "boat", "captain", "crew", "journal", "note", "plan", "list", "idea", "question",
)
_FOLDERS = ("Projects/", "Projects/Harbor/", "Projects/Lighthouse/", "Journal/", "Journal/2026/", "Reading/", "Recipes/")
_TOPIC_TAGS = ("tide", "boats", "weather", "birds", "maps", "repairs", "trips", "recipes")
_TABLE_COLUMNS = ("Day", "Place", "Notes")
_MARKDOWN_TAG = "@markdown"
_DIAGRAM_TAG = "@mermaid"


@dataclass(slots=True)
class _Draft:
    note_id: str
    parent_id: str | None
    prev_id: str | None
    next_id: str | None
    content: str
    tags: str
    created_at: datetime


def _note_id(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(_UUID_BITS), version=_UUID_VERSION))


def _sentence(rng: random.Random) -> str:
    words = rng.choices(_VOCABULARY, k=rng.randint(_FEWEST_SENTENCE_WORDS, _MOST_SENTENCE_WORDS))
    return " ".join(words).capitalize() + "."


def _lines(kind: str, rng: random.Random) -> list[str]:
    if kind == "short":
        return [_sentence(rng)]
    if kind == "long":
        return [_sentence(rng) for _ in range(rng.randint(_FEWEST_LONG_NOTE_SENTENCES, _MOST_LONG_NOTE_SENTENCES))]
    if kind == "table":
        rows = [f"| {day} | {rng.choice(_VOCABULARY).capitalize()} | {_sentence(rng)} |"
                for day in range(1, rng.randint(_FEWEST_TABLE_ROWS, _MOST_TABLE_ROWS) + 1)]
        return [_sentence(rng), "", "| " + " | ".join(_TABLE_COLUMNS) + " |", "| --- | --- | --- |", *rows]
    assert kind == "diagram", kind
    steps = [rng.choice(_VOCABULARY).capitalize() for _ in range(rng.randint(_FEWEST_DIAGRAM_STEPS, _MOST_DIAGRAM_STEPS))]
    return ["graph TD", *(f"  {earlier} --> {later}" for earlier, later in zip(steps, steps[1:]))]


def _tags(kind: str, rng: random.Random) -> str:
    tags = []
    if kind == "table":
        tags.append(_MARKDOWN_TAG)
    if kind == "diagram":
        tags.append(_DIAGRAM_TAG)
    if rng.random() < _FOLDER_TAG_CHANCE:
        tags.append(rng.choice(_FOLDERS))
    if rng.random() < _TOPIC_TAG_CHANCE:
        tags.append(rng.choice(_TOPIC_TAGS))
    return " ".join(tags)


def _html(lines: list[str]) -> str:
    return "".join("<div><br></div>" if line == "" else f"<div>{html.escape(line)}</div>" for line in lines)


def plan_notes(count: int, rng: random.Random) -> list[_Draft]:
    """The notes in the order they are written: each parent before its children, siblings
    linked in order."""
    if count <= 0:
        raise ValueError(f"a vault has at least one note, asked for {count}")
    drafts: list[_Draft] = []

    def make(parent: _Draft | None, prev: _Draft | None) -> _Draft:
        index = len(drafts)
        kind = rng.choices(_NOTE_KINDS, weights=_NOTE_KIND_WEIGHTS)[0]
        lines = _lines(kind, rng)
        if index % SEARCH_WORD_EVERY == 0:
            lines[0] = f"{SEARCH_WORD} {lines[0]}"
        parent_id = None
        if parent is not None:
            parent_id = parent.note_id
        prev_id = None
        if prev is not None:
            prev_id = prev.note_id
        draft = _Draft(note_id=_note_id(rng), parent_id=parent_id, prev_id=prev_id, next_id=None,
                       content=_html(lines), tags=_tags(kind, rng), created_at=_BASE_TIME + timedelta(seconds=index))
        if prev is not None:
            prev.next_id = draft.note_id
        drafts.append(draft)
        return draft

    def add_children(parent: _Draft, depth: int) -> None:
        if depth >= _MAX_DEPTH or rng.random() >= _CHILDREN_CHANCE:
            return
        prev: _Draft | None = None
        for _ in range(rng.randint(_FEWEST_CHILDREN, _MOST_CHILDREN)):
            if len(drafts) >= count:
                return
            child = make(parent, prev)
            add_children(child, depth + 1)
            prev = child

    last_root: _Draft | None = None
    while len(drafts) < count:
        root = make(None, last_root)
        add_children(root, 1)
        last_root = root
    if len(drafts) != count:
        raise RuntimeError(f"planned {len(drafts)} notes for {count}")
    return drafts


def write_vault(*, data_dir: Path, drafts: list[_Draft]) -> Path:
    """Writes the notes into the default namespace's database under data_dir, which must hold
    no vault; the database's path."""
    if not data_dir.is_absolute():
        raise ValueError(f"the data folder must be an absolute path, got {data_dir}")
    if (data_dir / NAMESPACES_FOLDER).exists():
        raise FileExistsError(f"{data_dir} already holds a vault ({NAMESPACES_FOLDER}/): this script never touches an existing one")
    os.environ["METALIST_DATA_DIRECTORY"] = str(data_dir)
    # Imported here, not at the top: app.server_runtime reads the data directory from the
    # environment when it is imported, and that directory is this call's argument.
    from app.db.notes_sql import insert_note
    from app.db.schema import initialize_schema
    from app.server_runtime import prepare_database_runtime_path, resolve_namespaced_database_path

    database_path = resolve_namespaced_database_path(namespace=DEFAULT_NAMESPACE)
    prepare_database_runtime_path(database_path=database_path)
    connection = sqlite3.connect(database_path)
    initialize_schema(connection)
    started = time.perf_counter()
    for number, draft in enumerate(drafts, 1):
        insert_note(
            connection, note_id=draft.note_id, content=draft.content, encryption_nonce=None, encryption_tag=None,
            tags=draft.tags, tags_encryption_nonce=None, tags_encryption_tag=None, proposed_tags="",
            proposed_tags_encryption_nonce=None, proposed_tags_encryption_tag=None, parent_id=draft.parent_id,
            prev_id=draft.prev_id, next_id=draft.next_id, is_collapsed=False, created_at=draft.created_at,
            updated_at=draft.created_at,
        )
        if number % _COMMIT_EVERY == 0:
            connection.commit()
        if number % _PROGRESS_EVERY == 0:
            print(f"{number:,} of {len(drafts):,} notes written ({time.perf_counter() - started:.1f} s)", flush=True)
    connection.commit()
    connection.close()
    return database_path


def write_import_files(*, folder: Path, count: int, rng: random.Random) -> None:
    """count Markdown files in folder and its subfolders, each with a heading, a few
    sentences and a link to another of the files."""
    if count <= 0:
        raise ValueError(f"an import folder has at least one file, asked for {count}")
    titles = [f"Note {number:05d}" for number in range(1, count + 1)]
    for title in titles:
        subfolder = folder / rng.choice(_IMPORT_SUBFOLDERS)
        subfolder.mkdir(parents=True, exist_ok=True)
        sentences = " ".join(_sentence(rng) for _ in range(rng.randint(_FEWEST_FILE_SENTENCES, _MOST_FILE_SENTENCES)))
        (subfolder / f"{title}.md").write_text(
            f"# {title}\n\n{sentences}\n\nSee [[{rng.choice(titles)}]].\n", encoding="utf-8",
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--notes", type=int, required=True, help="how many notes to write")
    parser.add_argument("--data-dir", required=True, help="the data folder (absolute), with no vault in it yet")
    parser.add_argument("--seed", type=int, default=1, help="the random seed: the same seed writes the same vault")
    parser.add_argument("--files", type=int, default=0, help=f"how many Markdown files to write in {IMPORT_FILES_FOLDER}/")
    arguments = parser.parse_args(argv)
    if arguments.notes <= 0:
        parser.error("--notes must be above 0")
    if arguments.files < 0:
        parser.error("--files must be 0 or above")
    data_dir = Path(arguments.data_dir)
    if not data_dir.is_absolute():
        parser.error("--data-dir must be an absolute path")

    rng = random.Random(arguments.seed)
    started = time.perf_counter()
    drafts = plan_notes(arguments.notes, rng)
    database_path = write_vault(data_dir=data_dir, drafts=drafts)
    roots = sum(1 for draft in drafts if draft.parent_id is None)
    print(f"Wrote {len(drafts):,} notes ({roots:,} at the top) to {database_path} in {time.perf_counter() - started:.1f} s")
    if arguments.files > 0:
        files_folder = data_dir / IMPORT_FILES_FOLDER
        write_import_files(folder=files_folder, count=arguments.files, rng=rng)
        print(f"Wrote {arguments.files:,} Markdown files to {files_folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
