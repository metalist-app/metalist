"""Long AI chats: earlier turns replaced by a summary the user can read
(app/services/agent/chat_compaction.py, AiChatSessionStore)."""

from __future__ import annotations

import asyncio
import re

import pytest

from app.services.agent.chat_compaction import (
    UnusableSummary,
    history_budget,
    history_meter,
    summarize_before_turn,
    summarize_on_request,
    turns_to_summarize,
)
from app.services.agent.inference import InferenceContextWindow
from app.services.agent.request_tokens import request_breakdown
from app.services.agent.token_estimation import estimate_text_tokens
from app.services.ai_chat import AiChatSessionStore
from app.services.ai_chat import NO_REQUEST
from app.services.agent.cloud_privacy import HistoryDisclosure

SESSION = "session"
CONTEXT_TOKENS = 32_768
# Words in a long message: three such answers outgrow the history budget at CONTEXT_TOKENS.
LONG_MESSAGE_WORDS = 3_000


class FakeInference:
    """Answers every summary request with the given text, recording what it was sent."""

    provider_label = "Fake"

    def __init__(self, summary: str) -> None:
        self.summary = summary
        self.requests: list[list[dict[str, str]]] = []

    async def inspect_context_window(self, *, base_url, model):
        return InferenceContextWindow(model=model, maximum_tokens=CONTEXT_TOKENS, loaded_tokens=CONTEXT_TOKENS,
                                      required_tokens=CONTEXT_TOKENS)

    async def stream_text(self, *, base_url, model, thinking_level, messages, on_request):
        self.requests.append(messages)
        yield {"type": "provider_started"}
        yield {"type": "content_delta", "text": self.summary}
        yield {"type": "done", "usage": {}}


def _store_with_turns(*answers: str) -> AiChatSessionStore:
    store = AiChatSessionStore()
    store.synchronize_disclosure_boundary(disclosure=HistoryDisclosure(policy_key="boundary", permitted_note_ids=frozenset(), hidden_note_ids=frozenset()))
    for number, answer in enumerate(answers, start=1):
        turn = store.start_turn(user_content=f"Question {number}", provider="openai", model="m")
        store.complete_turn(turn_id=turn, final_content=answer, actions=[], request_tokens=NO_REQUEST)
    return store


def _summarize_now(store: AiChatSessionStore, inference: FakeInference) -> bool:
    return asyncio.run(summarize_on_request(store=store, inference=inference, base_url="x",
                                            model="m", thinking_level="low"))


def _send(store: AiChatSessionStore, inference: FakeInference, message: str) -> list[str]:
    """Start a turn as Send does and run the summary step; the step's labels."""
    store.start_turn(user_content=message, provider="openai", model="m")

    async def labels() -> list[str]:
        return [event["label"] async for event in summarize_before_turn(
            store=store, inference=inference, base_url="x", model="m",
            thinking_level="low", current_message=message,
        ) if event["status"] == "completed"]

    return asyncio.run(labels())


def test_the_history_takes_a_quarter_of_the_context_up_to_its_cap() -> None:
    assert history_budget(32_768) == 8_192
    assert history_budget(1_050_000) == 32_000


@pytest.mark.parametrize(("turn_tokens", "current_tokens", "expected"), [
    # Everything fits: nothing is summarized.
    ([1_000, 1_000], 500, 0),
    # Too much: the oldest go until the turns kept fill half the budget.
    ([3_000, 3_000, 1_000], 1_000, 2),
    # The current turn alone is too long: every earlier turn goes, never the current one.
    ([1_000], 9_000, 1),
])
def test_the_oldest_turns_are_summarized_until_the_rest_fill_half(turn_tokens, current_tokens, expected) -> None:
    assert turns_to_summarize(summary_tokens=0, turn_tokens=turn_tokens, current_tokens=current_tokens,
                              history_tokens=7_000) == expected


