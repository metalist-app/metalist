"""A backup holds the vault's AI conversation as it was then, and a restore brings it back in place
of the current one (docs/ui/ai-chat.md, "Saved with the vault"): the real backup and restore, then
the runtime reset the restore route runs."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.api.routes import auth as auth_routes
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.security.sensitive_cache import enable_sensitive_caches
from app.services import auth_service
from app.services.ai_chat import NO_REQUEST, ai_chat_store
from app.services.backup_service import create_timestamped_backup_for_paths, restore_backup_to_paths
from app.services.content_cache import clear_cache
from app.services.file_registry import file_registry
from app.services.link_titles import link_title_store
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store


@pytest.fixture
def plaintext_vault(tmp_path, monkeypatch):
    database_path = tmp_path / "fixture.metalist.db"
    monkeypatch.setattr(SafeSession, "_db_path", database_path)
    monkeypatch.setattr(SafeSession, "_use_memory", False)
    clear_encryption_key()
    set_encryption_required(False)
    enable_sensitive_caches()
    clear_cache()
    store.reset()
    file_registry.reset()
    session = SafeSession()
    auth_service.AuthService(session).initialize_settings()
    bootstrap_ontology_rules_store(connection=session.connection())
    session.commit()
    with SafeSession.allow_reads("tests:ai_chat_restore"):
        ai_chat_store.bootstrap(connection=session.connection())
    session.close()
    yield database_path
    ai_chat_store.clear()
    # The restore read the vault's link titles: later tests expect none being looked up.
    link_title_store.reset()
    store.reset()
    clear_cache()
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)
    enable_sensitive_caches()


def _ask(question: str) -> None:
    turn = ai_chat_store.start_turn(user_content=question, provider="openai", model="gpt-5.6-sol")
    ai_chat_store.complete_turn(turn_id=turn, final_content=f"Answer to: {question}", actions=[],
                                request_tokens=NO_REQUEST)


def _questions() -> list[str]:
    return [message["content"] for message in ai_chat_store.snapshot()["messages"] if message["role"] == "user"]


def _back_up(database_path: Path, backup_directory: Path) -> Path:
    backup = create_timestamped_backup_for_paths(database_path, backup_directory)
    return backup_directory / backup.filename


def test_a_restore_brings_back_the_chat_the_backup_holds(plaintext_vault: Path, tmp_path: Path) -> None:
    _ask("Asked before the backup")
    backup_path = _back_up(plaintext_vault, tmp_path / "backups")
    ai_chat_store.clear()
    _ask("Asked after the backup")

    restore_backup_to_paths(backup_path, plaintext_vault)
    auth_routes._reset_runtime_state_after_restore()

    # The backup's conversation, in place of the current one: not merged.
    assert _questions() == ["Asked before the backup"]


def test_a_backup_made_with_no_chat_restores_none(plaintext_vault: Path, tmp_path: Path) -> None:
    backup_path = _back_up(plaintext_vault, tmp_path / "backups")
    _ask("Asked after the backup")

    restore_backup_to_paths(backup_path, plaintext_vault)
    auth_routes._reset_runtime_state_after_restore()

    assert _questions() == []
