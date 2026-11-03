"""Migration 13→14: the files database records which versions of the reader and of the bloom
filter made a file's kept text (docs/ready-to-build/folder-import-and-file-previews.md, "Text
versions"), so a newer reader or filter redoes it.

`file_texts` gains `reader_version` and `filter_version` (1 for text kept before: the first
reader and filter made it). Opening a files database also adds them (see
`initialize_file_schema`), so this step is idempotent.
"""

from contextlib import closing
from pathlib import Path
import sqlite3

from app.db.file_schema import (
    FILE_TEXTS_COLUMNS,
    FILE_TEXTS_TABLE,
    add_file_texts_version_columns,
    create_file_texts_table,
)

# Same shared in-memory database FileSession uses when the notes database is in memory.
_FILE_MEMORY_URI = "file:metalist_files_memory?mode=memory&cache=shared"
# PRAGMA database_list rows are (seq, name, file); PRAGMA table_info rows are (cid, name, ...).
_DATABASE_LIST_FILE_COLUMN = 2
_TABLE_INFO_NAME_COLUMN = 1


def _columns(files: sqlite3.Connection, table: str) -> set[str]:
    return {row[_TABLE_INFO_NAME_COLUMN] for row in files.execute(f"PRAGMA table_info({table})").fetchall()}


def _upgrade(files: sqlite3.Connection) -> None:
    # A files database from before 12→13 opened by this step alone still lacks file_texts.
    create_file_texts_table(files)
    add_file_texts_version_columns(files)
    files.commit()
    if _columns(files, FILE_TEXTS_TABLE) != set(FILE_TEXTS_COLUMNS):
        raise RuntimeError(f"Database migration 13→14 left {FILE_TEXTS_TABLE} with other columns: {sorted(_columns(files, FILE_TEXTS_TABLE))}")


def add_text_versions(
    *,
    connection: sqlite3.Connection,
    encryption_enabled: bool,  # noqa: ARG001
    encryption_service: object,  # noqa: ARG001
) -> int:
    database = connection.execute("PRAGMA database_list").fetchone()[_DATABASE_LIST_FILE_COLUMN]
    if not database:
        with closing(sqlite3.connect(_FILE_MEMORY_URI, uri=True)) as files:
            _upgrade(files)
        return 0
    notes = Path(database)
    target = notes.with_name(f"{notes.stem}.files{notes.suffix}")
    # A namespace without attachments gets the current schema when its files database is created.
    if not target.exists():
        return 0
    with closing(sqlite3.connect(target)) as files:
        _upgrade(files)
    return 0
