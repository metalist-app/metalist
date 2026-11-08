"""How much of the model's context window one agent evidence payload may fill.

One setting for every model (AI Agent Settings): a percentage of the window (the maintainer,
2026-11-08), so a model with a smaller window reads proportionally less. The window comes from
the provider where it says (inspect_context_window). A value saved as tokens, under its
original OpenAI key, reads as the same share of OpenAI's window.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.agent.openai_models import OPENAI_MODEL_CONTEXT_TOKENS
from app.services.preference_values import preference_or_default


AGENT_WINDOW_PERCENT_PREFERENCE_KEY = "pref.ai.retrieval.window_percent"
OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY = (
    "pref.ai.openai.retrieval.max_page_approximate_tokens"
)

MIN_AGENT_WINDOW_PERCENT = 1
MAX_AGENT_WINDOW_PERCENT = 100
DEFAULT_AGENT_WINDOW_PERCENT = 50
_PERCENT = 100
# What stays free however large the percentage: the instructions and conversation
# (TARGET_AGENT_CONTEXT_TOKENS) and a batch's answer (_SUMMARY_BATCH_MAX_OUTPUT_TOKENS).
_WINDOW_RESERVED_TOKENS = 32_768 + 8_192

DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS = 500_000
LEGACY_DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS = 24_000
MIN_MAX_PAGE_APPROXIMATE_TOKENS = 500
MAX_OPENAI_PAGE_APPROXIMATE_TOKENS = 500_000


@dataclass(frozen=True, slots=True)
class AgentRetrievalSettings:
    """The approximate token budget for the run's only evidence payload."""

    max_page_approximate_tokens: int

    def __post_init__(self) -> None:
        value = self.max_page_approximate_tokens
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError("Agent approximate tokens per evidence payload must be an integer")
        if value < MIN_MAX_PAGE_APPROXIMATE_TOKENS:
            raise ValueError(f"Agent approximate tokens per evidence payload must be at least {MIN_MAX_PAGE_APPROXIMATE_TOKENS}")


def resolve_tagging_batch_tokens(preferences: dict[str, str], *, context_tokens: int) -> int:
    """A tagging batch reads as much as an answer does: one limit, set in AI Agent Settings."""
    return resolve_agent_retrieval_settings(preferences=preferences, context_tokens=context_tokens).max_page_approximate_tokens


def validate_agent_window_percent_preference(value: str) -> str:
    return _validate_integer_preference(
        value=value,
        label="Share of the model's window preference",
        minimum=MIN_AGENT_WINDOW_PERCENT,
        maximum=MAX_AGENT_WINDOW_PERCENT,
    )


def validate_openai_max_page_approximate_tokens_preference(value: str) -> str:
    return _validate_integer_preference(
        value=value,
        label="OpenAI approximate tokens per evidence payload preference",
        minimum=MIN_MAX_PAGE_APPROXIMATE_TOKENS,
        maximum=MAX_OPENAI_PAGE_APPROXIMATE_TOKENS,
    )


def _window_percent(preferences: dict[str, str]) -> int:
    if AGENT_WINDOW_PERCENT_PREFERENCE_KEY in preferences:
        return int(validate_agent_window_percent_preference(preferences[AGENT_WINDOW_PERCENT_PREFERENCE_KEY]))
    saved_tokens = preference_or_default(
        preferences, OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY,
        default=str(LEGACY_DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS),
    )
    if saved_tokens == str(LEGACY_DEFAULT_OPENAI_MAX_PAGE_APPROXIMATE_TOKENS):
        return DEFAULT_AGENT_WINDOW_PERCENT
    tokens = int(validate_openai_max_page_approximate_tokens_preference(saved_tokens))
    return max(MIN_AGENT_WINDOW_PERCENT, round(tokens * _PERCENT / OPENAI_MODEL_CONTEXT_TOKENS))


def resolve_agent_retrieval_settings(
    *,
    preferences: dict[str, str],
    context_tokens: int,
) -> AgentRetrievalSettings:
    """The evidence budget for a model with this context window: the chosen share of it, never
    so much that the prompt and the answer would not fit."""
    if not isinstance(preferences, dict):
        raise TypeError("preferences must be a dict")
    assert isinstance(context_tokens, int) and context_tokens > _WINDOW_RESERVED_TOKENS, context_tokens
    share = context_tokens * _window_percent(preferences) // _PERCENT
    tokens = max(MIN_MAX_PAGE_APPROXIMATE_TOKENS, min(share, context_tokens - _WINDOW_RESERVED_TOKENS))
    return AgentRetrievalSettings(max_page_approximate_tokens=tokens)


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
