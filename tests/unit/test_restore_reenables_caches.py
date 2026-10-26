"""Restoring a backup switches the caches of note text off while the restored notes load
(disable_and_clear_sensitive_caches). Unlocking switches them back on (set_encryption_key),
but a vault without a password has no unlock: they stayed off until MetaList restarted, so
every such cache silently stopped caching, and `[[` suggestions, which keep the notes' text
only while the caches are on, found nothing (found 2026-10-26)."""

from __future__ import annotations

import pytest

from app.api.routes import auth as auth_routes
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, set_encryption_required
from app.security.sensitive_cache import enable_sensitive_caches, sensitive_caches_enabled
from app.services import auth_service
from app.services.content_cache import clear_cache
from app.services.file_registry import file_registry
from app.services.note_store import store
from app.services.ontology_rules_store import bootstrap_ontology_rules_store


@pytest.fixture
def plaintext_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "fixture.metalist.db")
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
    session.close()
    yield
    store.reset()
    clear_cache()
    file_registry.reset()
    clear_encryption_key()
    set_encryption_required(False)
    enable_sensitive_caches()


def test_restoring_a_vault_without_a_password_turns_the_caches_back_on(plaintext_vault) -> None:
    needs_unlock = auth_routes._reset_runtime_state_after_restore()

    assert needs_unlock is False
    assert store.loaded
    assert sensitive_caches_enabled()