def test_a_long_chat_sends_the_summary_and_never_the_turns_it_replaced() -> None:
    long_answer = "word " * LONG_MESSAGE_WORDS
    store = _store_with_turns(f"FIRST_ANSWER {long_answer}", f"SECOND_ANSWER {long_answer}",
                              f"THIRD_ANSWER {long_answer}")
    inference = FakeInference("The first answers, in short.")

    assert _send(store, inference, "Question 4") == ["Earlier conversation summarized"]

    sent = str(store.provider_messages())
    assert "The first answers, in short." in sent
    assert "FIRST_ANSWER" not in sent
    assert store.provider_messages()[0]["content"].startswith("EARLIER_CONVERSATION_SUMMARY")
    assert store.provider_messages()[-1] == {"role": "user", "content": "Question 4"}


def test_a_later_summary_folds_in_the_earlier_one() -> None:
    store = _store_with_turns("one", "two")
    assert _summarize_now(store, FakeInference("FIRST_SUMMARY"))
    turn = store.start_turn(user_content="Question 3", provider="openai", model="m")
    store.complete_turn(turn_id=turn, final_content="three", actions=[], request_tokens=NO_REQUEST)
    inference = FakeInference("SECOND_SUMMARY")

    assert _summarize_now(store, inference)

    assert "PREVIOUS_SUMMARY\nFIRST_SUMMARY" in inference.requests[0][1]["content"]
    sent = str(store.provider_messages())
    assert "SECOND_SUMMARY" in sent and "FIRST_SUMMARY" not in sent


def test_summarize_now_summarizes_every_turn() -> None:
    store = _store_with_turns("FIRST_ANSWER", "SECOND_ANSWER")
    inference = FakeInference("Both answers, in short.")

    assert _summarize_now(store, inference)

    request = inference.requests[0][1]["content"]
    assert "FIRST_ANSWER" in request and "SECOND_ANSWER" in request
    assert store.provider_messages() == [
        {"role": "user", "content": "EARLIER_CONVERSATION_SUMMARY\n"
         + store.provider_messages()[0]["content"].split("\n", 1)[1]},
    ]
    snapshot = store.snapshot()
    # The summary sits after the latest turn, where Summarize Now was chosen.
    assert snapshot["summaries"][0]["after_message_id"] == snapshot["messages"][-1]["id"]
    assert [message["visibility"] for message in snapshot["messages"]] == ["summarized"] * 4


def test_summarize_now_with_one_turn_summarizes_it() -> None:
    store = _store_with_turns("ONLY_ANSWER")

    assert _summarize_now(store, FakeInference("The one answer, in short."))


def test_summarize_now_with_nothing_new_has_nothing_to_summarize() -> None:
    store = _store_with_turns("one")
    assert _summarize_now(store, FakeInference("First summary."))
    inference = FakeInference("Never asked for.")

    assert not _summarize_now(store, inference)
    assert inference.requests == []


