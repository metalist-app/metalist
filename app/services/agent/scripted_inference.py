"""A scripted AI for a test server: the turns of every chat come from a JSON file, so a
browser suite or a throwaway MetaList runs the real agent loop, its tools and its frozen scope
without any provider (PLAN.md, scale testing, part 1: the 0.26.0 freezes were in that code,
which no browser test ran).

``METALIST_SCRIPTED_AI=<file>`` names the script. It is honoured only on a server with its
own data folder (``METALIST_DATA_DIRECTORY`` set, as every test server and throwaway has);
on a server using the user's own vault it is a startup error, so a real MetaList can never
answer from a script.

The file holds ``{"turns": [{"text": ..., "calls": [{"name": ..., "arguments": {...}}]}]}``.
Each question plays the turns from the first: turn k answers the k-th model call of that
question (counted by the assistant messages after the user's message), so one script serves
every question of a run. A question that needs more turns than the script has is a failure
of the script, raised as such.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from app.services.agent.inference import (
    TARGET_AGENT_CONTEXT_TOKENS,
    InferenceContextWindow,
    InferenceResponse,
    StructuredInferenceProgress,
)
from app.services.agent.token_estimation import estimate_text_tokens
from app.services.agent.tool_calling import AgentTool, estimate_tool_conversation_tokens, validate_tool_conversation

SCRIPTED_AI_ENVIRONMENT_VARIABLE = "METALIST_SCRIPTED_AI"
_DATA_DIRECTORY_ENVIRONMENT_VARIABLE = "METALIST_DATA_DIRECTORY"
# What the chat shows while connecting ("Connecting to Scripted AI (test)").
SCRIPTED_AI_LABEL = "Scripted AI (test)"
# The window a scripted model reads: as large as the largest shipped model's, so a whole
# vault's scope fits, as it does for the providers the scale checks stand in for.
_SCRIPTED_CONTEXT_TOKENS = 1_000_000
_FINISH_REASON_WITH_CALLS = "tool_calls"
_FINISH_REASON_WITHOUT_CALLS = "stop"


def scripted_ai_script_path(*, environ: Mapping[str, str]) -> Path | None:
    """The script a test server answers from, or None when the AI is a real provider.
    Raises when the variable is set where a script must never answer."""
    if SCRIPTED_AI_ENVIRONMENT_VARIABLE not in environ:
        return None
    if _DATA_DIRECTORY_ENVIRONMENT_VARIABLE not in environ:
        raise RuntimeError(
            f"{SCRIPTED_AI_ENVIRONMENT_VARIABLE} is set, but a scripted AI runs only on a test server with "
            f"its own data folder ({_DATA_DIRECTORY_ENVIRONMENT_VARIABLE}); this server uses the user's vault"
        )
    path = Path(environ[SCRIPTED_AI_ENVIRONMENT_VARIABLE])
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError(f"{SCRIPTED_AI_ENVIRONMENT_VARIABLE} must be the absolute path of a script file, got {path}")
    return path


@dataclass(frozen=True, slots=True)
class ScriptedCall:
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ScriptedTurn:
    # Written as the answer; a "|" splits it into the chunks streamed.
    text: str
    calls: tuple[ScriptedCall, ...]


def load_script(path: Path) -> tuple[ScriptedTurn, ...]:
    """The turns of a script file; a malformed file is an error naming what is wrong."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"turns"} or not isinstance(document["turns"], list):
        raise ValueError(f"{path}: a script is an object with one key, turns, holding a list")
    if not document["turns"]:
        raise ValueError(f"{path}: a script needs at least one turn")
    return tuple(_turn_from(path, index, turn) for index, turn in enumerate(document["turns"]))


def _turn_from(path: Path, index: int, turn: object) -> ScriptedTurn:
    if not isinstance(turn, dict) or set(turn) != {"text", "calls"}:
        raise ValueError(f"{path}: turn {index} must have exactly the keys text and calls")
    if not isinstance(turn["text"], str) or not isinstance(turn["calls"], list):
        raise ValueError(f"{path}: turn {index}: text is a string and calls a list")
    calls = []
    for call_index, call in enumerate(turn["calls"]):
        if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
            raise ValueError(f"{path}: turn {index}, call {call_index} must have exactly the keys name and arguments")
        if not isinstance(call["name"], str) or call["name"] == "" or not isinstance(call["arguments"], dict):
            raise ValueError(f"{path}: turn {index}, call {call_index}: name is a non-empty string and arguments an object")
        calls.append(ScriptedCall(name=call["name"], arguments=dict(call["arguments"])))
    return ScriptedTurn(text=turn["text"], calls=tuple(calls))


