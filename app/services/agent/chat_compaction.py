"""Keep an AI chat within the model's context: the oldest turns are replaced by a summary
the user can read (docs/ui/ai-chat.md, Long chats).

Nothing leaves the model's view without the summary taking its place, and the summary
is all the model knows of the turns it replaced: they are never sent again. There is
only ever one summary in what the model is sent; a later one folds the earlier one in.
The summary is made by the chat's own provider and model from what the chat already sent
it (the turns as the model saw them and the agent's record of what each answer did).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from app.services.agent.ai_send import send_text_stream
from app.services.agent.inference import InferenceAdapter, InferenceProviderError
from app.services.agent.prompts import CONVERSATION_SUMMARY_PROMPT
from app.services.agent.token_estimation import estimate_input_tokens, estimate_text_tokens
from app.services.ai_chat import AiChatSessionStore, SummarySource, TurnToSummarize
from app.utils.time_units import MS_PER_SECOND

# The conversation (summary and turns) may take a quarter of the model's context, and
# never more than this: the rest is for the notes and pages the agent reads, and every
# turn is sent again, so a longer history costs more on every answer.
HISTORY_SHARE_OF_CONTEXT = 4
MAX_HISTORY_TOKENS = 32_000
# The summary may take a tenth of that, so it never crowds out the turns after it, and
# at most a third of what it replaces, so it is shorter than what it stands for (the
# maintainer, 2026-10-30: a third keeps every note and paper the chat named).
SUMMARY_SHARE_OF_HISTORY = 10
SUMMARY_SHARE_OF_REPLACED = 3
# A third of a very short chat is a few words; a summary may always have a sentence or two.
MIN_SUMMARY_TOKENS = 60
# Summarizing goes on until the turns kept fill half the history, so the next turn does
# not summarize again.
_KEPT_SHARE_OF_HISTORY = 2
# Words the summary is asked for, per token it may take: a word is about 1.3 tokens, and
# asking for fewer keeps the summary clear of its limit.
_SUMMARY_WORDS_PER_TOKEN = 0.5
_ACTION = "conversation_summary"
_STARTED_LABEL = "Summarizing earlier conversation"
_COMPLETED_LABEL = "Earlier conversation summarized"
# The privacy settings changed while the summary was made: the turns it would replace
# are no longer sent at all, so neither is it.
_DISCARDED_LABEL = "Earlier conversation no longer sent: privacy settings changed"
_TEXT_EVENTS_WITHOUT_SUMMARY_TEXT = frozenset({"provider_started", "thinking_delta", "done"})


class UnusableSummary(InferenceProviderError):
    """The model wrote a summary MetaList cannot use (none, or too long), as a reply that
    breaks a structured answer's schema is a provider failure (StructuredInferenceError)."""


@dataclass(frozen=True)
class _SummaryRequest:
    source: SummarySource
    turn_count: int
    history_tokens: int


