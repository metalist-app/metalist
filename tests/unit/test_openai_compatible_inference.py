"""Gemini through its OpenAI-compatible endpoint (openai_compatible_inference.py), against
the streamed Chat Completions wire format, through the real SDK and a mock transport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

import app.services.agent.openai_compatible_inference as compatible
from app.services.agent.judging import OutputJudgment
from app.services.agent.openai_compatible_inference import GEMINI
from app.services.agent.openai_compatible_inference import OpenAICompatibleInferenceAdapter
from app.services.agent.openai_compatible_inference import OpenAICompatibleProviderError
from app.services.agent.openai_compatible_inference import chat_completions_messages
from app.services.agent.tool_calling import AgentTool
from app.services.ai_catalog import catalog_entry
from tests.unit.test_anthropic_inference import QUESTION
from tests.unit.test_anthropic_inference import ReadArguments

BASE_URL = catalog_entry("gemini").base_url
MODEL = "gemini-3.8-flash"
READ_TOOL = AgentTool(name="read_view_notes", description="Read notes in the view.", arguments_model=ReadArguments)
USAGE = {"prompt_tokens": 1000, "completion_tokens": 20, "total_tokens": 1020}
SIGNATURE = {"google": {"thought_signature": "sig-A"}}


def _chunk(delta: dict, finish_reason: str | None) -> dict:
    return {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": MODEL,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}


def _stream(*chunks: dict, usage: dict | None) -> bytes:
    events = list(chunks)
    if usage is not None:
        events.append({"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": MODEL, "choices": [], "usage": usage})
    return ("".join(f"data: {json.dumps(event)}\n\n" for event in events) + "data: [DONE]\n\n").encode()


def _serve(monkeypatch: pytest.MonkeyPatch, *replies: bytes) -> list[dict]:
    sent: list[dict] = []
    pending = list(replies)

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append({"url": str(request.url), **json.loads(request.content)})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=pending.pop(0))

    def client(on_wire_request) -> httpx.AsyncClient:
        return httpx.AsyncClient(event_hooks={"request": [on_wire_request]}, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(compatible, "http_client", client)
    return sent


def _tool_turn(messages: list[dict], thinking_level: str) -> list[dict]:
    adapter = OpenAICompatibleInferenceAdapter(api_key="AIza-test", provider=GEMINI)

    async def run() -> list[dict]:
        return [event async for event in adapter.stream_tool_turn(
            base_url=BASE_URL, model=MODEL, thinking_level=thinking_level, messages=messages,
            tools=(READ_TOOL,), max_output_tokens=8192, on_request=lambda request: None,
        )]
    return asyncio.run(run())


def test_a_gemini_tool_turn_returns_the_call_with_its_thought_signature(monkeypatch) -> None:
    sent = _serve(monkeypatch, _stream(
        _chunk({"role": "assistant", "content": "Reading them."}, None),
        _chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "extra_content": SIGNATURE,
                                "function": {"name": "read_view_notes", "arguments": '{"note_ids": '}}]}, None),
        _chunk({"tool_calls": [{"index": 0, "function": {"arguments": '["n1"], "reason": "garden"}'}}]}, "tool_calls"),
        usage=USAGE,
    ))
    events = _tool_turn(QUESTION, thinking_level="off")

    body = sent[0]
    assert body["url"] == f"{BASE_URL}chat/completions"
    # Gemini 4 Argon and 3.8 Flash cannot turn thinking off: Off asks for the least.
    assert body["reasoning_effort"] == "low"
    assert body["stream_options"] == {"include_usage": True}
    assert body["tool_choice"] == "auto"
    assert "store" not in body
    assert body["tools"][0]["function"]["parameters"]["additionalProperties"] is False
    assert events == [
        {"type": "provider_started"},
        {"type": "content_delta", "text": "Reading them."},
        {"type": "tool_call", "id": "call_1", "name": "read_view_notes", "arguments": '{"note_ids": ["n1"], "reason": "garden"}'},
        {"type": "done", "finish_reason": "tool_calls",
         "usage": {"prompt_tokens": 1000, "completion_tokens": 20, "total_tokens": 1020,
                   "uncached_input_tokens": 1000, "cached_input_tokens": 0, "cache_write_tokens": 0},
         "provider_state": {"provider": "gemini", "items": [{"tool_call_id": "call_1", "fields": {"extra_content": SIGNATURE}}]}},
    ]


def test_the_next_turn_sends_each_call_back_with_its_signature() -> None:
    call = {"id": "call_1", "name": "read_view_notes", "arguments": '{"note_ids": ["n1"]}'}
    state = {"provider": "gemini", "items": [{"tool_call_id": "call_1", "fields": {"extra_content": SIGNATURE}}]}
    messages = chat_completions_messages("gemini", [
        *QUESTION,
        {"role": "assistant", "content": "", "tool_calls": [call], "provider_state": state},
        {"role": "tool", "tool_call_id": "call_1", "name": "read_view_notes", "content": "n1: tomatoes"},
        {"role": "assistant", "content": ""},
        {"role": "system", "content": "Answer now."},
    ])
    assert messages[2:] == [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_1", "type": "function", "extra_content": SIGNATURE,
            "function": {"name": "read_view_notes", "arguments": '{"note_ids": ["n1"]}'},
        }]},
        {"role": "tool", "tool_call_id": "call_1", "content": "n1: tomatoes"},
        {"role": "system", "content": "Answer now."},
    ]
    with pytest.raises(ValueError, match="Cannot hand anthropic state to gemini"):
        chat_completions_messages("gemini", [*QUESTION, {"role": "assistant", "content": "Hi",
                                                         "provider_state": {"provider": "anthropic", "items": []}}])


@pytest.mark.parametrize(("finish_reason", "usage", "message"), [
    ("length", USAGE, "maximum output-token limit"),
    ("content_filter", USAGE, "finish reason 'content_filter'"),
    ("stop", None, "before reporting its usage"),
])
def test_a_gemini_reply_cut_off_or_incomplete_fails_loudly(monkeypatch, finish_reason, usage, message) -> None:
    _serve(monkeypatch, _stream(_chunk({"content": "Partial"}, finish_reason), usage=usage))
    with pytest.raises(OpenAICompatibleProviderError, match=message):
        _tool_turn(QUESTION, "low")


def test_a_gemini_structured_reply_uses_a_strict_schema(monkeypatch) -> None:
    judgment = {"criteria": [{"criterion_id": "accurate", "passed": True, "reason": "Matches the notes."}]}
    text = json.dumps(judgment)
    sent = _serve(monkeypatch, _stream(_chunk({"role": "assistant", "content": text[:20]}, None),
                                       _chunk({"content": text[20:]}, "stop"), usage=USAGE))
    adapter = OpenAICompatibleInferenceAdapter(api_key="AIza-test", provider=GEMINI)
    result = asyncio.run(adapter.infer_structured(
        base_url=BASE_URL, model=MODEL, thinking_level="medium", messages=QUESTION,
        response_model=OutputJudgment, on_progress=lambda progress: None,
    ))
    assert sent[0]["response_format"]["type"] == "json_schema"
    assert sent[0]["response_format"]["json_schema"]["strict"] is True
    assert sent[0]["reasoning_effort"] == "medium"
    assert "store" not in sent[0]
    assert OutputJudgment.model_validate_json(result.content) == OutputJudgment.model_validate(judgment)
    assert result.usage["prompt_tokens"] == 1000
