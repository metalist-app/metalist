"""The AI providers and models MetaList ships with (docs/ready-to-build/ai-providers.md).

Part of the program, updated with each release, never stored in a vault. A vault can
add models of its own (ai_added_models.py); a provider's API address is fixed here and
never editable, so a key goes only to its provider, and a hosted deployment can build
its outbound allowlist from these addresses.

A provider is listed here once it can be offered: its adapter exists and its eval pass
rates are recorded. Claude and Gemini join with their adapters.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from app.services.agent.openai_models import OPENAI_API_BASE_URL, OPENAI_MODEL_CONTEXT_TOKENS
from app.services.input_errors import InputRejected


@dataclass(frozen=True, slots=True)
class AiProviderCatalogEntry:
    label: str
    base_url: str
    # Where users see what they spent (the AI settings link to it).
    billing_url: str
    # The models offered, in the order the pickers list them.
    models: tuple[str, ...]
    # Picked until the user picks another; the evals run on it.
    default_model: str
    # The context size of every model of this provider, shipped or added.
    context_tokens: int


AI_CATALOG: dict[str, AiProviderCatalogEntry] = {
    "openai": AiProviderCatalogEntry(
        label="OpenAI",
        base_url=OPENAI_API_BASE_URL,
        billing_url="https://platform.openai.com/usage",
        models=("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
        default_model="gpt-5.6-luna",
        context_tokens=OPENAI_MODEL_CONTEXT_TOKENS,
    ),
}

for _provider, _entry in AI_CATALOG.items():
    assert _entry.default_model in _entry.models, f"{_provider}'s default model is not one of its models"


def catalog_entry(provider: str) -> AiProviderCatalogEntry:
    if provider not in AI_CATALOG:
        raise ValueError(f"AI provider {provider!r} is not in the catalog")
    return AI_CATALOG[provider]


# A model name as providers write them: gpt-5.6-luna, claude-sonnet-5-5,
# models/gemini-2.5-pro, ft:gpt-5.6-luna:org::id.
_MODEL_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]*")
MAX_MODEL_NAME_CHARACTERS = 128


def validate_model_name(model: str) -> str:
    """A model name that can be one, without surrounding spaces. Names come from users
    (AI Agent Settings, a request), so another is rejected input."""
    if not isinstance(model, str):
        raise TypeError("A model name must be text")
    normalized = model.strip()
    if len(normalized) > MAX_MODEL_NAME_CHARACTERS or _MODEL_NAME_RE.fullmatch(normalized) is None:
        raise InputRejected(f"Not a model name: {model!r}. Use the name the provider gives, like gpt-5.6-luna.")
    return normalized


def require_shipped_model(provider: str, model: str) -> str:
    """One of the models MetaList ships for the provider (the evals run only on these)."""
    normalized = validate_model_name(model)
    entry = catalog_entry(provider)
    if normalized not in entry.models:
        raise InputRejected(f"Unsupported {entry.label} model: {model}")
    return normalized


# A vault's own models for a provider, beside the shipped ones: a JSON list of names
# in this preference (ai_models.py reads it).
ADDED_MODELS_PREFERENCE_KEYS: dict[str, str] = {provider: f"pref.ai.{provider}.added_models" for provider in AI_CATALOG}
MAX_ADDED_MODELS = 20


def parse_added_models(provider: str, value: str) -> tuple[str, ...]:
    """The added models a preference value names: distinct, well-formed, none shipped already."""
    entry = catalog_entry(provider)
    if not isinstance(value, str):
        raise TypeError("Added models must be stored as text")
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(name, str) for name in parsed):
        raise InputRejected("Added models must be a list of model names")
    if len(parsed) > MAX_ADDED_MODELS:
        raise InputRejected(f"At most {MAX_ADDED_MODELS} added models per provider")
    models = tuple(validate_model_name(name) for name in parsed)
    if len(set(models)) != len(models):
        raise InputRejected("An added model is listed twice")
    shipped = set(models) & set(entry.models)
    if shipped:
        raise InputRejected(f"{sorted(shipped)[0]} is already one of {entry.label}'s models")
    return models


def serialize_added_models(models: tuple[str, ...]) -> str:
    return json.dumps(list(models), separators=(",", ":"))
