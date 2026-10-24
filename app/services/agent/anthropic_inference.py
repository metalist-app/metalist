"""Claude inference adapter: Anthropic's Messages API through the native SDK.

Native, not Anthropic's OpenAI-compatible endpoint, which ignores strict tools,
prompt caching and thinking (docs/ready-to-build/ai-providers.md, Design §1).

How MetaList's provider-neutral shapes (tool_calling.py) become Claude's:

- System messages before the first assistant reply become the request's `system`;
  later ones (the agent loop's "answer now") stay in place as mid-conversation
  system messages, which Claude accepts only after a user turn.
- Tool results become `tool_result` blocks in one user turn.
- Claude's thinking blocks travel as `provider_state` and go back first in the
  assistant turn that produced them, unchanged, so a thinking model keeps its train
  of thought across tool calls.
- An assistant reply with no text and no tool calls is left out: Claude rejects an
  empty assistant turn.
- Thinking is always adaptive (Opus 5.5 cannot turn it off); MetaList's thinking
  level sets Claude's effort, Off and Low both "low".
- Forced tool choice is rejected by current models, so tools are offered with
  `auto` and strict input schemas.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
from anthropic import APIError
from anthropic import APITimeoutError
from anthropic import AsyncAnthropic
from anthropic import DefaultAsyncHttpxClient
from anthropic.types import Message
from anthropic.types import Usage
from pydantic import BaseModel
from pydantic import ValidationError
from pydantic_core import from_json

from app.services.agent.history import record_provider_chunk
from app.services.agent.history import record_provider_event
from app.services.agent.history import record_structured_call
from app.services.agent.history import record_text_call
from app.services.agent.history import record_tool_turn
from app.services.agent.inference import InferenceAttempt
from app.services.agent.inference import InferenceContextWindow
from app.services.agent.inference import InferenceProviderError
from app.services.agent.inference import InferenceResponse
from app.services.agent.inference import StructuredInferenceError
from app.services.agent.inference import StructuredInferenceProgress
from app.services.agent.inference import TARGET_AGENT_CONTEXT_TOKENS
from app.services.agent.inference import UNMEASURED_SILENCE_LIMIT_SECONDS
from app.services.agent.structured_inference import _broken_rules
from app.services.agent.structured_inference import _structured_max_output_tokens
from app.services.agent.structured_inference import structured_retry_messages
from app.services.agent.token_estimation import estimate_text_tokens
from app.services.agent.tool_calling import AgentTool
from app.services.agent.tool_calling import validate_tool_conversation
from app.services.ai_catalog import catalog_entry
from app.services.ai_catalog import validate_model_name
from app.utils.time_units import MS_PER_SECOND


_PROVIDER = "anthropic"
_LABEL = "Claude"
# provider_state written and read only by this adapter.
_ANTHROPIC_PROVIDER_STATE = "anthropic"
_THINKING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})

_CLAUDE_EFFORT = {"off": "low", "low": "low", "medium": "medium", "high": "high"}
# Thinking is adaptive on every request; its text is not shown, so Claude returns only
# the signatures that let the next turn continue it.
_ADAPTIVE_THINKING = {"type": "adaptive", "display": "omitted"}
# The repeated prefix (instructions, tools, the evidence read so far) is cached.
_CACHE_PREFIX = {"type": "ephemeral"}

# Strict schemas: Claude enforces types, enums and required fields; it rejects string
# lengths, maxItems and a minItems above 1. Pydantic checks those on every reply.
_UNENFORCED_KEYWORDS = frozenset({"title", "minLength", "maxLength", "maxItems"})
_LARGEST_ENFORCED_MIN_ITEMS = 1

# Streamed structured output is reported again once this many more tokens have arrived.
_OUTPUT_PROGRESS_STEP_TOKENS = 8
_STRUCTURED_MAX_ATTEMPTS = 2
_PROVIDER_ERROR_DETAIL_CHARS = 500


class AnthropicProviderError(InferenceProviderError):
    """Expected Claude API or transport failure."""


def resolve_claude_effort(thinking_level: str) -> str:
    if thinking_level not in _CLAUDE_EFFORT:
        raise ValueError(f"Unsupported thinking level: {thinking_level}")
    return _CLAUDE_EFFORT[thinking_level]


def claude_silence_limit_seconds(thinking_level: str) -> float:
    """Claude streams pings while it thinks, so silence means a broken connection."""
    if thinking_level not in UNMEASURED_SILENCE_LIMIT_SECONDS:
        raise ValueError(f"Unsupported thinking level: {thinking_level}")
    return UNMEASURED_SILENCE_LIMIT_SECONDS[thinking_level]


def _silence_message(seconds: float) -> str:
    return f"Claude did not respond for {seconds:g} seconds. Check your internet connection and ask again."


def _provider_error_message(exc: APIError) -> str:
    detail = " ".join(str(exc).split())
    if detail == "":
        return "Claude API request failed"
    return f"Claude API request failed: {detail[:_PROVIDER_ERROR_DETAIL_CHARS]}"


def claude_strict_schema(schema: object) -> object:
    """A copy of a Pydantic schema Claude can enforce: every object closed, every
    property required, unenforced keywords left out (see _UNENFORCED_KEYWORDS)."""
    if isinstance(schema, list):
        return [claude_strict_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    strict: dict[str, object] = {}
    for key, value in schema.items():
        if key in _UNENFORCED_KEYWORDS:
            continue
        if key == "minItems" and isinstance(value, int) and value > _LARGEST_ENFORCED_MIN_ITEMS:
            continue
        if key in ("properties", "$defs"):
            if not isinstance(value, dict):
                raise TypeError(f"Schema {key} must be an object")
            strict[key] = {name: claude_strict_schema(nested) for name, nested in value.items()}
            continue
        strict[key] = claude_strict_schema(value)
    if "properties" in strict:
        properties = strict["properties"]
        assert isinstance(properties, dict)
        strict["additionalProperties"] = False
        strict["required"] = list(properties)
    return strict


def _claude_tool(tool: AgentTool) -> dict[str, object]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": claude_strict_schema(tool.arguments_schema()),
        "strict": True,
    }


def _text(item: Mapping[str, object], key: str) -> str:
    value = item[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be text")
    return value


def _objects(item: Mapping[str, object], key: str) -> list[dict[str, object]]:
    value = item[key]
    if not isinstance(value, list) or not all(isinstance(entry, dict) for entry in value):
        raise TypeError(f"{key} must be a list of objects")
    return value


def claude_request_messages(
    messages: Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The (system, messages) of a Claude request for a MetaList conversation (module docstring)."""
    conversation = [dict(message) for message in messages]
    validate_tool_conversation(conversation)
    system: list[dict[str, object]] = []
    converted: list[dict[str, object]] = []
    tool_results: list[dict[str, object]] = []
    has_assistant_turn = False
    for message in conversation:
        role = message["role"]
        if role == "tool":
            tool_results.append({
                "type": "tool_result", "tool_use_id": _text(message, "tool_call_id"), "content": _text(message, "content"),
            })
            continue
        if tool_results:
            converted.append({"role": "user", "content": tool_results})
            tool_results = []
        if role == "system" and not has_assistant_turn:
            system.append({"type": "text", "text": _text(message, "content")})
        elif role in ("system", "user"):
            converted.append({"role": role, "content": _text(message, "content")})
        else:
            has_assistant_turn = True
            blocks = _assistant_blocks(message)
            if any(block["type"] not in _THINKING_BLOCK_TYPES for block in blocks):
                converted.append({"role": "assistant", "content": blocks})
    if tool_results:
        converted.append({"role": "user", "content": tool_results})
    if not system:
        raise ValueError("A Claude request needs instructions before the first reply")
    return system, converted


