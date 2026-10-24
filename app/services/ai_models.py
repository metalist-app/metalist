"""Which models a vault can use with a provider: the ones MetaList ships
(ai_catalog.py) and the ones the vault added in AI Agent Settings, kept in its
encrypted preferences. A model name from a request or a preference is checked here,
where the vault can be read, before any AI call."""

from __future__ import annotations

from app.services.ai_catalog import ADDED_MODELS_PREFERENCE_KEYS, catalog_entry, parse_added_models, validate_model_name
from app.services.client_state_service import load_client_preferences
from app.services.input_errors import InputRejected


def added_models(provider: str, *, token: str) -> tuple[str, ...]:
    preferences = load_client_preferences(token=token)
    key = ADDED_MODELS_PREFERENCE_KEYS[provider]
    if key not in preferences:  # shockharness: ignore[DEF002] reason="a vault that never added a model for the provider has none: () is that"
        return ()
    return parse_added_models(provider, preferences[key])


def available_models(provider: str, *, token: str) -> tuple[str, ...]:
    """The shipped models, then the vault's own, in the order the pickers list them."""
    return catalog_entry(provider).models + added_models(provider, token=token)


def require_available_model(provider: str, model: str, *, token: str) -> str:
    """The model, if this vault can use it with the provider; rejected input otherwise."""
    normalized = validate_model_name(model)
    if normalized not in available_models(provider, token=token):
        raise InputRejected(
            f"{normalized} is not one of {catalog_entry(provider).label}'s models here. "
            "Pick another, or add it in AI Agent Settings."
        )
    return normalized
