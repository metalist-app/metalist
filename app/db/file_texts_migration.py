"""Migration 12→13: the files database gains the encrypted `file_texts` table, a file's text
kept for search (docs/ready-to-build/folder-import-and-file-previews.md, "Searchable file text").

Opening a files database also adds it (see `initialize_file_schema`), so this step is
idempotent; it exists so the upgrade is recorded in the namespace version like every other
schema change, and so the encryption audit can require the table from version 13 on.
"""

from contextlib import closing
from pathlib import Path
import sqlite3

from app.db.file_schema import FILE_TEXTS_COLUMNS, FILE_TEXTS_TABLE, create_file_texts_table

# Same shared in-memory database FileSession uses when the notes database is in memory.
_FILE_MEMORY_URI = "file:metalist_files_memory?mode=memory&cache=shared"
# PRAGMA database_list rows are (seq, name, file); PRAGMA table_info rows are (cid, name, ...).
_DATABASE_LIST_FILE_COLUMN = 2
_TABLE_INFO_NAME_COLUMN = 1


def _upgrade(files: sqlite3.Connection) -> None:
    create_file_texts_table(files)
    files.commit()
    columns = {row[_TABLE_INFO_NAME_COLUMN] for row in files.execute(f"PRAGMA table_info({FILE_TEXTS_TABLE})").fetchall()}
    if columns != set(FILE_TEXTS_COLUMNS):
        raise RuntimeError(f"Database migration 12→13 found a {FILE_TEXTS_TABLE} table with other columns: {sorted(columns)}")


def add_file_texts_table(
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
