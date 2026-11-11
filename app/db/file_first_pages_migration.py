"""Migration 17→18: a vault's files catalog gains `file_first_pages`, a PDF's first page drawn as a
picture for galleries (docs/future-plans/gallery.md, "PDF first pages").

Opening the catalog also adds it (see `initialize_file_schema`), so this step is idempotent; it
exists so the upgrade is recorded in the namespace version like every other schema change, and so
the encryption audit can require the table from version 18 on.
"""

from contextlib import closing
from pathlib import Path
import sqlite3

from app.db.blob_store import resolve_file_catalog_path
from app.db.file_schema import FILE_FIRST_PAGES_COLUMNS, FILE_FIRST_PAGES_TABLE, create_file_first_pages_table

# PRAGMA database_list rows are (seq, name, file); PRAGMA table_info rows are (cid, name, ...).
_DATABASE_LIST_FILE_COLUMN = 2
_TABLE_INFO_NAME_COLUMN = 1


def _upgrade(catalog: sqlite3.Connection) -> None:
    create_file_first_pages_table(catalog)
    catalog.commit()
    columns = {row[_TABLE_INFO_NAME_COLUMN] for row in catalog.execute(f"PRAGMA table_info({FILE_FIRST_PAGES_TABLE})").fetchall()}
    if columns != set(FILE_FIRST_PAGES_COLUMNS):
        raise RuntimeError(f"Database migration 17→18 found a {FILE_FIRST_PAGES_TABLE} table with other columns: {sorted(columns)}")


def add_file_first_pages_table(
    *,
    connection: sqlite3.Connection,
    encryption_enabled: bool,  # noqa: ARG001
    encryption_service: object,  # noqa: ARG001
) -> int:
    database = connection.execute("PRAGMA database_list").fetchone()[_DATABASE_LIST_FILE_COLUMN]
    # An in-memory notes database's catalog is current from the start.
    if not database:
        return 0
    catalog_path = resolve_file_catalog_path(Path(database))
    # A vault that never stored a file gets the current schema when its catalog is created.
    if not catalog_path.exists():
        return 0
    with closing(sqlite3.connect(catalog_path)) as catalog:
        _upgrade(catalog)
    return 0
