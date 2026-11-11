"""The vault's AI conversation is saved in it (docs/ui/ai-chat.md, "Saved with the vault"): a
restart keeps it, only Clear Chat ends it, and in a vault with a password it is never on disk
unencrypted."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.db.ai_chat_sql import fetch_ai_chat_row
from app.db.session import begin_writer
from app.models.database import SafeSession
from app.security.encryption import clear_encryption_key, get_encryption_service, set_encryption_required, set_session_dek
from app.services.agent.cloud_privacy import HistoryDisclosure
from app.services.ai_chat import INTERRUPTED_ERROR, NO_REQUEST, AiChatSessionStore

QUESTION = "Which notes mention the lighthouse?"
ANSWER = "Two notes mention the lighthouse."
REQUEST = {"total": 900, "instructions": 500, "history": 100, "this_turn": 300}
ACTIONS = [{"action": "search", "query": "lighthouse"}]
NOTE_SEEN = "note-seen"
DEK = b"d" * 32


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
