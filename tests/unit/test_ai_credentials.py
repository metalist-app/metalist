from __future__ import annotations

from pathlib import Path

import pytest

from app.db.session import begin_writer
from app.db.settings_sql import fetch_settings
from app.db.settings_sql import insert_default_settings
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key
from app.security.encryption import set_encryption_required
from app.services.encryption import EncryptionService
from app.services.ai_credentials import AiCredentialInputError, AiCredentialStore, validate_ai_api_key
import app.services.ai_credentials as credentials_module


# A key shaped like each provider's, with the label its messages use.
_KEYS = {
    "openai": ("sk-test-0123456789abcdefghijklmnop", "OpenAI"),
    "anthropic": ("sk-ant-test-0123456789abcdefghijk", "Anthropic"),
    "gemini": ("AIzaTest0123456789abcdefghijklmnopqr", "Google"),
}


@pytest.fixture
def credential_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    with begin_writer() as connection:
        insert_default_settings(connection)
    try:
        yield
    finally:
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()


def _settings() -> dict[str, object]:
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:ai_credentials:settings"):
            settings = fetch_settings(session.connection())
        assert settings is not None
        return settings
    finally:
        session.close()


@pytest.mark.parametrize("provider", list(_KEYS))
def test_plaintext_namespace_keeps_a_providers_key_in_session_memory_only(
    credential_database, provider: str,
) -> None:
    del credential_database
    api_key, label = _KEYS[provider]
    store = AiCredentialStore(provider)

    status = store.configure(
        token="plaintext-token",
        session_key="session-a",
        api_key=api_key,
    )

    assert status.configured is True
    assert status.persistent is False
    assert store.resolve(token="plaintext-token", session_key="session-a") == api_key
    settings = _settings()
    assert settings[f"{provider}_api_key_ciphertext"] is None
    assert settings[f"{provider}_api_key_encryption_nonce"] is None
    assert settings[f"{provider}_api_key_encryption_tag"] is None

    store.clear_session(session_key="session-a")
    assert store.status(
        token="plaintext-token",
        session_key="session-a",
    ).configured is False
    with pytest.raises(RuntimeError, match=f"{label} API key is not configured"):
        store.resolve(token="plaintext-token", session_key="session-a")


@pytest.mark.parametrize("provider", list(_KEYS))
def test_encrypted_namespace_persists_only_ciphertext(
    credential_database,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    del credential_database
    api_key, _label = _KEYS[provider]
    set_encryption_required(True)
    encryption_service = EncryptionService()
    encryption_service.dek = b"d" * 32
    monkeypatch.setattr(
        credentials_module,
        "get_encryption_service_with_token",
        lambda token: encryption_service,
    )
    store = AiCredentialStore(provider)

    status = store.configure(
        token="encrypted-token",
        session_key="session-a",
        api_key=api_key,
    )

    assert status.configured is True
    assert status.persistent is True
    settings = _settings()
    ciphertext = settings[f"{provider}_api_key_ciphertext"]
    nonce = settings[f"{provider}_api_key_encryption_nonce"]
    tag = settings[f"{provider}_api_key_encryption_tag"]
    assert isinstance(ciphertext, str)
    assert api_key not in ciphertext
    # Each provider has its own slot: the others stay empty.
    for other in set(_KEYS) - {provider}:
        assert settings[f"{other}_api_key_ciphertext"] is None
    assert isinstance(nonce, bytes)
    assert isinstance(tag, bytes)

    restarted_store = AiCredentialStore(provider)
    assert restarted_store.resolve(
        token="encrypted-token",
        session_key="session-after-restart",
    ) == api_key
    assert restarted_store.status(
        token="encrypted-token",
        session_key="session-after-restart",
    ).persistent is True

    cleared = restarted_store.clear(session_key="session-after-restart")
    assert cleared.configured is False
    cleared_settings = _settings()
    assert cleared_settings[f"{provider}_api_key_ciphertext"] is None
    assert cleared_settings[f"{provider}_api_key_encryption_nonce"] is None
    assert cleared_settings[f"{provider}_api_key_encryption_tag"] is None


@pytest.mark.parametrize(("provider", "api_key", "message"), [
    ("openai", "AIzaTest0123456789abcdefghijklmnopqr", "OpenAI API key must start with sk-"),
    ("anthropic", "sk-test-0123456789abcdefghijklmnop", "Anthropic API key must start with sk-ant-"),
    ("gemini", "sk-ant-test-0123456789abcdefghijk", "Google API key must start with AIza or AQ."),
    ("anthropic", "sk-ant-short", "Anthropic API key is too short"),
])
def test_a_key_for_another_provider_is_refused_by_name(provider: str, api_key: str, message: str) -> None:
    with pytest.raises(AiCredentialInputError, match=message):
        validate_ai_api_key(provider, api_key)


# Google AI Studio issues keys starting with AQ. (2026); older keys start with AIza.
@pytest.mark.parametrize("api_key", ["AIzaTest0123456789abcdefghijklmnopqr", "AQ.Test0123456789abcdefghijklmnopqrs"])
def test_both_google_key_formats_are_accepted(api_key: str) -> None:
    assert validate_ai_api_key("gemini", api_key) == api_key
