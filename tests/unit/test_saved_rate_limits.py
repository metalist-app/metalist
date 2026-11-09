"""Each model's rate limits saved in the vault (the maintainer, 2026-11-08), so a restart starts
with them instead of four batches at once until a first answer reports them: database version
15 adds an encrypted payload beside the API keys (app_settings.provider_rate_limits_json)."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.db.migrations import PROVIDER_RATE_LIMIT_COLUMNS, run_database_migrations
from app.db.schema import initialize_schema
from app.db.session import begin_writer
from app.db.settings_sql import fetch_settings, insert_default_settings
from app.db.version import CURRENT_DATABASE_VERSION
from app.models.database import SafeSession
from app.security.encryption import (
    clear_encryption_key,
    get_encryption_service,
    set_encryption_required,
    set_session_dek,
)
from app.services.agent.provider_limits import SavedLimits
from app.services.agent.saved_rate_limits import DatabaseSavedLimits
from app.services.client_state_service import rewrite_client_state_storage
from app.services.encryption import EncryptionService

NEW_COLUMNS = {column for column, _sql_type in PROVIDER_RATE_LIMIT_COLUMNS}
OPENAI = "https://api.openai.com/v1"
ANTHROPIC = "https://api.anthropic.com"


@pytest.fixture
def memory_settings_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    try:
        yield
    finally:
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()


def _stored_payload() -> tuple[object, object, object]:
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:saved_rate_limits"):
            settings = fetch_settings(session.connection())
    finally:
        session.close()
    assert settings is not None
    return (settings["provider_rate_limits_json"], settings["provider_rate_limits_encryption_nonce"],
            settings["provider_rate_limits_encryption_tag"])


@pytest.mark.parametrize("encrypted", [False, True], ids=["no password", "password"])
def test_each_models_limits_are_saved_and_read_back(memory_settings_db, encrypted: bool) -> None:
    if encrypted:
        set_encryption_required(True)
        set_session_dek(b"d" * 32)
    store = DatabaseSavedLimits()
    assert store.load(base_url=OPENAI, model="gpt-5.6-sol") is None

    store.save(base_url=OPENAI, model="gpt-5.6-sol", limits=SavedLimits(request_limit=30_000, token_limit=180_000_000))
    store.save(base_url=ANTHROPIC, model="claude-opus-5-5", limits=SavedLimits(request_limit=4_000, token_limit=2_000_000))
    store.save(base_url=OPENAI, model="gpt-5.6-sol", limits=SavedLimits(request_limit=10_000, token_limit=30_000_000))

    assert store.load(base_url=OPENAI, model="gpt-5.6-sol") == SavedLimits(request_limit=10_000, token_limit=30_000_000)
    assert store.load(base_url=ANTHROPIC, model="claude-opus-5-5") == SavedLimits(request_limit=4_000, token_limit=2_000_000)
    assert store.load(base_url=OPENAI, model="gpt-6-luna") is None
    stored_json, nonce, tag = _stored_payload()
    assert (nonce is not None, tag is not None) == (encrypted, encrypted)
    # Which models you use is as private as the rest of your AI settings.
    assert ("gpt-5.6-sol" in stored_json) is not encrypted


def test_setting_and_removing_a_password_rewrites_them(memory_settings_db) -> None:
    store = DatabaseSavedLimits()
    store.save(base_url=OPENAI, model="gpt-5.6-sol", limits=SavedLimits(request_limit=30_000, token_limit=180_000_000))
    set_encryption_required(True)
    set_session_dek(b"d" * 32)

    with begin_writer() as connection:
        rewrite_client_state_storage(connection=connection, encryption_service=get_encryption_service(), force_plaintext=False)
    stored_json, nonce, _tag = _stored_payload()
    assert nonce is not None and "gpt-5.6-sol" not in stored_json
    assert store.load(base_url=OPENAI, model="gpt-5.6-sol") == SavedLimits(request_limit=30_000, token_limit=180_000_000)

    with begin_writer() as connection:
        rewrite_client_state_storage(connection=connection, encryption_service=get_encryption_service(), force_plaintext=True)
    stored_json, nonce, _tag = _stored_payload()
    assert nonce is None and "gpt-5.6-sol" in stored_json


def _version_14_namespace(tmp_path: Path, *, kept_columns: set[str]) -> Path:
    """A version-14 notes database whose app_settings has only kept_columns of the new ones
    (the on-open schema helper may have added some or all of them already)."""
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        for column in sorted(NEW_COLUMNS - kept_columns):
            connection.execute(f"ALTER TABLE app_settings DROP COLUMN {column}")
        connection.execute("PRAGMA user_version = 14")
        connection.commit()
    return notes


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("kept_columns", [set(), {"provider_rate_limits_json"}, NEW_COLUMNS], ids=["none", "some", "all"])
def test_version_14_gains_the_saved_rate_limits(tmp_path: Path, encrypted: bool, kept_columns: set[str]) -> None:
    notes = _version_14_namespace(tmp_path, kept_columns=kept_columns)
    service = None
    if encrypted:
        service = EncryptionService()
        service.dek = b"k" * 32

    def migrate() -> tuple[int, ...]:
        with closing(sqlite3.connect(notes)) as connection:
            with connection:
                result = run_database_migrations(connection=connection, encryption_enabled=encrypted, encryption_service=service)
            assert connection.execute("PRAGMA user_version").fetchone()[0] == CURRENT_DATABASE_VERSION
            assert NEW_COLUMNS <= {row[1] for row in connection.execute("PRAGMA table_info(app_settings)")}
            return result.applied_versions

    assert migrate() == (15, 16, 17)
    assert migrate() == ()
    with closing(sqlite3.connect(notes)) as connection:
        row = connection.execute("SELECT provider_rate_limits_json FROM app_settings").fetchone()
    # Nothing saved yet: the first answer from each model saves its limits.
    assert row == (None,)
