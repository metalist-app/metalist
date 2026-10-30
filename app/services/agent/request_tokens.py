"""What an answer's last request to the model was made of, for the chat's history meter
(docs/ui/ai-chat.md, Long chats): instructions, the chat's history, and this turn (the
question, the view, and the notes and pages read).

The total is the provider's own count. The history and this turn are MetaList's
estimates; the rest of the count is instructions, which also takes in what MetaList does
not estimate (tool definitions, the provider's own framing).
"""

from __future__ import annotations

from app.services.agent.token_estimation import estimate_text_tokens

_SYSTEM_ROLE = "system"


def _message_tokens(message: dict[str, object]) -> int:
    tokens = estimate_text_tokens(str(message["content"]))
    if "tool_calls" in message:
        for call in message["tool_calls"]:
            tokens += estimate_text_tokens(call["name"]) + estimate_text_tokens(call["arguments"])
    return tokens


def request_breakdown(
    *, messages: list[dict[str, object]], history_message_count: int, prompt_tokens: int,
) -> dict[str, int]:
    """{total, instructions, history, this_turn} for one request: the model's messages
    (instructions first, then the history_message_count history messages, then the rest)
    and the provider's count of the tokens it read."""
    if not isinstance(prompt_tokens, int) or isinstance(prompt_tokens, bool) or prompt_tokens < 1:
        raise ValueError("A request reads at least one token")
    if not isinstance(history_message_count, int) or history_message_count < 0:
        raise ValueError("The history is a count of messages")
    conversation = [message for message in messages if message["role"] != _SYSTEM_ROLE]
    assert len(conversation) > history_message_count, "a request has the current question after its history"
    history = sum(_message_tokens(message) for message in conversation[:history_message_count])
    this_turn = sum(_message_tokens(message) for message in conversation[history_message_count:])
    estimated = history + this_turn
    if estimated > prompt_tokens:
        # The estimate ran over the provider's count: shrink both parts to fit inside it.
        history = history * prompt_tokens // estimated
        this_turn = this_turn * prompt_tokens // estimated
    return {
        "total": prompt_tokens,
        "instructions": prompt_tokens - history - this_turn,
        "history": history,
        "this_turn": this_turn,
    }
