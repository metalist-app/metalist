"""Provider-neutral inference contracts owned by MetaList."""

from __future__ import annotations

from collections.abc import AsyncIterator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from app.services.agent.tool_calling import AgentTool


MINIMUM_AGENT_CONTEXT_TOKENS = 16_384
TARGET_AGENT_CONTEXT_TOKENS = 32_768

# How long a provider not yet timed may stay silent before a request fails (OpenAI's
# limits are measured, openai_inference.py). As generous as OpenAI's Medium and High.
_UNMEASURED_LOW_THINKING_SILENCE_SECONDS = 30.0
_UNMEASURED_MEDIUM_THINKING_SILENCE_SECONDS = 60.0
_UNMEASURED_HIGH_THINKING_SILENCE_SECONDS = 120.0
UNMEASURED_SILENCE_LIMIT_SECONDS = {
    "off": _UNMEASURED_LOW_THINKING_SILENCE_SECONDS,
    "low": _UNMEASURED_LOW_THINKING_SILENCE_SECONDS,
    "medium": _UNMEASURED_MEDIUM_THINKING_SILENCE_SECONDS,
    "high": _UNMEASURED_HIGH_THINKING_SILENCE_SECONDS,
}


@dataclass(frozen=True, slots=True)
class InferenceAttempt:
    request: dict[str, object]
    response: dict[str, object]
    error: str
    duration_ms: float
    # Rules the model's reply broke, when it was rejected: each a dict with
    # field, kind, problem and value (for explaining the failure in the chat).
    validation_errors: tuple[dict[str, str], ...]


@dataclass(frozen=True, slots=True)
class InferenceResponse:
    content: str
    thinking: str
    usage: dict[str, int]
    attempts: list[InferenceAttempt]


@dataclass(frozen=True, slots=True)
class InferenceContextWindow:
    model: str
    maximum_tokens: int
    loaded_tokens: int
    required_tokens: int

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or self.model.strip() == "":
            raise ValueError("Inference context model must be non-empty")
        for label, value in (
            ("maximum_tokens", self.maximum_tokens),
            ("loaded_tokens", self.loaded_tokens),
            ("required_tokens", self.required_tokens),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"Inference context {label} must be positive")

    @property
    def is_sufficient(self) -> bool:
        return self.loaded_tokens >= self.required_tokens


@dataclass(frozen=True, slots=True)
class StructuredInferenceProgress:
    phase: str
    attempt: int
    max_attempts: int
    failure_kind: str
    error_type: str
    error_message: str
    duration_ms: float
    wire_request: dict[str, object]
    output_tokens_received: int
    # Latest Instructor partial object for this attempt ({} until one is parsed).
    partial_output: dict[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.partial_output, dict):
            raise TypeError("Structured inference partial output must be an object")
        if (
            not isinstance(self.output_tokens_received, int)
            or isinstance(self.output_tokens_received, bool)
            or self.output_tokens_received < 0
        ):
            raise ValueError("Structured inference output tokens must be non-negative")


class InferenceProviderError(RuntimeError):
    """Expected failure while communicating with an external model provider."""


class OutputLimitReached(InferenceProviderError):
    """A reply reached the longest the model can write. MetaList sets no limit of its own
    on answers (the maintainer, 2026-10-24): this happens only to a runaway reply, and
    the chat says so plainly, under whatever the model wrote."""

    def __init__(self, *, model: str) -> None:
        super().__init__(
            f"{model} reached the longest answer it can write before finishing (its thinking "
            "counts toward that), so the answer stopped there. Anything it wrote is kept above. "
            "Ask it to continue, or ask for a shorter answer."
        )


class StructuredInferenceError(InferenceProviderError):
    def __init__(self, *, attempts: list[InferenceAttempt]) -> None:
        assert attempts, "Structured inference failure must contain at least one attempt"
        attempt_count = len(attempts)
        if attempt_count == 1:
            attempt_summary = "1 attempt"
        else:
            attempt_summary = f"{attempt_count} attempts"
        super().__init__(
            f"The model could not produce a valid structured response after {attempt_summary}. "
            "Open Agent Debug for exact request and response details."
        )
        self.attempts = list(attempts)


class InferenceAdapter(Protocol):
    @property
    def provider_label(self) -> str:
        ...

    async def inspect_context_window(
        self,
        *,
        base_url: str,
        model: str,
    ) -> InferenceContextWindow:
        ...

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
        ...

    def stream_text(
        self,
        *,
        base_url: str,
        model: str,
        thinking_level: str,
        messages: list[dict[str, str]],
        on_request: Callable[[dict[str, object]], None],
    ) -> AsyncIterator[dict[str, object]]:
        ...

    def stream_tool_turn(
        self,
        *,
        base_url: str,
        model: str,
        thinking_level: str,
        messages: list[dict[str, object]],
        tools: tuple[AgentTool, ...],
        on_request: Callable[[dict[str, object]], None],
    ) -> AsyncIterator[dict[str, object]]:
        """One model turn in a tool conversation (see tool_calling.py for shapes).

        Yields ``{"type": "content_delta", "text"}`` as answer text arrives, then
        one ``{"type": "tool_call", "id", "name", "arguments"}`` per requested
        tool call (complete, after the model finished), then exactly one
        ``{"type": "done", "finish_reason": "stop" | "tool_calls", "usage"}``,
        which also carries ``"provider_state"`` when the provider returned state
        to hand back on the next turn (put it on the assistant message).
        Text and tool turns send no output limit of MetaList's own: the model may write
        as much as it can. A reply cut off at that maximum raises ``OutputLimitReached``;
        one ended any other way raises ``InferenceProviderError``.
        """
        ...