def history_budget(context_tokens: int) -> int:
    """The tokens the conversation may take in what the model is sent."""
    if not isinstance(context_tokens, int) or isinstance(context_tokens, bool) or context_tokens < 1:
        raise ValueError("The model's context must be a positive number of tokens")
    return min(context_tokens // HISTORY_SHARE_OF_CONTEXT, MAX_HISTORY_TOKENS)


def summary_token_limit(*, history_tokens: int, replaced_tokens: int) -> int:
    """The longest a summary may be: a tenth of the history, and a third of what it
    replaces, though never less than a sentence or two."""
    third = max(replaced_tokens // SUMMARY_SHARE_OF_REPLACED, MIN_SUMMARY_TOKENS)
    return min(history_tokens // SUMMARY_SHARE_OF_HISTORY, third)


def turns_to_summarize(*, summary_tokens: int, turn_tokens: list[int], current_tokens: int, history_tokens: int) -> int:
    """How many of the oldest turns to summarize before the current one is answered: none
    while everything fits, else enough that the turns kept fill at most half the history.
    The current turn is never summarized."""
    for value in (summary_tokens, current_tokens, history_tokens, *turn_tokens):
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Token counts must be non-negative integers")
    kept = sum(turn_tokens) + current_tokens
    if summary_tokens + kept <= history_tokens:
        return 0
    target = history_tokens // _KEPT_SHARE_OF_HISTORY
    count = 0
    while count < len(turn_tokens) and kept > target:
        kept -= turn_tokens[count]
        count += 1
    return count


def _turn_tokens(turn: TurnToSummarize) -> int:
    """A turn's share of what the model is sent: its messages and the agent's record
    of it (EARLIER_ACTIONS)."""
    tokens = estimate_input_tokens(turn.messages)
    if turn.actions:
        tokens += estimate_input_tokens(turn.actions)
    return tokens


def _summary_request_text(source: SummarySource, turn_count: int) -> str:
    """The summary request's user message: the summary the model sees now, then the
    turns it replaces as the model was sent them, with what each answer did."""
    parts: list[str] = []
    if source.summary != "":
        parts.append(f"PREVIOUS_SUMMARY\n{source.summary}")
    for number, turn in enumerate(source.turns[:turn_count], start=1):
        lines = [f"TURN {number}"]
        for message in turn.messages:
            lines.append(f"{message['role'].upper()}:\n{message['content']}")
        if turn.actions:
            lines.append("ACTIONS:\n" + json.dumps(turn.actions, sort_keys=True, separators=(",", ":")))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


async def _make_summary(
    *, inference: InferenceAdapter, base_url: str, model: str, thinking_level: str, request: _SummaryRequest,
) -> str:
    replaced = _summary_request_text(request.source, request.turn_count)
    limit = summary_token_limit(history_tokens=request.history_tokens, replaced_tokens=estimate_text_tokens(replaced))
    word_limit = int(limit * _SUMMARY_WORDS_PER_TOKEN)
    messages = [
        {"role": "system", "content": CONVERSATION_SUMMARY_PROMPT.format(word_limit=word_limit)},
        {"role": "user", "content": replaced},
    ]
    content = ""
    async for event in send_text_stream(  # shockharness: ignore[EXC003] reason="each pull from the provider's stream is the external operation; the body collects the text"
        inference, base_url=base_url, model=model, thinking_level=thinking_level, messages=messages,
        on_request=lambda wire_request: None,
    ):
        if event["type"] == "content_delta":
            text = event["text"]
            assert isinstance(text, str), "a content delta carries text"
            content += text
        elif event["type"] not in _TEXT_EVENTS_WITHOUT_SUMMARY_TEXT:
            raise RuntimeError(f"Unknown inference stream event: {event['type']}")
    content = content.strip()
    if content == "":
        raise UnusableSummary("The AI returned an empty summary of the earlier conversation. Send again.")
    if estimate_text_tokens(content) > limit:
        raise UnusableSummary(
            "The AI's summary of the earlier conversation came back longer than allowed, so nothing "
            "was summarized. Send again, or start a new chat with Clear."
        )
    return content


def _status_event(status: str, label: str, *, input_tokens: int, started_at: float) -> dict[str, object]:
    duration_ms = 0.0
    if status == "completed":
        duration_ms = (time.perf_counter() - started_at) * MS_PER_SECOND
    return dict(type="action_status", action=_ACTION, status=status, label=label,
                approx_input_tokens=input_tokens, output_tokens_received=0, duration_ms=duration_ms)


async def summarize_before_turn(
    *, store: AiChatSessionStore, session_key: str, inference: InferenceAdapter, base_url: str, model: str,
    thinking_level: str, current_message: str,
) -> AsyncIterator[dict[str, object]]:
    """Before a turn is answered: summarize the oldest turns when the conversation would
    not fit its share of the model's context. Yields the step's status, if it runs."""
    context = await inference.inspect_context_window(base_url=base_url, model=model)
    history_tokens = history_budget(context.loaded_tokens)
    source = store.summary_source(session_key=session_key)
    summary_tokens = 0
    if source.summary != "":
        summary_tokens = estimate_text_tokens(source.summary)
    turn_count = turns_to_summarize(
        summary_tokens=summary_tokens, turn_tokens=[_turn_tokens(turn) for turn in source.turns],
        current_tokens=estimate_text_tokens(current_message), history_tokens=history_tokens,
    )
    if turn_count == 0:
        return
    request = _SummaryRequest(source=source, turn_count=turn_count, history_tokens=history_tokens)
    input_tokens = estimate_text_tokens(_summary_request_text(source, turn_count))
    started_at = time.perf_counter()
    yield _status_event("started", _STARTED_LABEL, input_tokens=input_tokens, started_at=started_at)
    content = await _make_summary(inference=inference, base_url=base_url, model=model,
                                  thinking_level=thinking_level, request=request)
    is_applied = store.apply_summary(session_key=session_key, content=content, turn_count=turn_count,
                                     history_start=source.history_start, session_id=source.session_id)
    label = _COMPLETED_LABEL
    if not is_applied:
        label = _DISCARDED_LABEL
    yield _status_event("completed", label, input_tokens=input_tokens, started_at=started_at)


async def summarize_on_request(
    *, store: AiChatSessionStore, session_key: str, inference: InferenceAdapter, base_url: str, model: str,
    thinking_level: str,
) -> bool:
    """"Summarize now": summarize every turn the model sees directly, so the summary
    sits where it was asked for. False when there is nothing to summarize, or the chat
    was cleared meanwhile."""
    source = store.summary_source(session_key=session_key)
    turn_count = len(source.turns)
    if turn_count == 0:
        return False
    context = await inference.inspect_context_window(base_url=base_url, model=model)
    request = _SummaryRequest(source=source, turn_count=turn_count,
                              history_tokens=history_budget(context.loaded_tokens))
    content = await _make_summary(inference=inference, base_url=base_url, model=model,
                                  thinking_level=thinking_level, request=request)
    return store.apply_summary(session_key=session_key, content=content, turn_count=turn_count,
                               history_start=source.history_start, session_id=source.session_id)


def history_meter(*, store: AiChatSessionStore, session_key: str, context_tokens: int) -> dict[str, int]:
    """What the chat's history takes of its budget, as the automatic summary counts it: the
    summary, the turns the model still sees directly and the agent's records of them."""
    source = store.summary_source(session_key=session_key)
    summary_tokens = 0
    if source.summary != "":
        summary_tokens = estimate_text_tokens(source.summary)
    turn_tokens = sum(estimate_input_tokens(turn.messages) for turn in source.turns)
    action_tokens = sum(estimate_input_tokens(turn.actions) for turn in source.turns if turn.actions)
    return {
        "summary_tokens": summary_tokens,
        "turn_count": len(source.turns),
        "turn_tokens": turn_tokens,
        "action_tokens": action_tokens,
        "budget_tokens": history_budget(context_tokens),
        "context_tokens": context_tokens,
    }
