import pytest

from app.services.agent.retrieval_settings import (
    AGENT_WINDOW_PERCENT_PREFERENCE_KEY,
    OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY,
    AgentRetrievalSettings,
    resolve_agent_retrieval_settings,
    resolve_tagging_batch_tokens,
    validate_agent_window_percent_preference,
    validate_openai_max_page_approximate_tokens_preference,
)

OPENAI_WINDOW = 1_050_000


# The evidence budget is a share of the model's own window (the maintainer, 2026-11-08), so
# one setting fits every model.
@pytest.mark.parametrize(("percent", "context_tokens", "tokens"), [
    ("50", OPENAI_WINDOW, 525_000),
    ("25", OPENAI_WINDOW, 262_500),
    ("50", 1_000_000, 500_000),
    ("50", 200_000, 100_000),
], ids=["half of OpenAI's", "a quarter", "half of a 1M window", "a smaller model gets less"])
def test_the_budget_is_a_percentage_of_the_models_window(percent: str, context_tokens: int, tokens: int) -> None:
    preferences = {AGENT_WINDOW_PERCENT_PREFERENCE_KEY: percent}
    assert resolve_agent_retrieval_settings(
        preferences=preferences, context_tokens=context_tokens,
    ) == AgentRetrievalSettings(max_page_approximate_tokens=tokens)
    assert resolve_tagging_batch_tokens(preferences, context_tokens=context_tokens) == tokens


def test_the_default_is_half_the_window() -> None:
    assert resolve_agent_retrieval_settings(
        preferences={}, context_tokens=OPENAI_WINDOW,
    ).max_page_approximate_tokens == 525_000


def test_the_whole_window_still_leaves_room_for_the_prompt_and_the_answer() -> None:
    settings = resolve_agent_retrieval_settings(
        preferences={AGENT_WINDOW_PERCENT_PREFERENCE_KEY: "100"}, context_tokens=OPENAI_WINDOW,
    )
    assert settings.max_page_approximate_tokens == OPENAI_WINDOW - 40_960


# A value saved as tokens reads as the same share of OpenAI's window: 500,000 is 48%.
def test_a_saved_token_limit_becomes_a_percentage() -> None:
    settings = resolve_agent_retrieval_settings(
        preferences={OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY: "500000"}, context_tokens=OPENAI_WINDOW,
    )
    assert settings.max_page_approximate_tokens == 504_000


def test_a_saved_percentage_wins_over_a_saved_token_limit() -> None:
    settings = resolve_agent_retrieval_settings(
        preferences={
            OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY: "500000",
            AGENT_WINDOW_PERCENT_PREFERENCE_KEY: "10",
        },
        context_tokens=OPENAI_WINDOW,
    )
    assert settings.max_page_approximate_tokens == 105_000


def test_the_legacy_default_becomes_the_current_default() -> None:
    settings = resolve_agent_retrieval_settings(
        preferences={OPENAI_MAX_PAGE_APPROXIMATE_TOKENS_PREFERENCE_KEY: "24000"}, context_tokens=OPENAI_WINDOW,
    )
    assert settings.max_page_approximate_tokens == 525_000


def test_retired_provider_limits_are_ignored() -> None:
    settings = resolve_agent_retrieval_settings(
        preferences={"pref.ai.retrieval.max_page_approximate_tokens": "7000"}, context_tokens=OPENAI_WINDOW,
    )
    assert settings.max_page_approximate_tokens == 525_000


@pytest.mark.parametrize("value", ["", "0", "101", "1.5", "050", "abc"])
def test_the_percentage_rejects_invalid_values(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_agent_window_percent_preference(value)


@pytest.mark.parametrize("value", ["", "0499", "499", "500001", "1.5"])
def test_a_saved_token_limit_is_still_checked(value: str) -> None:
    with pytest.raises((TypeError, ValueError)):
        validate_openai_max_page_approximate_tokens_preference(value)
