"""Inference through a provider's OpenAI-compatible Chat Completions endpoint.

Gemini is the first such provider (docs/ready-to-build/ai-providers.md, Design §1):
Google's compatibility endpoint offers Chat Completions only, not the Responses API
the OpenAI adapter uses for tool turns. A later OpenAI-dialect provider is one more
OpenAICompatibleProvider row.

Thought signatures: Gemini puts them on a tool call as fields beyond the standard ones
and needs them back with that call on the next turn. Every extra field of a streamed
tool call is kept in `provider_state` and sent back unchanged with that call.

Structured replies go through Instructor's JSON_SCHEMA mode with strict schemas, as for
OpenAI (strict_structured_outputs.py, registered by importing openai_inference).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from typing import cast

import httpx
import instructor
from instructor.v2.core.client import AsyncInstructor
from openai import APIError
from openai import APITimeoutError
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.services.agent.history import record_provider_chunk
from app.services.agent.history import record_provider_event
from app.services.agent.history import record_structured_call
from app.services.agent.history import record_text_call
from app.services.agent.history import record_tool_turn
from app.services.agent.inference import InferenceContextWindow
from app.services.agent.inference import InferenceProviderError
from app.services.agent.inference import InferenceResponse
from app.services.agent.inference import StructuredInferenceProgress
from app.services.agent.inference import TARGET_AGENT_CONTEXT_TOKENS
from app.services.agent.inference import UNMEASURED_SILENCE_LIMIT_SECONDS
# Also registers strict structured outputs for Instructor's JSON_SCHEMA requests.
from app.services.agent.openai_inference import _extract_openai_token_usage
from app.services.agent.openai_inference import _strict_json_schema
from app.services.agent.structured_inference import _InstructorTraceCapture
from app.services.agent.structured_inference import _attach_trace_capture
from app.services.agent.structured_inference import _create_structured_completion
from app.services.agent.structured_inference import _extract_reasoning
from app.services.agent.structured_inference import _json_object
from app.services.agent.structured_inference import _structured_max_output_tokens
from app.services.agent.tool_calling import AgentTool
from app.services.agent.tool_calling import validate_tool_conversation
from app.services.ai_catalog import catalog_entry
from app.services.ai_catalog import validate_model_name


@dataclass(frozen=True, slots=True)
class OpenAICompatibleProvider:
    provider: str
    label: str
    # MetaList's thinking level as the endpoint's reasoning_effort.
    reasoning_effort: dict[str, str]


# Gemini 4 Argon and 3.8 Flash cannot turn thinking off and start at "low"
# (Google's thinking guide, 2026-10-23), so Off asks for the least.
GEMINI = OpenAICompatibleProvider(
    provider="gemini",
    label="Google",
    reasoning_effort={"off": "low", "low": "low", "medium": "medium", "high": "high"},
)

_PROVIDER_ERROR_DETAIL_CHARS = 500
# The fields every streamed tool call has; any other field is the provider's own.
_STANDARD_TOOL_CALL_FIELDS = frozenset({"index", "id", "type", "function"})


class OpenAICompatibleProviderError(InferenceProviderError):
    """Expected API or transport failure of an OpenAI-compatible provider."""


def compatible_silence_limit_seconds(thinking_level: str) -> float:
    if thinking_level not in UNMEASURED_SILENCE_LIMIT_SECONDS:
        raise ValueError(f"Unsupported thinking level: {thinking_level}")
    return UNMEASURED_SILENCE_LIMIT_SECONDS[thinking_level]


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


def chat_completions_messages(provider: str, messages: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """A MetaList conversation as Chat Completions messages, the provider's own tool-call
    fields restored from provider_state. An empty reply (no text, no calls) is left out."""
    conversation = [dict(message) for message in messages]
    validate_tool_conversation(conversation)
    converted: list[dict[str, object]] = []
    for message in conversation:
        role = message["role"]
        if role in ("system", "user"):
            converted.append({"role": role, "content": _text(message, "content")})
            continue
        if role == "tool":
            converted.append({"role": "tool", "tool_call_id": _text(message, "tool_call_id"), "content": _text(message, "content")})
            continue
        extra_fields: dict[str, object] = {}
        if "provider_state" in message:
            state = message["provider_state"]
            assert isinstance(state, dict), "validate_tool_conversation checked provider_state"
            if state["provider"] != provider:
                raise ValueError(f"Cannot hand {state['provider']} state to {provider}")
            extra_fields = {_text(item, "tool_call_id"): item["fields"] for item in _objects(state, "items")}
        content = _text(message, "content")
        if "tool_calls" not in message:
            if content != "":
                converted.append({"role": "assistant", "content": content})
            continue
        calls: list[dict[str, object]] = []
        for call in _objects(message, "tool_calls"):
            call_id = _text(call, "id")
            fields: dict[str, object] = {}
            if call_id in extra_fields:
                saved = extra_fields[call_id]
                assert isinstance(saved, dict), "provider_state fields are an object"
                fields = saved
            calls.append({"id": call_id, "type": "function",
                          "function": {"name": _text(call, "name"), "arguments": _text(call, "arguments")}, **fields})
        # Chat Completions writes "no text beside the calls" as null.
        reply: dict[str, object] = {"role": "assistant", "content": None, "tool_calls": calls}
        if content != "":
            reply["content"] = content
        converted.append(reply)
    return converted


def _compatible_tool(tool: AgentTool) -> dict[str, object]:
    return {"type": "function", "function": {
        "name": tool.name, "description": tool.description, "parameters": _strict_json_schema(tool.arguments_schema()),
    }}


def http_client(on_wire_request: Callable[[httpx.Request], object]) -> httpx.AsyncClient:
    """The provider's own HTTP client: no redirects, no proxy settings from the environment."""
    return httpx.AsyncClient(event_hooks={"request": [on_wire_request]}, follow_redirects=False, trust_env=False)


