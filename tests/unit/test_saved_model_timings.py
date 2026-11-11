"""Each model's timing saved in the vault (the maintainer, 2026-11-08), so a summary's bar moves
from its first second: database version 16 adds an encrypted payload beside the saved rate limits
(app_settings.model_timings_json)."""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

import pytest

from app.db.migrations import MODEL_TIMING_COLUMNS, run_database_migrations
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
from app.services.agent.saved_rate_limits import DatabaseSavedTimings
from app.services.agent.staged_summary import ModelTiming
from app.services.client_state_service import rewrite_client_state_storage
from app.services.encryption import EncryptionService

NEW_COLUMNS = {column for column, _sql_type in MODEL_TIMING_COLUMNS}
OPENAI = "https://api.openai.com/v1"
ANTHROPIC = "https://api.anthropic.com"
FAST = ModelTiming(startup_seconds=4.5, seconds_per_million_tokens=80.0)
SLOW = ModelTiming(startup_seconds=12.0, seconds_per_million_tokens=300.0)


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
        with SafeSession.allow_reads("tests:saved_model_timings"):
            settings = fetch_settings(session.connection())
    finally:
        session.close()
    assert settings is not None
    return settings["model_timings_json"], settings["model_timings_encryption_nonce"], settings["model_timings_encryption_tag"]


@pytest.mark.parametrize("encrypted", [False, True], ids=["no password", "password"])
def test_each_models_timing_is_saved_and_read_back(memory_settings_db, encrypted: bool) -> None:
    if encrypted:
        set_encryption_required(True)
        set_session_dek(b"d" * 32)
    store = DatabaseSavedTimings()
    assert store.load(base_url=OPENAI, model="gpt-5.6-sol") is None

    store.save(base_url=OPENAI, model="gpt-5.6-sol", timing=SLOW)
    store.save(base_url=ANTHROPIC, model="claude-opus-5-5", timing=SLOW)
    store.save(base_url=OPENAI, model="gpt-5.6-sol", timing=FAST)

    assert store.load(base_url=OPENAI, model="gpt-5.6-sol") == FAST
    assert store.load(base_url=ANTHROPIC, model="claude-opus-5-5") == SLOW
    assert store.load(base_url=OPENAI, model="gpt-6-luna") is None
    stored_json, nonce, tag = _stored_payload()
    assert (nonce is not None, tag is not None) == (encrypted, encrypted)
    assert ("gpt-5.6-sol" in stored_json) is not encrypted


def test_setting_and_removing_a_password_rewrites_them(memory_settings_db) -> None:
    store = DatabaseSavedTimings()
    store.save(base_url=OPENAI, model="gpt-5.6-sol", timing=FAST)
    set_encryption_required(True)
    set_session_dek(b"d" * 32)

    with begin_writer() as connection:
        rewrite_client_state_storage(connection=connection, encryption_service=get_encryption_service(), force_plaintext=False)
    stored_json, nonce, _tag = _stored_payload()
    assert nonce is not None and "gpt-5.6-sol" not in stored_json
    assert store.load(base_url=OPENAI, model="gpt-5.6-sol") == FAST

    with begin_writer() as connection:
        rewrite_client_state_storage(connection=connection, encryption_service=get_encryption_service(), force_plaintext=True)
    stored_json, nonce, _tag = _stored_payload()
    assert nonce is None and "gpt-5.6-sol" in stored_json


def _version_15_namespace(tmp_path: Path, *, kept_columns: set[str]) -> Path:
    """A version-15 notes database whose app_settings has only kept_columns of the new ones
    (the on-open schema helper may have added some or all of them already)."""
    notes = tmp_path / "fixture.metalist.db"
    with closing(sqlite3.connect(notes)) as connection:
        initialize_schema(connection)
        insert_default_settings(connection)
        for column in sorted(NEW_COLUMNS - kept_columns):
            connection.execute(f"ALTER TABLE app_settings DROP COLUMN {column}")
        connection.execute("PRAGMA user_version = 15")
        connection.commit()
    return notes


@pytest.mark.parametrize("encrypted", [False, True])
@pytest.mark.parametrize("kept_columns", [set(), {"model_timings_json"}, NEW_COLUMNS], ids=["none", "some", "all"])
def test_version_15_gains_the_saved_model_timings(tmp_path: Path, encrypted: bool, kept_columns: set[str]) -> None:
    notes = _version_15_namespace(tmp_path, kept_columns=kept_columns)
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

    assert CURRENT_DATABASE_VERSION == 18
    assert migrate() == (16, 17, 18)
    assert migrate() == ()
    with closing(sqlite3.connect(notes)) as connection:
        row = connection.execute("SELECT model_timings_json FROM app_settings").fetchone()
    # Nothing saved yet: a model's first finished summary saves its timing.
    assert row == (None,)
