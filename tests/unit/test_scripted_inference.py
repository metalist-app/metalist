"""The scripted AI of a test server (app/services/agent/scripted_inference.py): plays a
script file through the real agent loop, restarts it for every question, is set up without
a key, and is refused on a server using the user's own vault."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services import ai_setup
from app.services.ai_credentials import AiCredentialStatus
from app.services.agent.scripted_inference import (
    SCRIPTED_AI_LABEL,
    ScriptedInferenceAdapter,
    load_script,
    scripted_ai_script_path,
)
from test_agent_loop import _StubTagging, _answer, _ignore, _run_agent

FIXTURE_SCRIPT = Path(__file__).resolve().parents[1] / "fixtures" / "scripted-ai" / "search-view.json"
# A script whose search matches a note of the unit snapshot (test_agent_scoped_runtime._snapshot).
ALPHA_SCRIPT = {"turns": [
    {"text": "", "calls": [{"name": "search_view_notes", "arguments": {"query": "ALPHA"}}]},
    {"text": "Two notes |mention alpha.", "calls": []},
]}


def _script_file(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _ask(adapter: ScriptedInferenceAdapter, message: str) -> list[dict[str, object]]:
    return _run_agent(adapter, web_mode="none", message=message, tagging=_StubTagging(), on_event=_ignore)


def test_the_fixture_script_searches_the_view_then_answers() -> None:
    turns = load_script(FIXTURE_SCRIPT)

    assert [turn.text == "" for turn in turns] == [True, False]
    assert [call.name for call in turns[0].calls] == ["search_view_notes"] and turns[0].calls[0].arguments == {"query": "harbor"}
    assert turns[1].calls == ()


def test_every_question_plays_the_script_from_its_first_turn(tmp_path: Path) -> None:
    adapter = ScriptedInferenceAdapter(turns=load_script(_script_file(tmp_path, ALPHA_SCRIPT)))

    first = _ask(adapter, "What is here?")
    second = _ask(adapter, "And again?")

    for events in (first, second):
        assert _answer(events) == "Two notes mention alpha."
        actions = events[-1]["actions"]
        assert [(action["tool"], action["query"], action["matching_notes"]) for action in actions] == [
            ("search_view_notes", "ALPHA", 2),
        ]


def test_a_script_too_short_for_the_question_fails_loud(tmp_path: Path) -> None:
    adapter = ScriptedInferenceAdapter(turns=load_script(_script_file(tmp_path, {"turns": [ALPHA_SCRIPT["turns"][1]]})))

    async def second_turn() -> None:
        async for _ in adapter.stream_text(
            base_url="", model="m", thinking_level="low", on_request=_ignore,
            messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        ):
            pass

    with pytest.raises(AssertionError, match="1 turns and this question asked for turn 2"):
        asyncio.run(second_turn())


def test_a_malformed_script_is_refused_naming_the_fault(tmp_path: Path) -> None:
    faults = {
        "a script is an object with one key, turns": ["not", "an", "object"],
        "needs at least one turn": {"turns": []},
        "turn 0 must have exactly the keys text and calls": {"turns": [{"text": "x"}]},
        "turn 0, call 0 must have exactly the keys name and arguments": {"turns": [{"text": "", "calls": [{"name": "x"}]}]},
        "name is a non-empty string and arguments an object": {"turns": [{"text": "", "calls": [{"name": "", "arguments": {}}]}]},
    }
    for message, document in faults.items():
        with pytest.raises(ValueError, match=message):
            load_script(_script_file(tmp_path, document))


def test_the_variable_is_honoured_only_on_a_test_server(tmp_path: Path) -> None:
    assert scripted_ai_script_path(environ={}) is None
    assert scripted_ai_script_path(environ={"METALIST_DATA_DIRECTORY": str(tmp_path),
                                            "METALIST_SCRIPTED_AI": str(FIXTURE_SCRIPT)}) == FIXTURE_SCRIPT
    with pytest.raises(RuntimeError, match="this server uses the user's vault"):
        scripted_ai_script_path(environ={"METALIST_SCRIPTED_AI": str(FIXTURE_SCRIPT)})
    with pytest.raises(RuntimeError, match="absolute path of a script file"):
        scripted_ai_script_path(environ={"METALIST_DATA_DIRECTORY": str(tmp_path), "METALIST_SCRIPTED_AI": "relative.json"})


class _NoKeys:
    """A credential store with no key for any provider."""

    def status(self, *, token: str, session_key: str) -> object:
        del token, session_key
        return AiCredentialStatus(configured=False, persistent=False)

    def resolve(self, *, token: str, session_key: str) -> str:
        raise AssertionError("a scripted AI never asks for a key")


def test_the_scripted_ai_is_set_up_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_setup, "ai_credential_store", lambda provider: _NoKeys())
    assert ai_setup.describe_ai_setup(token="token", session_key="session").ready_providers == ()
    with pytest.raises(ai_setup.AiNotSetUp):
        ai_setup.connect_to_ai(provider="openai", token="token", session_key="session")

    monkeypatch.setenv("METALIST_SCRIPTED_AI", str(FIXTURE_SCRIPT))

    assert ai_setup.describe_ai_setup(token="token", session_key="session").ready_providers == ("openai",)
    connection = ai_setup.connect_to_ai(provider="openai", token="token", session_key="session")
    assert connection.label == SCRIPTED_AI_LABEL and connection.inference.provider_label == SCRIPTED_AI_LABEL