class _StreamedToolCall:
    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments = ""
        self.extra_fields: dict[str, object] = {}

    def add(self, delta: dict[str, Any]) -> None:
        if "id" in delta and delta["id"] is not None:
            self.id = str(delta["id"])
        if "function" in delta and delta["function"] is not None:
            function = delta["function"]
            if "name" in function and function["name"] is not None:
                self.name += str(function["name"])
            if "arguments" in function and function["arguments"] is not None:
                self.arguments += str(function["arguments"])
        for key, value in delta.items():
            if key not in _STANDARD_TOOL_CALL_FIELDS and value is not None:
                self.extra_fields[key] = value

    def as_call(self) -> dict[str, str]:
        if self.id == "" or self.name == "":
            raise OpenAICompatibleProviderError("The provider streamed a tool call without its id or name")
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


class OpenAICompatibleInferenceAdapter:
    def __init__(self, *, api_key: str, provider: OpenAICompatibleProvider) -> None:
        if not isinstance(api_key, str) or api_key == "":
            raise ValueError(f"{provider.label} inference requires an API key")
        self._api_key = api_key
        self._provider = provider
        self._base_url = catalog_entry(provider.provider).base_url

    @property
    def provider_label(self) -> str:
        return self._provider.label

    def _validate_base_url(self, base_url: str) -> None:
        if base_url != self._base_url:
            raise ValueError(f"{self._provider.label} inference requires the official API base URL")

    def _reasoning_effort(self, thinking_level: str) -> str:
        if thinking_level not in self._provider.reasoning_effort:
            raise ValueError(f"Unsupported thinking level: {thinking_level}")
        return self._provider.reasoning_effort[thinking_level]

    def _silence_error(self, thinking_level: str) -> OpenAICompatibleProviderError:
        seconds = compatible_silence_limit_seconds(thinking_level)
        return OpenAICompatibleProviderError(
            f"{self._provider.label} did not respond for {seconds:g} seconds. Check your internet connection and ask again."
        )

    def _api_error(self, exc: APIError) -> OpenAICompatibleProviderError:
        detail = " ".join(str(exc).split())
        if detail == "":
            return OpenAICompatibleProviderError(f"{self._provider.label} API request failed")
        return OpenAICompatibleProviderError(
            f"{self._provider.label} API request failed: {detail[:_PROVIDER_ERROR_DETAIL_CHARS]}"
        )

    def _client(self, on_wire_request: Callable[[httpx.Request], object]) -> AsyncOpenAI:
        return AsyncOpenAI(api_key=self._api_key, base_url=self._base_url, http_client=http_client(on_wire_request), max_retries=0)

    def _capture_requests(self, on_request: Callable[[dict[str, object]], None]) -> Callable[[httpx.Request], object]:
        async def capture_wire_request(request: httpx.Request) -> None:
            body = json.loads(await request.aread())
            if not isinstance(body, dict):
                raise TypeError(f"{self._provider.label} wire request body must be an object")
            wire_request: dict[str, object] = {"method": request.method, "url": str(request.url), "body": body}
            record_provider_event("LLM_WIRE_REQUEST", wire_request)
            on_request(wire_request)
        return capture_wire_request

    async def inspect_context_window(self, *, base_url: str, model: str) -> InferenceContextWindow:
        self._validate_base_url(base_url)
        context_tokens = catalog_entry(self._provider.provider).context_tokens
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
        capture = _InstructorTraceCapture(on_progress=on_progress)
        client = cast(AsyncInstructor, instructor.from_openai(
            self._client(capture.record_wire_request), model=normalized_model, mode=instructor.Mode.JSON_SCHEMA,
        ))
        _attach_trace_capture(client=client, capture=capture)
        request_options = {
            "max_completion_tokens": _structured_max_output_tokens(response_model),
            "timeout": compatible_silence_limit_seconds(thinking_level),
            "reasoning_effort": self._reasoning_effort(thinking_level),
            "stream_options": {"include_usage": True},
        }
        # lint: allow-PY001 rationale="the provider's API and transport failures are external provider failures"
        try:
            parsed, raw_completion = await _create_structured_completion(
                client=client, capture=capture, response_model=response_model,
                messages=messages, request_options=request_options,
            )
        # lint: allow-PY001 rationale="a request the provider never answers is a network failure, explained plainly"
        except APITimeoutError as exc:
            raise self._silence_error(thinking_level) from exc
        # lint: allow-PY001 rationale="translate the provider's API failures into the provider-neutral contract"
        except APIError as exc:
            raise self._api_error(exc) from exc
        finally:
            for number, attempt in enumerate(capture.freeze(), 1):
                record_provider_event("LLM_ATTEMPT_OUTPUT", {
                    "attempt": number, "response": attempt.response,
                    "error": attempt.error, "duration_ms": attempt.duration_ms,
                })
        if not isinstance(parsed, response_model):
            raise TypeError("Instructor returned the wrong structured response type")
        capture.record_success()
        raw_response = _json_object(raw_completion)
        attempts = capture.freeze()
        if len(attempts) == 0:
            raise RuntimeError("Instructor returned without recording an inference attempt")
        return InferenceResponse(
            content=parsed.model_dump_json(),
            thinking=_extract_reasoning(raw_response),
            usage=_extract_openai_token_usage(raw_response).as_inference_usage(),
            attempts=attempts,
        )

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
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool) or max_output_tokens < 1:
            raise ValueError(f"{self._provider.label} maximum output tokens must be positive")
        request: dict[str, Any] = {
            "model": normalized_model,
            "messages": chat_completions_messages(self._provider.provider, messages),
            "reasoning_effort": self._reasoning_effort(thinking_level),
            "max_completion_tokens": max_output_tokens,
            "timeout": compatible_silence_limit_seconds(thinking_level),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            request["tools"] = [_compatible_tool(tool) for tool in tools]
            request["tool_choice"] = "auto"
        client = self._client(self._capture_requests(on_request))
        streamed_calls: dict[int, _StreamedToolCall] = {}
        finish_reason = ""
        usage: dict[str, int] = {}
        has_provider_started = False
        # lint: allow-PY001 rationale="the provider's streaming and transport failures are external provider failures"
        try:
            stream = await client.chat.completions.create(**request)
            async for chunk in stream:  # shockharness: ignore[EXC003] reason="each pull from the provider's stream is the external operation; the body forwards and gathers the chunk"
                if not has_provider_started:
                    has_provider_started = True
                    yield {"type": "provider_started"}
                record_provider_chunk(chunk)
                if chunk.usage is not None:
                    usage = _extract_openai_token_usage({"usage": chunk.usage.model_dump()}).as_inference_usage()
                for choice in chunk.choices:
                    if choice.delta.content is not None and choice.delta.content != "":
                        yield {"type": "content_delta", "text": choice.delta.content}
                    if choice.delta.tool_calls is not None:
                        for call_delta in choice.delta.tool_calls:
                            if call_delta.index not in streamed_calls:
                                streamed_calls[call_delta.index] = _StreamedToolCall()
                            streamed_calls[call_delta.index].add(call_delta.model_dump(mode="json"))
                    if choice.finish_reason is not None:
                        finish_reason = choice.finish_reason
        # lint: allow-PY001 rationale="a request the provider never answers is a network failure, explained plainly"
        except APITimeoutError as exc:
            raise self._silence_error(thinking_level) from exc
        # lint: allow-PY001 rationale="translate the provider's stream failures into the provider-neutral contract"
        except APIError as exc:
            raise self._api_error(exc) from exc
        finally:
            await client.close()
        if finish_reason == "length":
            raise OpenAICompatibleProviderError(
                f"{self._provider.label} reached the maximum output-token limit before finishing the response"
            )
        if finish_reason not in ("stop", "tool_calls"):
            raise OpenAICompatibleProviderError(f"{self._provider.label} ended the response with finish reason {finish_reason!r}")
        if not usage:
            raise OpenAICompatibleProviderError(f"{self._provider.label} response stream ended before reporting its usage")
        calls = [streamed_calls[index] for index in sorted(streamed_calls)]
        for call in calls:
            yield {"type": "tool_call", **call.as_call()}
        done: dict[str, object] = {"type": "done", "finish_reason": "stop", "usage": usage}
        if calls:
            done["finish_reason"] = "tool_calls"
        signed = [{"tool_call_id": call.id, "fields": call.extra_fields} for call in calls if call.extra_fields]
        if signed:
            done["provider_state"] = {"provider": self._provider.provider, "items": signed}
        yield done
