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

from app.services.agent.openai_models import OPENAI_API_BASE_URL, OPENAI_MODEL_CONTEXT_TOKENS


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