def test_the_summary_is_asked_for_and_held_to_a_third_of_what_it_replaces() -> None:
    answer = "word " * LONG_MESSAGE_WORDS
    store = _store_with_turns(answer)
    inference = FakeInference("Short.")
    assert _summarize_now(store, inference)
    request_tokens = estimate_text_tokens(inference.requests[0][1]["content"])
    word_limit = int(re.search(r"At most (\d+) words", inference.requests[0][0]["content"]).group(1))
    # Asked for in words, about 1.3 tokens each: well within a third of the tokens replaced.
    assert word_limit * 2 <= request_tokens // 3

    store = _store_with_turns(answer)
    with pytest.raises(UnusableSummary, match="longer than allowed"):
        _summarize_now(store, FakeInference("word " * (LONG_MESSAGE_WORDS // 2)))
    # Nothing was summarized.
    assert store.snapshot()["summaries"] == []


def test_a_summary_finished_after_clear_chat_is_dropped() -> None:
    store = _store_with_turns("one", "two")
    source = store.summary_source()
    store.clear()

    assert not store.apply_summary(content="Too late.", turn_count=2,
                                   history_start=source.history_start, session_id=source.session_id)
    assert store.snapshot() == {"messages": [], "summaries": []}


def test_a_privacy_change_stops_sending_the_summary() -> None:
    store = _store_with_turns("PRIVATE_ANSWER")
    assert _summarize_now(store, FakeInference("PRIVATE_SUMMARY"))

    store.synchronize_disclosure_boundary(disclosure=HistoryDisclosure(policy_key="changed", permitted_note_ids=frozenset(), hidden_note_ids=frozenset()))
    store.start_turn(user_content="Hello", provider="openai", model="m")

    assert store.provider_messages() == [{"role": "user", "content": "Hello"}]
    snapshot = store.snapshot()
    assert [summary["visibility"] for summary in snapshot["summaries"]] == ["held_back"]
    assert [message["visibility"] for message in snapshot["messages"]] == ["held_back", "held_back", "sent", "sent"]


def test_no_turn_starts_while_a_summary_is_made() -> None:
    store = _store_with_turns("one")
    assert store.begin_summary()
    assert store.is_summarizing()
    assert not store.begin_summary()
    with pytest.raises(RuntimeError, match="summarizing"):
        store.start_turn(user_content="Too soon", provider="openai", model="m")
    store.end_summary()
    assert not store.is_summarizing()


def test_the_history_meter_counts_what_the_automatic_summary_counts() -> None:
    store = _store_with_turns("one", "two")

    meter = history_meter(store=store, context_tokens=CONTEXT_TOKENS)

    assert meter["turn_count"] == 2 and meter["summary_tokens"] == 0 and meter["turn_tokens"] > 0
    assert meter["budget_tokens"] == history_budget(CONTEXT_TOKENS)
    assert meter["context_tokens"] == CONTEXT_TOKENS
    assert _summarize_now(store, FakeInference("Both, in short."))
    after = history_meter(store=store, context_tokens=CONTEXT_TOKENS)
    assert after["turn_count"] == 0 and after["turn_tokens"] == 0
    assert after["summary_tokens"] == estimate_text_tokens("Both, in short.")


def test_the_last_request_is_the_providers_count_split_into_its_parts() -> None:
    messages = [
        {"role": "system", "content": "Instructions " * 50},
        {"role": "user", "content": "EARLIER " * 20},
        {"role": "assistant", "content": "ANSWER " * 20},
        {"role": "user", "content": "Current question"},
        {"role": "tool", "name": "read_view_notes", "tool_call_id": "c1", "content": "NOTE " * 100},
    ]

    parts = request_breakdown(messages=messages, history_message_count=2, prompt_tokens=5_000)

    assert parts["total"] == 5_000
    assert parts["history"] > 0 and parts["this_turn"] > parts["history"]
    # What MetaList does not estimate (tool definitions, framing) counts as instructions.
    assert parts["instructions"] == 5_000 - parts["history"] - parts["this_turn"]


def test_an_estimate_over_the_providers_count_shrinks_to_fit_it() -> None:
    messages = [{"role": "user", "content": "word " * 500}, {"role": "user", "content": "word " * 500}]

    parts = request_breakdown(messages=messages, history_message_count=1, prompt_tokens=100)

    assert parts["history"] + parts["this_turn"] <= 100
    assert parts["instructions"] >= 0 and parts["total"] == 100


def test_the_store_keeps_the_latest_answers_request() -> None:
    store = _store_with_turns("one")
    assert store.last_request() == NO_REQUEST
    request = {"total": 900, "instructions": 500, "history": 100, "this_turn": 300}
    turn = store.start_turn(user_content="Question 2", provider="openai", model="m")
    store.complete_turn(turn_id=turn, final_content="two", actions=[], request_tokens=request)

    assert store.last_request() == request
    store.clear()
    assert store.last_request() == NO_REQUEST
