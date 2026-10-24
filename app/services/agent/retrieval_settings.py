"""The max token window: the most one agent evidence payload holds, for every provider.

One setting (AI Agent Settings), kept under its original OpenAI key so saved values carry
over; every provider's shipped models read far more than its maximum.
"""

from __future__ import annotations

from dataclasses import dataclass
from app.services.ai_catalog import AI_CATALOG
from app.services.preference_values import preference_or_default


OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY = (
    "pref.ai.openai.retrieval.max_page_approximate_tokens"
)

DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS = 500_000
LEGACY_DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS = 24_000
MIN_MAX_PAGE_APPROXIMATE_TOKENS = 500
MAX_OPENAI_PAGE_APPROXIMATE_TOKENS = 500_000


@dataclass(frozen=True, slots=True)
class AgentRetrievalSettings:
    """The approximate token budget for the run's only evidence payload."""

    max_page_approximate_tokens: int

    def __post_init__(self) -> None:
        _validate_integer_range(
            value=self.max_page_approximate_tokens,
            label="Agent approximate tokens per evidence payload",
            minimum=MIN_MAX_PAGE_APPROXIMATE_TOKENS,
            maximum=MAX_OPENAI_PAGE_APPROXIMATE_TOKENS,
        )


def resolve_tagging_batch_tokens(preferences: dict[str, str], provider: str) -> int:
    """A tagging batch reads as much as an answer does: one limit, set in AI Agent Settings."""
    return resolve_agent_retrieval_settings(preferences=preferences, provider=provider).max_page_approximate_tokens


def validate_openai_max_page_approximate_tokens_preference(value: str) -> str:
    return _validate_integer_preference(
        value=value,
        label="OpenAI approximate tokens per evidence payload preference",
        minimum=MIN_MAX_PAGE_APPROXIMATE_TOKENS,
        maximum=MAX_OPENAI_PAGE_APPROXIMATE_TOKENS,
    )


def resolve_agent_retrieval_settings(
    *,
    preferences: dict[str, str],
    provider: str,
) -> AgentRetrievalSettings:
    if not isinstance(preferences, dict):
        raise TypeError("preferences must be a dict")
    preference_key = _preference_key_for_provider(provider=provider)
    default = _default_for_provider(provider=provider)
    raw_value = preference_or_default(preferences, preference_key, default=str(default.max_page_approximate_tokens))
    if raw_value == str(LEGACY_DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS):
        raw_value = str(DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS)
    validator = validate_openai_max_page_approximate_tokens_preference
    return AgentRetrievalSettings(
        max_page_approximate_tokens=int(validator(raw_value)),
    )


def _validate_integer_preference(
    *,
    value: str,
    label: str,
    minimum: int,
    maximum: int,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if value == "" or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{label} must be a canonical positive integer")
    parsed = int(value)
    if str(parsed) != value:
        raise ValueError(f"{label} must be a canonical positive integer")
    _validate_integer_range(
        value=parsed,
        label=label,
        minimum=minimum,
        maximum=maximum,
    )
    return value


def _validate_integer_range(
    *,
    value: int,
    label: str,
    minimum: int,
    maximum: int,
) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{label} must be from {minimum} to {maximum}")


DEFAULT_AGENT_RETRIEVAL_SETTINGS = AgentRetrievalSettings(
    max_page_approximate_tokens=DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS,
)
DEFAULT_OPENAI_AGENT_RETRIEVAL_SETTINGS = AgentRetrievalSettings(
    max_page_approximate_tokens=DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS,
)


def _preference_key_for_provider(
    *,
    provider: str,
) -> str:
    if provider in AI_CATALOG:
        return OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY
    raise ValueError(f"Unsupported agent retrieval provider: {provider}")


def _default_for_provider(
    *,
    provider: str,
) -> AgentRetrievalSettings:
    if provider in AI_CATALOG:
        return DEFAULT_OPENAI_AGENT_RETRIEVAL_SETTINGS
    raise ValueError(f"Unsupported agent retrieval provider: {provider}")