def _turn_index(messages: list[dict[str, object]]) -> int:
    """How many times the model has already answered this question: the assistant messages
    after the last user message."""
    assistant_turns = 0
    for message in messages:
        if message["role"] == "user":
            assistant_turns = 0
        elif message["role"] == "assistant":
            assistant_turns += 1
    return assistant_turns


class ScriptedInferenceAdapter:
    """An InferenceAdapter that plays a script (load_script) instead of calling a provider."""

    provider_label = SCRIPTED_AI_LABEL

    def __init__(self, *, turns: tuple[ScriptedTurn, ...]) -> None:
        assert turns, "a scripted AI needs at least one turn"
        self._turns = turns

    def _turn_for(self, messages: list[dict[str, object]]) -> ScriptedTurn:
        index = _turn_index(messages)
        if index >= len(self._turns):
            raise AssertionError(
                f"the scripted AI has {len(self._turns)} turns and this question asked for turn {index + 1}: "
                "the script is too short for what the agent did"
            )
        return self._turns[index]

    async def inspect_context_window(self, *, base_url: str, model: str) -> InferenceContextWindow:
        del base_url
        return InferenceContextWindow(
            model=model, maximum_tokens=_SCRIPTED_CONTEXT_TOKENS, loaded_tokens=_SCRIPTED_CONTEXT_TOKENS,
            required_tokens=TARGET_AGENT_CONTEXT_TOKENS,
        )

    async def infer_structured(
        self, *, base_url: str, model: str, thinking_level: str, messages: list[dict[str, str]],
        response_model: type[BaseModel], on_progress: Callable[[StructuredInferenceProgress], None],
    ) -> InferenceResponse:
        del base_url, model, thinking_level, messages, on_progress
        raise AssertionError(f"the scripted AI has no structured answers (asked for {response_model.__name__})")

    async def stream_text(
        self, *, base_url: str, model: str, thinking_level: str, messages: list[dict[str, str]],
        on_request: Callable[[dict[str, object]], None],
    ) -> AsyncIterator[dict[str, object]]:
        del base_url, model, thinking_level
        conversation: list[dict[str, object]] = [dict(message) for message in messages]
        on_request({"messages": len(conversation)})
        turn = self._turn_for(conversation)
        for chunk in turn.text.split("|"):
            if chunk:
                yield {"type": "content_delta", "text": chunk}
        yield {"type": "done", "usage": self._usage(conversation, turn)}

    async def stream_tool_turn(
        self, *, base_url: str, model: str, thinking_level: str, messages: list[dict[str, object]],
        tools: tuple[AgentTool, ...], on_request: Callable[[dict[str, object]], None],
    ) -> AsyncIterator[dict[str, object]]:
        del base_url, model, thinking_level
        validate_tool_conversation(messages)
        offered = {tool.name for tool in tools}
        on_request({"messages": len(messages)})
        turn = self._turn_for(messages)
        for chunk in turn.text.split("|"):
            if chunk:
                yield {"type": "content_delta", "text": chunk}
        turn_number = _turn_index(messages) + 1
        for index, call in enumerate(turn.calls):
            if call.name not in offered:
                raise AssertionError(f"the script calls {call.name}, which the agent did not offer ({sorted(offered)})")
            yield {"type": "tool_call", "id": f"scripted-{turn_number}-{index}", "name": call.name,
                   "arguments": json.dumps(call.arguments)}
        finish_reason = _FINISH_REASON_WITHOUT_CALLS
        if turn.calls:
            finish_reason = _FINISH_REASON_WITH_CALLS
        yield {"type": "done", "finish_reason": finish_reason, "usage": self._usage(messages, turn)}

    @staticmethod
    def _usage(messages: list[dict[str, object]], turn: ScriptedTurn) -> dict[str, int]:
        prompt_tokens = estimate_tool_conversation_tokens(messages)
        return {"prompt_tokens": prompt_tokens, "input_tokens": prompt_tokens,
                "output_tokens": estimate_text_tokens(turn.text)}


def scripted_ai_adapter(*, environ: Mapping[str, str]) -> ScriptedInferenceAdapter | None:
    """The adapter for the script the environment names, or None for a real provider."""
    path = scripted_ai_script_path(environ=environ)
    if path is None:
        return None
    return ScriptedInferenceAdapter(turns=load_script(path))
