"""Each model's rate limits, saved in the vault beside the API keys (the maintainer, 2026-11-08):
a restart starts with them, so a summary's batches go out as the account allows from the
first one, not four at once until a first answer reports them (provider_limits.py).

Kept in app_settings.provider_rate_limits_json (database version 15), encrypted like the AI
settings while the vault has a password: which models you use is as private as they are. What
is saved is the account's limits per minute, not what is left: a first answer corrects them.
"""

from __future__ import annotations

from dataclasses import dataclass
import json

from app.db.session import begin_writer
from app.db.settings_sql import fetch_settings, insert_default_settings, update_provider_rate_limits_json
from app.models.database import SafeSession
from app.security.encryption import get_encryption_service, is_encryption_required

_BASE_URL_KEY = "baseUrl"
_MODEL_KEY = "model"
_REQUEST_LIMIT_KEY = "requestLimit"
_TOKEN_LIMIT_KEY = "tokenLimit"
_ENTRY_KEYS = frozenset({_BASE_URL_KEY, _MODEL_KEY, _REQUEST_LIMIT_KEY, _TOKEN_LIMIT_KEY})


@dataclass(frozen=True, slots=True)
class SavedLimits:
    """An account's limits for one endpoint and model: requests and tokens per window."""

    request_limit: int
    token_limit: int

    def __post_init__(self) -> None:
        if not isinstance(self.request_limit, int) or self.request_limit <= 0:
            raise ValueError("A saved request limit is a positive whole number")
        if not isinstance(self.token_limit, int) or self.token_limit <= 0:
            raise ValueError("A saved token limit is a positive whole number")


def _entries(settings: dict[str, object]) -> list[dict[str, object]]:
    stored = settings["provider_rate_limits_json"]
    nonce = settings["provider_rate_limits_encryption_nonce"]
    tag = settings["provider_rate_limits_encryption_tag"]
    if stored is None:
        if nonce is not None or tag is not None:
            raise RuntimeError("provider_rate_limits_json has encryption metadata without a payload")
        return []
    if not isinstance(stored, str):
        raise RuntimeError("provider_rate_limits_json must be stored as a string")
    if (nonce is None) != (tag is None):
        raise RuntimeError("provider_rate_limits_json has incomplete encryption metadata")
    plaintext = stored
    if nonce is not None:
        service = get_encryption_service()
        if service is None:
            raise RuntimeError("Reading the saved rate limits requires an active DEK")
        plaintext = service.decrypt_from_storage(stored, nonce, tag)
    entries = json.loads(plaintext)
    if not isinstance(entries, list) or not all(isinstance(entry, dict) and set(entry) == _ENTRY_KEYS for entry in entries):
        raise RuntimeError("provider_rate_limits_json must be a list of saved limits")
    return entries


def _matches(entry: dict[str, object], *, base_url: str, model: str) -> bool:
    return entry[_BASE_URL_KEY] == base_url and entry[_MODEL_KEY] == model


class DatabaseSavedLimits:
    """The vault's saved rate limits (provider_limits.SavedLimitsStore)."""

    def load(self, *, base_url: str, model: str) -> SavedLimits | None:
        session = SafeSession()
        try:
            with SafeSession.allow_reads("saved_rate_limits:load"):
                settings = fetch_settings(session.connection())
        finally:
            session.close()
        # A vault no setting has been saved in yet has no settings row, as client state allows.
        if settings is None:
            return None
        for entry in _entries(settings):
            if _matches(entry, base_url=base_url, model=model):
                return SavedLimits(request_limit=entry[_REQUEST_LIMIT_KEY], token_limit=entry[_TOKEN_LIMIT_KEY])
        return None

    def save(self, *, base_url: str, model: str, limits: SavedLimits) -> None:
        with begin_writer() as connection:
            insert_default_settings(connection)
            settings = fetch_settings(connection)
            if settings is None:
                raise RuntimeError("app_settings row missing after inserting it")
            entries = [entry for entry in _entries(settings) if not _matches(entry, base_url=base_url, model=model)]
            entries.append({
                _BASE_URL_KEY: base_url, _MODEL_KEY: model,
                _REQUEST_LIMIT_KEY: limits.request_limit, _TOKEN_LIMIT_KEY: limits.token_limit,
            })
            stored = json.dumps(entries, separators=(",", ":"))
            nonce: bytes | None = None
            tag: bytes | None = None
            service = get_encryption_service()
            if service is not None:
                stored, nonce, tag = service.encrypt_for_storage(stored)
            elif is_encryption_required():
                raise RuntimeError("Saving the rate limits requires an active DEK")
            update_provider_rate_limits_json(
                connection,
                provider_rate_limits_json=stored,
                provider_rate_limits_encryption_nonce=nonce,
                provider_rate_limits_encryption_tag=tag,
            )