def _assistant_blocks(message: Mapping[str, object]) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    if "provider_state" in message:
        state = message["provider_state"]
        assert isinstance(state, dict), "validate_tool_conversation checked provider_state"
        if state["provider"] != _ANTHROPIC_PROVIDER_STATE:
            raise ValueError(f"Cannot hand {state['provider']} state to Claude")
        blocks.extend(dict(item) for item in _objects(state, "items"))
    content = _text(message, "content")
    if content != "":
        blocks.append({"type": "text", "text": content})
    if "tool_calls" in message:
        for call in _objects(message, "tool_calls"):
            blocks.append({
                "type": "tool_use", "id": _text(call, "id"), "name": _text(call, "name"),
                "input": json.loads(_text(call, "arguments")),
            })
    return blocks


def _cache_tokens(reported: int | None) -> int:
    # Claude leaves a cache count out (None) when the request used no cache.
    if reported is None:
        return 0
    return reported


def claude_usage(usage: Usage) -> dict[str, int]:
    """Claude's usage in MetaList's shape: input counts what was read from and written to the cache too."""
    uncached = usage.input_tokens
    cached = _cache_tokens(usage.cache_read_input_tokens)
    cache_written = _cache_tokens(usage.cache_creation_input_tokens)
    prompt = uncached + cached + cache_written
    return {
        "prompt_tokens": prompt,
        "completion_tokens": usage.output_tokens,
        "total_tokens": prompt + usage.output_tokens,
        "uncached_input_tokens": uncached,
        "cached_input_tokens": cached,
        "cache_write_tokens": cache_written,
    }


