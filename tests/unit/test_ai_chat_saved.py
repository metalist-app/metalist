"""The vault's AI conversation is saved in it (docs/ui/ai-chat.md, "Saved with the vault"): a
restart keeps it, only Clear Chat ends it, and in a vault with a password it is never on disk
unencrypted."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import Response

import app.api.routes.ai as ai_routes

from app.db.ai_chat_sql import fetch_ai_chat_row, upsert_ai_chat_row
from app.db.session import begin_writer
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, get_encryption_service, set_encryption_required, set_session_dek
from app.services.agent.cloud_privacy import HistoryDisclosure
from app.services.ai_chat import INTERRUPTED_ERROR, NO_REQUEST, AiChatSessionStore
from app.services.ai_chat_stream import ChatTurnStream
from app.services.agent.web_evidence import WebEvidenceStore
from app.services.agent.web_fetch import WebPageFetchResult
from app.services.note_store import NoteStore

QUESTION = "Which notes mention the lighthouse?"
ANSWER = "Two notes mention the lighthouse."
REQUEST = {"total": 900, "instructions": 500, "history": 100, "this_turn": 300}
ACTIONS = [{"action": "search", "query": "lighthouse"}]
NOTE_SEEN = "note-seen"
DEK = b"d" * 32
WEB_SESSION = "web-session"
PAGE_URL = "https://example.com/lighthouses"
PAGE_TITLE = "Lighthouses of the North Sea"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(SafeSession, "_db_path", tmp_path / "notes.db")
    SafeSession.use_memory_db()
    set_encryption_required(False)
    try:
        yield
    finally:
        clear_encryption_key()
        set_encryption_required(False)
        SafeSession.use_file_db()


def _disclosure(*, permitted: frozenset[str], hidden: frozenset[str]) -> HistoryDisclosure:
    return HistoryDisclosure(policy_key="policy", permitted_note_ids=permitted, hidden_note_ids=hidden)


def _restarted() -> AiChatSessionStore:
    """A store as a restarted MetaList has it: read from the vault."""
    store = AiChatSessionStore()
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:ai_chat_saved"):
            store.bootstrap(connection=session.connection())
    finally:
        session.close()
    return store


def _saved_row() -> dict[str, object] | None:
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:ai_chat_saved"):
            return fetch_ai_chat_row(session.connection())
    finally:
        session.close()


def _answered(store: AiChatSessionStore, question: str, answer: str) -> None:
    turn = store.start_turn(user_content=question, provider="openai", model="gpt-5.6-sol")
    store.append_activity(turn_id=turn, action="search", status="completed", label="Searched the notes",
                          approx_input_tokens=120, output_tokens_received=0, duration_ms=250.0)
    store.complete_turn(turn_id=turn, final_content=answer, actions=ACTIONS, request_tokens=REQUEST)


def _conversation_with_a_summary() -> AiChatSessionStore:
    store = AiChatSessionStore()
    store.synchronize_disclosure_boundary(disclosure=_disclosure(permitted=frozenset({NOTE_SEEN}), hidden=frozenset()))
    _answered(store, "First question", "First answer")
    source = store.summary_source()
    assert store.apply_summary(content="They asked one question.", turn_count=1,
                               history_start=source.history_start, session_id=source.session_id)
    _answered(store, QUESTION, ANSWER)
    return store


def test_a_restart_keeps_the_conversation_as_it_was(vault) -> None:
    before = _conversation_with_a_summary()

    after = _restarted()

    # What the chat shows (messages, progress, summaries and what the model still sees of each),
    # what the model is sent, the agent's records and the history meter's last request.
    assert after.snapshot() == before.snapshot()
    assert after.provider_messages() == before.provider_messages()
    assert after.earlier_actions() == before.earlier_actions()
    assert after.last_request() == REQUEST
    assert [summary["content"] for summary in after.snapshot()["summaries"]] == ["They asked one question."]


def test_a_question_being_answered_when_metalist_stops_comes_back_interrupted(vault) -> None:
    store = AiChatSessionStore()
    turn = store.start_turn(user_content=QUESTION, provider="openai", model="gpt-5.6-sol")
    store.append_delta(turn_id=turn, delta_kind="content", text="Half an ans")

    messages = _restarted().snapshot()["messages"]

    assert [(message["role"], message["status"]) for message in messages] == [("user", "complete"), ("assistant", "error")]
    assert messages[0]["content"] == QUESTION
    assert messages[1]["error"] == INTERRUPTED_ERROR
    # The next question can be asked: nothing is left streaming.
    _answered(_restarted(), "Again?", "Yes.")


def test_clear_chat_removes_it_from_the_vault(vault) -> None:
    store = _conversation_with_a_summary()
    assert _saved_row() is not None

    store.clear()

    assert _saved_row() is None
    assert store.snapshot() == {"messages": [], "summaries": []}
    assert _restarted().snapshot() == {"messages": [], "summaries": []}
    assert _restarted().last_request() == NO_REQUEST


def test_locking_or_logging_out_keeps_it_to_read_again(vault) -> None:
    store = _conversation_with_a_summary()
    shown = store.snapshot()

    store.reset()
    # Unread since the reset: starting a conversation would write over the saved one.
    with pytest.raises(RuntimeError, match="not read from the vault"):
        store.snapshot()
    session = SafeSession()
    try:
        with SafeSession.allow_reads("tests:ai_chat_saved"):
            store.bootstrap_if_reset(connection=session.connection())
    finally:
        session.close()

    assert store.snapshot() == shown


def test_in_a_vault_with_a_password_it_is_saved_encrypted(vault) -> None:
    set_encryption_required(True)
    set_session_dek(DEK)
    shown = _conversation_with_a_summary().snapshot()

    row = _saved_row()
    assert row is not None
    assert row["state_encryption_nonce"] is not None and row["state_encryption_tag"] is not None
    assert QUESTION not in str(row["state_json"]) and ANSWER not in str(row["state_json"])
    assert _restarted().snapshot() == shown

    # Locked: read but not decrypted, and no use until the key is back.
    clear_encryption_key()
    locked = _restarted()
    with pytest.raises(RuntimeError, match="vault is locked"):
        locked.snapshot()
    set_session_dek(DEK)
    locked.ensure_decrypted(token="")
    assert locked.snapshot() == shown


def test_setting_and_removing_a_password_rewrite_it(vault) -> None:
    store = _conversation_with_a_summary()
    shown = store.snapshot()
    set_encryption_required(True)
    set_session_dek(DEK)

    with begin_writer() as connection:
        store.rewrite_persisted_state(encryption_service=get_encryption_service(), force_plaintext=False,
                                      connection=connection)
    row = _saved_row()
    assert row is not None and row["state_encryption_nonce"] is not None and QUESTION not in str(row["state_json"])
    assert _restarted().snapshot() == shown

    with begin_writer() as connection:
        store.rewrite_persisted_state(encryption_service=None, force_plaintext=True, connection=connection)
    row = _saved_row()
    assert row is not None and row["state_encryption_nonce"] is None and QUESTION in str(row["state_json"])
    clear_encryption_key()
    set_encryption_required(False)
    assert _restarted().snapshot() == shown


def test_a_note_made_private_while_metalist_was_stopped_holds_the_history_back(vault) -> None:
    store = _conversation_with_a_summary()
    assert store.provider_messages() != []

    after = _restarted()
    is_reset = after.synchronize_disclosure_boundary(
        disclosure=_disclosure(permitted=frozenset(), hidden=frozenset({NOTE_SEEN})))

    assert is_reset
    assert after.provider_messages() == []
    assert {message["visibility"] for message in after.snapshot()["messages"]} == {"held_back"}
    # Saved so: another restart does not send it again.
    assert _restarted().provider_messages() == []


def _answered_citing_a_web_page() -> None:
    """An answer streamed as the chat streams it, citing a page the AI opened."""
    web_pages = WebEvidenceStore()
    page = web_pages.retain_success(session_key=WEB_SESSION, result=WebPageFetchResult(
        requested_url=PAGE_URL, final_url=PAGE_URL, status="ok", title=PAGE_TITLE,
        content_text="Six lighthouses still stand.", outgoing_links=(),
        fetched_at="2026-11-13T00:00:00+00:00", truncated=False, error_kind=""))
    store = AiChatSessionStore()
    turn = store.start_turn(user_content=QUESTION, provider="openai", model="gpt-5.6-sol")
    stream = ChatTurnStream(store=store, notes=NoteStore(), session_key=WEB_SESSION, turn_id=turn,
                            initial_input_tokens=1, web_evidence_store=web_pages)
    references = {"reference_note_ids": [], "reference_web_ids": [page.evidence_id]}

    async def events():
        yield {"type": "content_delta", "text": f"Six still stand. [[web:{page.evidence_id}]]", **references}
        yield {"type": "done", **references, "actions": ACTIONS, "request_tokens": REQUEST}

    async def consume() -> None:
        async for _line in stream.events(events()):
            pass

    asyncio.run(consume())


def test_a_restart_keeps_the_web_pages_an_answer_cites(vault, monkeypatch: pytest.MonkeyPatch) -> None:
    _answered_citing_a_web_page()
    # After a restart the pages the AI opened are gone (they are kept only for the login).
    monkeypatch.setattr(ai_routes, "ai_chat_store", _restarted())
    monkeypatch.setattr(ai_routes, "web_evidence_store", WebEvidenceStore())
    monkeypatch.setattr(ai_routes.token_service, "get_session_key", lambda token: "a-new-login")

    shown = ai_routes.get_ai_session(response=Response(), token="auth-token").messages[1]
    monkeypatch.setattr(ai_routes, "set_clipboard", lambda client_id, records: None)
    copied = ai_routes.copy_ai_message(message_id=shown.id, token="auth-token",
                                       payload=ai_routes.AiCopyMessageRequest(client_id="client-1"))

    # In the chat, and in a note made from the answer with Copy.
    for answer in (shown.rendered_content, copied.html):
        assert "Six still stand." in answer
        assert f'href="{PAGE_URL}"' in answer
        assert PAGE_TITLE in answer


def test_a_chat_saved_before_answers_kept_their_web_pages_still_opens(vault) -> None:
    """Format 1 (before 2026-11-13) kept no web pages: its answers show without their links."""
    _answered_citing_a_web_page()
    saved = json.loads(str(_saved_row()["state_json"]))
    del saved["web_references"]
    saved["format"] = 1
    with begin_writer() as connection:
        upsert_ai_chat_row(connection, state_json=json.dumps(saved), state_encryption_nonce=None,
                           state_encryption_tag=None, updated_at=datetime.now(timezone.utc))

    store = _restarted()

    answer_id = store.snapshot()["messages"][1]["id"]
    assert store.web_references(message_id=answer_id) == ()
    # The next answer keeps its pages.
    _answered(store, "Again?", "Yes.")
    assert _restarted().web_references(message_id=store.snapshot()["messages"][3]["id"]) == ()
