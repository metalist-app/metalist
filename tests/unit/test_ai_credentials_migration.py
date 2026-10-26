"""Migration 10→11: an encrypted API-key slot for Claude (anthropic) and Gemini beside
OpenAI's, and the encryption audit before and after it."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.db.migrations import AI_PROVIDER_CREDENTIAL_COLUMNS, run_database_migrations
from app.db.schema import initialize_schema
from app.db.settings_sql import insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION
from app.services.encryption import EncryptionService

NEW_COLUMNS = {column for column, _sql_type in AI_PROVIDER_CREDENTIAL_COLUMNS}
GEMINI_COLUMNS = {column for column in NEW_COLUMNS if column.startswith("gemini_")}


def _app_settings_columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(app_settings)")}


def _version_10_namespace(tmp_path: Path, *, kept_columns: set[str]) -> Path:
    """A version-10 notes database whose app_settings has only kept_columns of the new ones
    (the on-open schema helper may have added some or all of them already)."""
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        for column in sorted(NEW_COLUMNS - kept_columns):
            connection.execute(f"ALTER TABLE app_settings DROP COLUMN {column}")
        connection.execute("PRAGMA user_version = 10")
        connection.commit()
    return notes


def _migrate(notes: Path, *, encrypted: bool) -> tuple[int, ...]:
    service = None
    if encrypted:
        service = EncryptionService()
        service.dek = b"k" * 32
    with closing(sqlite3.connect(notes)) as connection:
        with connection:
            result = run_database_migrations(connection=connection, encryption_enabled=encrypted, encryption_service=service)
        assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
        assert NEW_COLUMNS <= _app_settings_columns(connection)
        return result.applied_versions


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("kept_columns", [set(), NEW_COLUMNS - GEMINI_COLUMNS, NEW_COLUMNS], ids=["none", "some", "all"])
def test_version_10_gains_the_claude_and_gemini_key_slots(tmp_path: Path, encrypted: bool, kept_columns: set[str]) -> None:
    notes = _version_10_namespace(tmp_path, kept_columns=kept_columns)
    with closing(sqlite3.connect(notes)) as connection:
        connection.execute(
            "UPDATE app_settings SET openai_api_key_ciphertext = 'kept', openai_api_key_encryption_nonce = x'01', "
            "openai_api_key_encryption_tag = x'02' WHERE id = 1"
        )
        connection.commit()

    assert _migrate(notes, encrypted=encrypted) == (11, 12)
    assert _migrate(notes, encrypted=encrypted) == ()

    with closing(sqlite3.connect(notes)) as connection:
        row = connection.execute(
            "SELECT openai_api_key_ciphertext, anthropic_api_key_ciphertext, gemini_api_key_ciphertext FROM app_settings"
        ).fetchone()
    # The OpenAI key stays where it was; the new slots start empty.
    assert row == ("kept", None, None)