def _raise_unless_finished(final: Message) -> None:
    """A reply cut off, declined, or ended any other way fails loudly."""
    if final.stop_reason in ("end_turn", "tool_use"):
        return
    if final.stop_reason == "max_tokens":
        raise AnthropicProviderError("Claude reached the maximum output-token limit before finishing the response")
    if final.stop_reason == "refusal":
        explanation = ""
        if final.stop_details is not None and final.stop_details.explanation is not None:
            explanation = f": {final.stop_details.explanation}"
        raise AnthropicProviderError(f"Claude declined to answer this request{explanation}")
    raise AnthropicProviderError(f"Claude ended the response with stop reason {final.stop_reason!r}")


class AnthropicInferenceAdapter:
    def __init__(self, *, api_key: str) -> None:
        if not isinstance(api_key, str) or api_key == "":
            raise ValueError("Claude inference requires an API key")
        self._api_key = api_key
        self._base_url = catalog_entry(_PROVIDER).base_url

    @property
    def provider_label(self) -> str:
        return _LABEL

    def _validate_base_url(self, base_url: str) -> None:
        if base_url != self._base_url:
            raise ValueError("Claude inference requires the official API base URL")

    def _client(self, on_wire_request: Callable[[dict[str, object]], None]) -> AsyncAnthropic:
        async def capture_wire_request(request: httpx2.Request) -> None:
            body = json.loads(await request.aread())
            if not isinstance(body, dict):
                raise TypeError("Claude wire request body must be an object")
            wire_request: dict[str, object] = {"method": request.method, "url": str(request.url), "body": body}
            record_provider_event("LLM_WIRE_REQUEST", wire_request)
            on_wire_request(wire_request)

        http_client = DefaultAsyncHttpxClient(
            event_hooks={"request": [capture_wire_request]},
            follow_redirects=False,
            trust_env=False,
        )
        return AsyncAnthropic(api_key=self._api_key, base_url=self._base_url, http_client=http_client, max_retries=0)

    async def inspect_context_window(self, *, base_url: str, model: str) -> InferenceContextWindow:
        self._validate_base_url(base_url)
        context_tokens = catalog_entry(_PROVIDER).context_tokens
        return InferenceContextWindow(
            model=validate_model_name(model),
            maximum_tokens=context_tokens,
            loaded_tokens=context_tokens,
            required_tokens=TARGET_AGENT_CONTEXT_TOKENS,
        )

    @record_structured_call
    async def infer_structured(
        self,
        *,
        base_url: str,
        model: str,
        thinking_level: str,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        on_progress: Callable[[StructuredInferenceProgress], None],
    ) -> InferenceResponse:
        self._validate_base_url(base_url)
        normalized_model = validate_model_name(model)
        effort = resolve_claude_effort(thinking_level)
        attempts = _StructuredAttempts(on_progress=on_progress)
        attempt_messages = messages
        while True:
            outcome = await self._structured_attempt(
                attempts=attempts, model=normalized_model, thinking_level=thinking_level, effort=effort,
                messages=attempt_messages, response_model=response_model,
            )
            if isinstance(outcome, BaseModel):
                attempts.succeed()
                return InferenceResponse(
                    content=outcome.model_dump_json(), thinking="",
                    usage=attempts.current.usage, attempts=attempts.freeze(),
                )
            if len(attempts.attempts) == _STRUCTURED_MAX_ATTEMPTS:
                raise StructuredInferenceError(attempts=attempts.freeze())
            attempt_messages = structured_retry_messages(
                original_messages=messages, failed_content=attempts.current.text,
                was_cut_off=attempts.current.was_cut_off, failure=outcome,
            )

    async def _structured_attempt(
        self,
        *,
        attempts: _StructuredAttempts,
        model: str,
        thinking_level: str,
        effort: str,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
    ) -> BaseModel | Exception:
        """One attempt: the validated reply, or the reply's flaw for the retry to explain."""
        system, request_messages = claude_request_messages(messages)
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": _structured_max_output_tokens(response_model),
            "system": system,
            "messages": request_messages,
            "thinking": _ADAPTIVE_THINKING,
            "output_config": {
                "effort": effort,
                "format": {"type": "json_schema", "schema": claude_strict_schema(response_model.model_json_schema())},
            },
            "cache_control": _CACHE_PREFIX,
        }
        attempts.start(request)
        client = self._client(attempts.record_wire_request)
        # lint: allow-PY001 rationale="Claude API and transport failures are external provider failures"
        try:
            async with client.messages.stream(**request, timeout=claude_silence_limit_seconds(thinking_level)) as stream:  # shockharness: ignore[EXC003] reason="opening Claude's stream is the external operation; its body reads that stream"
                async for event in stream:  # shockharness: ignore[EXC003] reason="each pull from Claude's stream is the external operation; the body records the event"
                    record_provider_chunk(event)
                    if event.type == "text":
                        attempts.record_text(event.text)
                final = await stream.get_final_message()
        # lint: allow-PY001 rationale="a request Claude never answers is a network failure, explained plainly"
        except APITimeoutError as exc:
            attempts.fail(exc)
            raise AnthropicProviderError(_silence_message(claude_silence_limit_seconds(thinking_level))) from exc
        # lint: allow-PY001 rationale="translate external Claude API failures into the provider-neutral contract"
        except APIError as exc:
            attempts.fail(exc)
            raise AnthropicProviderError(_provider_error_message(exc)) from exc
        finally:
            await client.close()
        attempts.finish(final)
        if final.stop_reason == "max_tokens":
            flaw = ValueError("The reply reached the output-token limit")
            attempts.fail(flaw)
            return flaw
        _raise_unless_finished(final)
        # lint: allow-PY001 rationale="model-produced structured JSON is external input and receives one bounded retry"
        try:
            return response_model.model_validate_json(attempts.current.text)
        # lint: allow-PY001 rationale="a reply that breaks the schema's rules is explained to the model on retry"
        except ValidationError as exc:
            attempts.fail(exc)
            return exc

    @record_text_call
    async def stream_text(
        self,
        *,
        base_url: str,
        model: str,
        thinking_level: str,
        messages: list[dict[str, str]],
        max_output_tokens: int,
        on_request: Callable[[dict[str, object]], None],
    ) -> AsyncIterator[dict[str, object]]:
        async for event in self._stream(
            base_url=base_url, model=model, thinking_level=thinking_level, messages=messages,
            tools=(), max_output_tokens=max_output_tokens, on_request=on_request,
        ):
            if event["type"] == "done":
                yield {"type": "done", "usage": event["usage"]}
                continue
            yield event

    @record_tool_turn
    async def stream_tool_turn(
        self,
        *,
        base_url: str,
        model: str,
        thinking_level: str,
        messages: list[dict[str, object]],
        tools: tuple[AgentTool, ...],
        max_output_tokens: int,
        on_request: Callable[[dict[str, object]], None],
    ) -> AsyncIterator[dict[str, object]]:
        if not isinstance(tools, tuple) or not tools or not all(isinstance(tool, AgentTool) for tool in tools):
            raise TypeError("A tool turn needs a non-empty tuple of AgentTool")
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("Tool names must be unique")
        async for event in self._stream(
            base_url=base_url, model=model, thinking_level=thinking_level, messages=messages,
            tools=tools, max_output_tokens=max_output_tokens, on_request=on_request,
        ):
            yield event

    async def _stream(
        self,
        *,
        base_url: str,
        model: str,
        thinking_level: str,
        messages: Sequence[Mapping[str, object]],
        tools: tuple[AgentTool, ...],
        max_output_tokens: int,
        on_request: Callable[[dict[str, object]], None],
    ) -> AsyncIterator[dict[str, object]]:
        self._validate_base_url(base_url)
        normalized_model = validate_model_name(model)
        effort = resolve_claude_effort(thinking_level)
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool) or max_output_tokens < 1:
            raise ValueError("Claude maximum output tokens must be positive")
        system, request_messages = claude_request_messages(messages)
        request: dict[str, Any] = {
            "model": normalized_model,
            "max_tokens": max_output_tokens,
            "system": system,
            "messages": request_messages,
            "thinking": _ADAPTIVE_THINKING,
            "output_config": {"effort": effort},
            "cache_control": _CACHE_PREFIX,
        }
        if tools:
            request["tools"] = [_claude_tool(tool) for tool in tools]
            request["tool_choice"] = {"type": "auto"}
        client = self._client(on_request)
        has_provider_started = False
        # lint: allow-PY001 rationale="Claude streaming and transport failures are external provider failures"
        try:
            async with client.messages.stream(**request, timeout=claude_silence_limit_seconds(thinking_level)) as stream:  # shockharness: ignore[EXC003] reason="opening Claude's stream is the external operation; its body reads that stream"
                async for event in stream:  # shockharness: ignore[EXC003] reason="each pull from Claude's stream is the external operation; the body forwards the event"
                    if not has_provider_started:
                        # Claude's first signal: the request was received (the chat stops showing "Waiting").
                        has_provider_started = True
                        yield {"type": "provider_started"}
                    record_provider_chunk(event)
                    if event.type == "text" and event.text != "":
                        yield {"type": "content_delta", "text": event.text}
                final = await stream.get_final_message()
        # lint: allow-PY001 rationale="a request Claude never answers is a network failure, explained plainly"
        except APITimeoutError as exc:
            raise AnthropicProviderError(_silence_message(claude_silence_limit_seconds(thinking_level))) from exc
        # lint: allow-PY001 rationale="translate external Claude stream failures into the provider-neutral contract"
        except APIError as exc:
            raise AnthropicProviderError(_provider_error_message(exc)) from exc
        finally:
            await client.close()
        _raise_unless_finished(final)
        thinking_items: list[dict[str, object]] = []
        tool_calls: list[dict[str, str]] = []
        for block in final.content:
            if block.type in _THINKING_BLOCK_TYPES:
                thinking_items.append(block.model_dump(mode="json", exclude_none=True))
            elif block.type == "tool_use":
                tool_calls.append({"id": block.id, "name": block.name, "arguments": json.dumps(block.input)})
        for call in tool_calls:
            yield {"type": "tool_call", **call}
        finish_reason = "stop"
        if tool_calls:
            finish_reason = "tool_calls"
        done: dict[str, object] = {"type": "done", "finish_reason": finish_reason, "usage": claude_usage(final.usage)}
        if thinking_items:
            done["provider_state"] = {"provider": _ANTHROPIC_PROVIDER_STATE, "items": thinking_items}
        yield done


