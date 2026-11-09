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
from app.db.settings_sql import fetch_settings, insert_default_settings, update_model_timings_json, update_provider_rate_limits_json
from app.models.database import SafeSession
from app.security.encryption import get_encryption_service, is_encryption_required
from app.services.agent.staged_summary import ModelTiming

_BASE_URL_KEY = "baseUrl"
_MODEL_KEY = "model"
_REQUEST_LIMIT_KEY = "requestLimit"
_TOKEN_LIMIT_KEY = "tokenLimit"
_ENTRY_KEYS = frozenset({_BASE_URL_KEY, _MODEL_KEY, _REQUEST_LIMIT_KEY, _TOKEN_LIMIT_KEY})
_STARTUP_SECONDS_KEY = "startupSeconds"
_SECONDS_PER_MILLION_TOKENS_KEY = "secondsPerMillionTokens"
_TIMING_ENTRY_KEYS = frozenset({_BASE_URL_KEY, _MODEL_KEY, _STARTUP_SECONDS_KEY, _SECONDS_PER_MILLION_TOKENS_KEY})


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


def _entries(settings: dict[str, object], *, payload: str, entry_keys: frozenset[str]) -> list[dict[str, object]]:
    """The saved entries of one app_settings payload ("provider_rate_limits" or "model_timings")."""
    stored = settings[f"{payload}_json"]
    nonce = settings[f"{payload}_encryption_nonce"]
    tag = settings[f"{payload}_encryption_tag"]
    if stored is None:
        if nonce is not None or tag is not None:
            raise RuntimeError(f"{payload}_json has encryption metadata without a payload")
        return []
    if not isinstance(stored, str):
        raise RuntimeError(f"{payload}_json must be stored as a string")
    if (nonce is None) != (tag is None):
        raise RuntimeError(f"{payload}_json has incomplete encryption metadata")
    plaintext = stored
    if nonce is not None:
        if not isinstance(nonce, bytes) or not isinstance(tag, bytes):
            raise RuntimeError(f"{payload}_json encryption metadata must be bytes")
        service = get_encryption_service()
        if service is None:
            raise RuntimeError(f"Reading {payload} requires an active DEK")
        plaintext = service.decrypt_from_storage(stored, nonce, tag)
    entries = json.loads(plaintext)
    if not isinstance(entries, list) or not all(isinstance(entry, dict) and set(entry) == entry_keys for entry in entries):
        raise RuntimeError(f"{payload}_json must be a list of saved entries")
    return entries


def _sealed(entries: list[dict[str, object]]) -> tuple[str, bytes | None, bytes | None]:
    """Entries as stored: encrypted while the vault has a password."""
    stored = json.dumps(entries, separators=(",", ":"))
    service = get_encryption_service()
    if service is not None:
        return service.encrypt_for_storage(stored)
    if is_encryption_required():
        raise RuntimeError("Saving this requires an active DEK")
    return stored, None, None


def _read_settings(reason: str) -> dict[str, object] | None:
    session = SafeSession()
    try:
        with SafeSession.allow_reads(reason):
            return fetch_settings(session.connection())
    finally:
        session.close()


def _whole_number(entry: dict[str, object], key: str) -> int:
    value = entry[key]
    if not isinstance(value, int):
        raise RuntimeError(f"A saved {key} must be a whole number")
    return value


def _number(entry: dict[str, object], key: str) -> float:
    value = entry[key]
    if not isinstance(value, (int, float)):
        raise RuntimeError(f"A saved {key} must be a number")
    return float(value)


def _matches(entry: dict[str, object], *, base_url: str, model: str) -> bool:
    return entry[_BASE_URL_KEY] == base_url and entry[_MODEL_KEY] == model


class DatabaseSavedLimits:
    """The vault's saved rate limits (provider_limits.SavedLimitsStore)."""

    def load(self, *, base_url: str, model: str) -> SavedLimits | None:
        settings = _read_settings("saved_rate_limits:load")
        # A vault no setting has been saved in yet has no settings row, as client state allows.
        if settings is None:
            return None
        for entry in _entries(settings, payload="provider_rate_limits", entry_keys=_ENTRY_KEYS):
            if _matches(entry, base_url=base_url, model=model):
                return SavedLimits(request_limit=_whole_number(entry, _REQUEST_LIMIT_KEY), token_limit=_whole_number(entry, _TOKEN_LIMIT_KEY))
        return None

    def save(self, *, base_url: str, model: str, limits: SavedLimits) -> None:
        with begin_writer() as connection:
            insert_default_settings(connection)
            settings = fetch_settings(connection)
            if settings is None:
                raise RuntimeError("app_settings row missing after inserting it")
            entries = [
                entry for entry in _entries(settings, payload="provider_rate_limits", entry_keys=_ENTRY_KEYS)
                if not _matches(entry, base_url=base_url, model=model)
            ]
            entries.append({
                _BASE_URL_KEY: base_url, _MODEL_KEY: model,
                _REQUEST_LIMIT_KEY: limits.request_limit, _TOKEN_LIMIT_KEY: limits.token_limit,
            })
            stored, nonce, tag = _sealed(entries)
            update_provider_rate_limits_json(
                connection,
                provider_rate_limits_json=stored,
                provider_rate_limits_encryption_nonce=nonce,
                provider_rate_limits_encryption_tag=tag,
            )


class DatabaseSavedTimings:
    """The vault's saved model timings: how long each model takes over a summary batch, so its
    progress bar moves from the first second (app_settings.model_timings_json, database version 16)."""

    def load(self, *, base_url: str, model: str) -> ModelTiming | None:
        settings = _read_settings("saved_model_timings:load")
        # A vault no setting has been saved in yet has no settings row, as client state allows.
        if settings is None:
            return None
        for entry in _entries(settings, payload="model_timings", entry_keys=_TIMING_ENTRY_KEYS):
            if _matches(entry, base_url=base_url, model=model):
                return ModelTiming(
                    startup_seconds=_number(entry, _STARTUP_SECONDS_KEY),
                    seconds_per_million_tokens=_number(entry, _SECONDS_PER_MILLION_TOKENS_KEY),
                )
        return None

    def save(self, *, base_url: str, model: str, timing: ModelTiming) -> None:
        with begin_writer() as connection:
            insert_default_settings(connection)
            settings = fetch_settings(connection)
            if settings is None:
                raise RuntimeError("app_settings row missing after inserting it")
            entries = [
                entry for entry in _entries(settings, payload="model_timings", entry_keys=_TIMING_ENTRY_KEYS)
                if not _matches(entry, base_url=base_url, model=model)
            ]
            entries.append({
                _BASE_URL_KEY: base_url, _MODEL_KEY: model,
                _STARTUP_SECONDS_KEY: timing.startup_seconds,
                _SECONDS_PER_MILLION_TOKENS_KEY: timing.seconds_per_million_tokens,
            })
            stored, nonce, tag = _sealed(entries)
            update_model_timings_json(
                connection,
                model_timings_json=stored,
                model_timings_encryption_nonce=nonce,
                model_timings_encryption_tag=tag,
            )
