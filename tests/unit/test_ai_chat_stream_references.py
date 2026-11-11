import asyncio
import json

import pytest

from app.services.ai_chat import NO_REQUEST
from app.services.ai_chat import AiChatSessionStore
from app.services.ai_chat_stream import ChatTurnStream
from app.services.agent.web_evidence import WebEvidenceStore
from app.services.note_store import NoteStore


def _delta(text: str, note_ids: list[str]) -> dict[str, object]:
    return {"type": "content_delta", "text": text, "reference_note_ids": note_ids, "reference_web_ids": []}


def _stream_lines(events: list[dict[str, object]]) -> list[dict[str, object]]:
    store = AiChatSessionStore()
    turn_id = store.start_turn(user_content="question", provider="openai", model="test")
    stream = ChatTurnStream(store=store, notes=NoteStore(), session_key="refs", turn_id=turn_id,
                            initial_input_tokens=1, web_evidence_store=WebEvidenceStore())

    async def source():
        for event in events:
            yield event

    async def consume() -> list[dict[str, object]]:
        return [json.loads(line) async for line in stream.events(source())]

    return asyncio.run(consume())


def test_references_may_grow_while_a_tool_using_answer_streams() -> None:
    lines = _stream_lines([
        _delta("I'll check your notes. ", []),
        _delta("Found it.", ["note-1"]),
        {"type": "done", "reference_note_ids": ["note-1"], "reference_web_ids": [], "actions": [], "request_tokens": NO_REQUEST},
    ])
    assert lines[-1]["type"] == "done"


def test_references_shown_earlier_are_never_dropped() -> None:
    with pytest.raises(RuntimeError, match="only grow"):
        _stream_lines([
            _delta("First.", ["note-1"]),
            _delta("Second.", ["note-2"]),
        ])