@dataclass(slots=True)
class _Attempt:
    request: dict[str, object]
    started_at: float
    wire_request: dict[str, object]
    response: dict[str, object]
    usage: dict[str, int]
    error: str
    duration_ms: float
    text: str
    was_cut_off: bool
    output_tokens: int
    reported_tokens: int
    partial_output: dict[str, object]
    validation_errors: tuple[dict[str, str], ...]


class _StructuredAttempts:
    """The attempts of one structured request, reported as they progress (StructuredInferenceProgress)."""

    def __init__(self, *, on_progress: Callable[[StructuredInferenceProgress], None]) -> None:
        self._on_progress = on_progress
        self.attempts: list[_Attempt] = []

    @property
    def current(self) -> _Attempt:
        if not self.attempts:
            raise RuntimeError("A structured attempt event arrived before its request")
        return self.attempts[-1]

    def start(self, request: dict[str, Any]) -> None:
        self.attempts.append(_Attempt(
            request=json.loads(json.dumps(request)), started_at=time.perf_counter(), wire_request={}, response={},
            usage={}, error="", duration_ms=0.0, text="", was_cut_off=False, output_tokens=0, reported_tokens=0,
            partial_output={}, validation_errors=(),
        ))

    def record_wire_request(self, wire_request: dict[str, object]) -> None:
        if self.current.wire_request:
            raise RuntimeError("Claude emitted more than one HTTP request for one attempt")
        self.current.wire_request = wire_request
        self._emit("attempt_started", failure_kind="", error=None)

    def record_text(self, text: str) -> None:
        attempt = self.current
        attempt.text += text
        attempt.output_tokens = estimate_text_tokens(attempt.text)
        partial = from_json(attempt.text, allow_partial=True)
        if isinstance(partial, dict):
            attempt.partial_output = partial
        if attempt.output_tokens >= attempt.reported_tokens + _OUTPUT_PROGRESS_STEP_TOKENS:
            attempt.reported_tokens = attempt.output_tokens
            self._emit("output_progress", failure_kind="", error=None)

    def finish(self, final: Message) -> None:
        attempt = self.current
        attempt.response = final.model_dump(mode="json")
        attempt.usage = claude_usage(final.usage)
        attempt.was_cut_off = final.stop_reason == "max_tokens"
        attempt.output_tokens = final.usage.output_tokens
        attempt.duration_ms = (time.perf_counter() - attempt.started_at) * MS_PER_SECOND
        self._emit("response_received", failure_kind="", error=None)

    def fail(self, error: Exception) -> None:
        attempt = self.current
        attempt.error = f"{type(error).__name__}: {error}"
        if isinstance(error, ValidationError):
            attempt.validation_errors = _broken_rules(error)
        attempt.duration_ms = (time.perf_counter() - attempt.started_at) * MS_PER_SECOND
        failure_kind = "Structured output invalid"
        phase = "retrying"
        if isinstance(error, APIError):
            failure_kind = "Provider request failed"
            phase = "attempt_failed"
        if len(self.attempts) == _STRUCTURED_MAX_ATTEMPTS:
            phase = "attempt_failed"
        if attempt.wire_request:
            self._emit(phase, failure_kind=failure_kind, error=error)

    def succeed(self) -> None:
        self._emit("attempt_succeeded", failure_kind="", error=None)

    def freeze(self) -> list[InferenceAttempt]:
        frozen = []
        for attempt in self.attempts:
            error = attempt.error
            if attempt.response == {} and error == "":
                error = "Incomplete provider response"
            frozen.append(InferenceAttempt(
                request=attempt.request, response=attempt.response, error=error,
                duration_ms=attempt.duration_ms, validation_errors=attempt.validation_errors,
            ))
        return frozen

    def _emit(self, phase: str, *, failure_kind: str, error: Exception | None) -> None:
        attempt = self.current
        error_type = ""
        error_message = ""
        if error is not None:
            error_type = type(error).__name__
            error_message = str(error)
        self._on_progress(StructuredInferenceProgress(
            phase=phase, attempt=len(self.attempts), max_attempts=_STRUCTURED_MAX_ATTEMPTS,
            failure_kind=failure_kind, error_type=error_type, error_message=error_message,
            duration_ms=attempt.duration_ms, wire_request=dict(attempt.wire_request),
            output_tokens_received=attempt.output_tokens, partial_output=dict(attempt.partial_output),
        ))
