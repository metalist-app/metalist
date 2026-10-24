"""Each AI provider's API key, kept per vault (docs/design/ai-providers.md).

One slot per provider: in an encrypted namespace the key is encrypted with the
namespace DEK into its app_settings columns (settings_sql.AI_API_KEY_COLUMN_PREFIXES);
in a plaintext namespace it is held only in server session memory. A key is
write-only from the browser: never returned, never in traces, debug or history.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from app.db.session import begin_writer
from app.db.settings_sql import ai_api_key_columns
from app.db.settings_sql import clear_ai_api_key
from app.db.settings_sql import fetch_settings
from app.db.settings_sql import insert_default_settings
from app.db.settings_sql import update_ai_api_key
from app.models.database import SafeSession
from app.security.encryption import get_encryption_service_with_token
from app.security.encryption import is_encryption_required


_MINIMUM_API_KEY_CHARACTERS = 20
_MAXIMUM_API_KEY_CHARACTERS = 512
# ASCII control characters are the codes below the space.
_FIRST_NON_CONTROL_CODE = ord(" ")


@dataclass(frozen=True, slots=True)
class AiKeyFormat:
    # How the provider is named in messages ("OpenAI API key must ...").
    label: str
    # Every key the provider issues starts with one of these.
    prefixes: tuple[str, ...]


# The providers with a key slot, and what their keys look like.
AI_KEY_FORMATS: dict[str, AiKeyFormat] = {
    "openai": AiKeyFormat(label="OpenAI", prefixes=("sk-",)),
    "anthropic": AiKeyFormat(label="Anthropic", prefixes=("sk-ant-",)),
    # Google AI Studio issues keys starting with AQ. (2026); older keys start with AIza.
    "gemini": AiKeyFormat(label="Google", prefixes=("AIza", "AQ.")),
}


@dataclass(frozen=True, slots=True)
class AiCredentialStatus:
    configured: bool
    persistent: bool


class AiCredentialInputError(ValueError):
    """An API key the user typed that cannot be one."""


def _key_format(provider: str) -> AiKeyFormat:
    if provider not in AI_KEY_FORMATS:
        raise ValueError(f"No API-key slot for AI provider {provider!r}")
    return AI_KEY_FORMATS[provider]


def validate_ai_api_key(provider: str, api_key: str) -> str:
    key_format = _key_format(provider)
    name = f"{key_format.label} API key"
    if not isinstance(api_key, str):
        raise TypeError(f"{name} must be text")
    if api_key != api_key.strip():
        raise AiCredentialInputError(f"{name} must not contain surrounding whitespace")
    if not api_key.startswith(key_format.prefixes):
        raise AiCredentialInputError(f"{name} must start with {' or '.join(key_format.prefixes)}")
    if len(api_key) < _MINIMUM_API_KEY_CHARACTERS:
        raise AiCredentialInputError(f"{name} is too short")
    if len(api_key) > _MAXIMUM_API_KEY_CHARACTERS:
        raise AiCredentialInputError(f"{name} is too long")
    if any(character.isspace() or ord(character) < _FIRST_NON_CONTROL_CODE for character in api_key):
        raise AiCredentialInputError(f"{name} must not contain whitespace or control characters")
    return api_key


class AiCredentialStore:
    """One provider's key slot."""

    def __init__(self, provider: str) -> None:
        self._provider = provider
        self._label = _key_format(provider).label
        self._lock = RLock()
        self._session_keys: dict[str, str] = {}

    def configure(self, *, token: str, session_key: str, api_key: str) -> AiCredentialStatus:
        normalized = validate_ai_api_key(self._provider, api_key)
        self._validate_session_key(session_key)
        if is_encryption_required():
            encryption_service = get_encryption_service_with_token(token)
            if encryption_service is None:
                raise RuntimeError(f"{self._label} API key persistence requires an active DEK")
            ciphertext, nonce, tag = encryption_service.encrypt_for_storage(normalized)
            with begin_writer() as connection:
                insert_default_settings(connection)
                update_ai_api_key(connection, provider=self._provider, ciphertext=ciphertext, nonce=nonce, tag=tag)
            with self._lock:
                self._forget_session_key_locked(session_key)
            return AiCredentialStatus(configured=True, persistent=True)

        self._assert_no_plaintext_persisted_key()
        with self._lock:
            self._session_keys[session_key] = normalized
        return AiCredentialStatus(configured=True, persistent=False)

    def resolve(self, *, token: str, session_key: str) -> str:
        self._validate_session_key(session_key)
        if is_encryption_required():
            return self._load_persisted_key(token=token)
        self._assert_no_plaintext_persisted_key()
        with self._lock:
            if session_key not in self._session_keys:
                raise RuntimeError(f"{self._label} API key is not configured")
            return self._session_keys[session_key]

    def status(self, *, token: str, session_key: str) -> AiCredentialStatus:
        self._validate_session_key(session_key)
        if is_encryption_required():
            persisted = self._load_persisted_key_if_present(token=token)
            return AiCredentialStatus(configured=persisted != "", persistent=persisted != "")
        self._assert_no_plaintext_persisted_key()
        with self._lock:
            configured = session_key in self._session_keys
        return AiCredentialStatus(configured=configured, persistent=False)

    def clear(self, *, session_key: str) -> AiCredentialStatus:
        self._validate_session_key(session_key)
        with self._lock:
            self._forget_session_key_locked(session_key)
        if is_encryption_required():
            with begin_writer() as connection:
                insert_default_settings(connection)
                clear_ai_api_key(connection, provider=self._provider)
        else:
            self._assert_no_plaintext_persisted_key()
        return AiCredentialStatus(configured=False, persistent=False)

    def clear_session(self, *, session_key: str) -> None:
        self._validate_session_key(session_key)
        with self._lock:
            self._forget_session_key_locked(session_key)

    def _forget_session_key_locked(self, session_key: str) -> None:
        """A session that never set a key has none to forget."""
        if session_key in self._session_keys:
            del self._session_keys[session_key]

    def reset(self) -> None:
        with self._lock:
            self._session_keys.clear()

    def _validate_session_key(self, session_key: str) -> None:
        if not isinstance(session_key, str) or session_key == "":
            raise ValueError(f"{self._label} credential session key must be non-empty")

    @staticmethod
    def _settings() -> dict[str, object]:
        session = SafeSession()
        try:
            with SafeSession.allow_reads("ai_credentials:settings"):
                settings = fetch_settings(session.connection())
            if settings is None:
                raise RuntimeError("AI credentials require app_settings row")
            return settings
        finally:
            session.close()

    def _assert_no_plaintext_persisted_key(self) -> None:
        if any(value is not None for value in self._credential_columns(self._settings())):
            raise RuntimeError(f"Unencrypted vault contains persisted {self._label} credential data")

    def _load_persisted_key(self, *, token: str) -> str:
        api_key = self._load_persisted_key_if_present(token=token)
        if api_key == "":
            raise RuntimeError(f"{self._label} API key is not configured")
        return api_key

    def _load_persisted_key_if_present(self, *, token: str) -> str:
        ciphertext, nonce, tag = self._credential_columns(self._settings())
        if ciphertext is None and nonce is None and tag is None:
            return ""
        if not isinstance(ciphertext, str) or ciphertext == "":
            raise RuntimeError(f"Stored {self._label} API key ciphertext is invalid")
        if not isinstance(nonce, bytes) or not isinstance(tag, bytes):
            raise RuntimeError(f"Stored {self._label} API key encryption metadata is incomplete")
        encryption_service = get_encryption_service_with_token(token)
        if encryption_service is None:
            raise RuntimeError(f"{self._label} API key decryption requires an active DEK")
        plaintext = encryption_service.decrypt_from_storage(ciphertext, nonce, tag)
        return validate_ai_api_key(self._provider, plaintext)

    def _credential_columns(self, settings: dict[str, object]) -> tuple[object, object, object]:
        ciphertext_column, nonce_column, tag_column = ai_api_key_columns(self._provider)
        return settings[ciphertext_column], settings[nonce_column], settings[tag_column]


# Every provider's slot, by provider.
ai_credential_stores: dict[str, AiCredentialStore] = {provider: AiCredentialStore(provider) for provider in AI_KEY_FORMATS}


def ai_credential_store(provider: str) -> AiCredentialStore:
    if provider not in ai_credential_stores:
        raise ValueError(f"No API-key slot for AI provider {provider!r}")
    return ai_credential_stores[provider]


def reset_ai_credentials() -> None:
    """Forget every session-held key (logout of everyone, vault switch, restore)."""
    for store in ai_credential_stores.values():
        store.reset()


def clear_ai_credential_sessions(*, session_key: str) -> None:
    """Forget one session's session-held keys (its logout)."""
    for store in ai_credential_stores.values():
        store.clear_session(session_key=session_key)
