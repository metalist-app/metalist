"""Session-scoped, in-memory AI chat state."""

from __future__ import annotations

import math
from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from app.services.agent.cloud_privacy import HistoryDisclosure
from app.services.ai_chat_rendering import strip_note_citations_for_history
from app.utils.time_units import MS_PER_SECOND


# What the history meter shows before any answer: no request yet.
NO_REQUEST = {"total": 0, "instructions": 0, "history": 0, "this_turn": 0}
# A turn is the user's message followed by the assistant's answer.
_MESSAGES_PER_TURN = 2
_MAX_MESSAGE_CHARACTERS = 32_000
# What the model may still see of each message (snapshot()): directly, only through the
# summary that replaced it, or nothing since a privacy change (synchronize_disclosure_boundary).
VISIBILITY_SENT = "sent"
VISIBILITY_SUMMARIZED = "summarized"
VISIBILITY_HELD_BACK = "held_back"
# How the summary of earlier turns opens the conversation the model is sent.
_SUMMARY_MESSAGE_HEADER = "EARLIER_CONVERSATION_SUMMARY"
_SUMMARY_MESSAGE_INSTRUCTION = (
    "The earlier part of this chat, summarized because the whole chat no longer fits. It is "
    "everything you know about that part: if it does not say something, you cannot tell."
)


class AiChatActivityTimer:
    """Attach retained elapsed time to a stream of activity lifecycle events."""

    def __init__(self) -> None:
        self._started: dict[str, tuple[str, float]] = {}

    def stamp(
        self,
        *,
        event: dict[str, object],
        observed_at: float,
    ) -> dict[str, object]:
        if not isinstance(event, dict):
            raise TypeError("AI activity event must be an object")
        if not isinstance(observed_at, (int, float)) or isinstance(observed_at, bool):
            raise TypeError("AI activity observation time must be numeric")
        if not math.isfinite(observed_at) or observed_at < 0:
            raise ValueError("AI activity observation time must be non-negative and finite")
        action = event["action"]
        status = event["status"]
        label = event["label"]
        supplied_duration = event["duration_ms"]
        if not isinstance(action, str) or action == "":
            raise ValueError("AI activity action must be non-empty")
        if status not in {"started", "completed"}:
            raise ValueError("AI activity status is invalid")
        if not isinstance(label, str) or label == "":
            raise ValueError("AI activity label must be non-empty")
        if (
            not isinstance(supplied_duration, (int, float))
            or isinstance(supplied_duration, bool)
            or not math.isfinite(supplied_duration)
            or supplied_duration < 0
        ):
            raise ValueError("AI activity duration must be non-negative and finite")
        measured_duration = 0.0
        if status == "started":
            should_start = action not in self._started
            if action in self._started:
                prior_label, prior_started_at = self._started[action]
                should_start = prior_label != label
                if not should_start:
                    measured_duration = (observed_at - prior_started_at) * MS_PER_SECOND
            if should_start:
                self._started[action] = (
                    label,
                    observed_at - (float(supplied_duration) / MS_PER_SECOND),
                )
                measured_duration = float(supplied_duration)
        else:
            if action in self._started:
                _prior_label, prior_started_at = self._started.pop(action)
                measured_duration = (observed_at - prior_started_at) * MS_PER_SECOND
        duration_ms = max(float(supplied_duration), measured_duration)
        return {**event, "duration_ms": duration_ms}


# Enough of each earlier question for the model to tell answers apart.
_ACTION_LOG_QUESTION_CHARACTERS = 200


_FAILED_TURN_HISTORY_PREFIX = (
    "(No answer: this request failed. The user was shown the explanation below. "
    "If they ask to try again, redo this request.)"
)


def _failed_turn_history_content(error: str) -> str:
    """A failed turn as the model sees it later: plainly not an answer, with the
    explanation the user saw (note citations removed, as for answers)."""
    if not isinstance(error, str) or error.strip() == "":
        raise ValueError("A failed AI turn must keep its explanation")
    return strip_note_citations_for_history(f"{_FAILED_TURN_HISTORY_PREFIX}\n{error}")


def summary_message(content: str) -> dict[str, str]:
    """The summary of earlier turns as the model is sent it, before the turns after it."""
    if not isinstance(content, str) or content.strip() == "":
        raise ValueError("A summary must have text")
    return {"role": "user", "content": f"{_SUMMARY_MESSAGE_HEADER}\n{_SUMMARY_MESSAGE_INSTRUCTION}\n\n{content}"}


def _turn_as_sent(messages: list[dict[str, str]], index: int) -> list[dict[str, str]]:
    """The turn starting at messages[index] as the model is sent it: the question, then
    the answer (note citations removed), the failure it explained, or nothing while it is
    being answered."""
    assert len(messages) % _MESSAGES_PER_TURN == 0, "AI chat history must contain complete turn pairs"
    user_message = messages[index]
    assistant_message = messages[index + 1]
    assert user_message["role"] == "user"
    assert user_message["status"] == "complete"
    assert assistant_message["role"] == "assistant"
    sent = [{"role": "user", "content": user_message["content"]}]
    if assistant_message["status"] == "error":
        # The agent keeps failed requests in view, so the user can
        # say "try that again" or ask why it failed.
        sent.append({"role": "assistant", "content": _failed_turn_history_content(assistant_message["error"])})
        return sent
    if assistant_message["status"] == "streaming":
        assert index == len(messages) - _MESSAGES_PER_TURN, "only the current turn may be streaming"
        return sent
    assert assistant_message["status"] == "complete"
    assistant_content = assistant_message["content"]
    assert isinstance(assistant_content, str)
    sent.append({"role": "assistant", "content": strip_note_citations_for_history(assistant_content)})
    return sent


def _turn_actions(session: "_ChatSession", assistant_message: dict[str, str]) -> list[dict[str, object]]:
    """The agent's record of what an answer did; a failed request has none."""
    if assistant_message["status"] != "complete":
        return []
    if assistant_message["id"] not in session.action_logs:
        raise RuntimeError("Completed AI answer has no action log")
    return [dict(action) for action in session.action_logs[assistant_message["id"]]]


@dataclass(frozen=True)
class ChatSummary:
    """A summary that replaced the earlier turns of a chat (agent/chat_compaction.py)."""
    id: str
    content: str
    # It replaced messages[:position] (those the model still saw directly).
    position: int


@dataclass(frozen=True)
class TurnToSummarize:
    """One earlier turn as the model sees it, with the agent's record of what it did."""
    messages: list[dict[str, str]]
    actions: list[dict[str, object]]


@dataclass(frozen=True)
class SummarySource:
    """What a new summary replaces: the summary the model sees now ('' for none) and the
    turns it still sees directly, oldest first, without the turn being answered."""
    summary: str
    turns: list[TurnToSummarize]
    # Where those turns start (history_start), and the chat they belong to, to check
    # nothing moved and the chat was not cleared meanwhile.
    history_start: int
    session_id: str


@dataclass
class _ChatSession:
    """One authenticated session's conversation."""
    # A new one after Clear Chat, so work begun before it cannot land in the new chat.
    id: str
    messages: list[dict[str, str]]
    # Progress shown under each message, by message id.
    activities: dict[str, list[dict[str, object]]]
    # The agent's own record of what each answer did (action_log.py), by
    # assistant message id. Only the model sees it, on later turns.
    action_logs: dict[str, list[dict[str, object]]]
    # The first message the model still sees directly (after a disclosure boundary or
    # a summary).
    history_start: int
    # The privacy rules at the last turn; None until the first disclosure boundary is set.
    disclosure_policy_key: str | None
    # The notes the AI could see at the last turn: if one becomes private, the history resets.
    permitted_note_ids: frozenset[str]
    # Every summary made, oldest first; the screen keeps them all.
    summaries: list[ChatSummary]
    # The summary the model sees, before messages[history_start:]; None when there is
    # none, or since a privacy change dropped it.
    active_summary: ChatSummary | None
    # The model sees nothing of messages[:held_back_until] since the last privacy change.
    held_back_until: int
    # A summary is being made on request (begin_summary); no turn starts meanwhile.
    is_summarizing: bool
    # The make-up of the latest answer's last request to the model (request_tokens.py):
    # all zeros until an answer completes.
    last_request: dict[str, int]


def _new_chat_session() -> _ChatSession:
    return _ChatSession(id=str(uuid4()), messages=[], activities={}, action_logs={}, history_start=0,
                        disclosure_policy_key=None, permitted_note_ids=frozenset(),
                        summaries=[], active_summary=None, held_back_until=0, is_summarizing=False,
                        last_request=dict(NO_REQUEST))


def _visibility(index: int, *, held_back_until: int, history_start: int) -> str:
    """What the model sees of the message (or summary) at a position in the chat."""
    if index < held_back_until:
        return VISIBILITY_HELD_BACK
    if index < history_start:
        return VISIBILITY_SUMMARIZED
    return VISIBILITY_SENT


class AiChatSessionStore:
    """Keep AI conversations isolated by opaque authenticated-session key."""

    def __init__(self) -> None:
        self._sessions: dict[str, _ChatSession] = {}
        self._lock = Lock()

    def reset(self) -> None:
        with self._lock:
            self._sessions.clear()

    def clear_session(self, *, session_key: str) -> None:
        self._validate_session_key(session_key)
        with self._lock:
            # A session that never chatted has nothing to clear.
            if session_key in self._sessions:
                del self._sessions[session_key]

    def _session_locked(self, session_key: str) -> _ChatSession:
        """The session's conversation, started empty on its first use."""
        if session_key not in self._sessions:
            self._sessions[session_key] = _new_chat_session()
        return self._sessions[session_key]

    def snapshot(self, *, session_key: str) -> dict[str, list[dict[str, object]]]:
        """The chat as shown: every message and every summary, each with what the model
        still sees of it (a summary sits after the last message it replaced)."""
        self._validate_session_key(session_key)
        with self._lock:
            if session_key not in self._sessions:
                return {"messages": [], "summaries": []}
            session = self._sessions[session_key]
            boundaries = {"held_back_until": session.held_back_until, "history_start": session.history_start}
            summaries: list[dict[str, object]] = []
            for summary in session.summaries:
                visibility = VISIBILITY_SUMMARIZED
                if summary is session.active_summary:
                    visibility = VISIBILITY_SENT
                elif summary.position <= session.held_back_until:
                    visibility = VISIBILITY_HELD_BACK
                summaries.append({
                    "id": summary.id,
                    "content": summary.content,
                    "after_message_id": session.messages[summary.position - 1]["id"],
                    "visibility": visibility,
                })
            return {
                "messages": [
                    {
                        **message,
                        "visibility": _visibility(index, **boundaries),
                        "activities": [
                            dict(activity)
                            for activity in session.activities[message["id"]]
                        ],
                    }
                    for index, message in enumerate(session.messages)
                ],
                "summaries": summaries,
            }

    def start_turn(
        self,
        *,
        session_key: str,
        user_content: str,
        provider: str,
        model: str,
    ) -> str:
        self._validate_session_key(session_key)
        self._validate_message_text(user_content, label="user_content")
        self._validate_message_text(provider, label="provider")
        self._validate_message_text(model, label="model")
        with self._lock:
            session = self._session_locked(session_key)
            messages = session.messages
            session_activities = session.activities
            if any(message["status"] == "streaming" for message in messages):
                raise RuntimeError("AI chat session already streaming a turn")
            if session.is_summarizing:
                raise RuntimeError("AI chat session is summarizing its earlier turns")
            # Switching provider keeps the conversation: one privacy policy covers every
            # provider (synchronize_disclosure_boundary resets it when what the AI may see
            # changes; the maintainer, 2026-10-24). Nothing is trimmed: summaries keep the
            # conversation within the model's context (agent/chat_compaction.py).
            user_message_id = str(uuid4())
            assistant_message_id = str(uuid4())
            messages.extend(
                [
                    {
                        "id": user_message_id,
                        "role": "user",
                        "content": user_content,
                        "thinking": "",
                        "status": "complete",
                        "error": "",
                        "provider": provider,
                        "model": model,
                    },
                    {
                        "id": assistant_message_id,
                        "role": "assistant",
                        "content": "",
                        "thinking": "",
                        "status": "streaming",
                        "error": "",
                        "provider": provider,
                        "model": model,
                    },
                ]
            )
            session_activities[user_message_id] = []
            session_activities[assistant_message_id] = []
            return assistant_message_id

    def append_activity(
        self,
        *,
        session_key: str,
        turn_id: str,
        action: str,
        status: str,
        label: str,
        approx_input_tokens: int,
        output_tokens_received: int,
        duration_ms: float,
    ) -> None:
        self._validate_session_key(session_key)
        self._validate_message_text(turn_id, label="turn_id")
        self._validate_message_text(action, label="action")
        if status not in {"started", "completed"}:
            raise ValueError(f"Unsupported AI activity status: {status}")
        self._validate_message_text(label, label="label")
        if (
            not isinstance(approx_input_tokens, int)
            or isinstance(approx_input_tokens, bool)
            or approx_input_tokens < 1
        ):
            raise ValueError("AI activity approximate input tokens must be positive")
        if (
            not isinstance(output_tokens_received, int)
            or isinstance(output_tokens_received, bool)
            or output_tokens_received < 0
        ):
            raise ValueError("AI activity output tokens must be non-negative")
        if (
            not isinstance(duration_ms, (int, float))
            or isinstance(duration_ms, bool)
            or not math.isfinite(duration_ms)
            or duration_ms < 0
        ):
            raise ValueError("AI activity duration must be non-negative and finite")
        with self._lock:
            self._require_streaming_turn(session_key=session_key, turn_id=turn_id)
            session_activities = self._sessions[session_key].activities
            if turn_id not in session_activities:
                raise RuntimeError("AI activity list missing for streaming turn")
            session_activities[turn_id].append(
                {
                    "action": action,
                    "status": status,
                    "label": label,
                    "approx_input_tokens": approx_input_tokens,
                    "output_tokens_received": output_tokens_received,
                    "duration_ms": float(duration_ms),
                }
            )

    def append_delta(
        self,
        *,
        session_key: str,
        turn_id: str,
        delta_kind: str,
        text: str,
    ) -> None:
        self._validate_session_key(session_key)
        self._validate_message_text(turn_id, label="turn_id")
        if delta_kind not in {"thinking", "content"}:
            raise ValueError(f"Unsupported AI delta kind: {delta_kind}")
        if not isinstance(text, str) or text == "":
            raise ValueError("AI delta text must be a non-empty string")
        with self._lock:
            message = self._require_streaming_turn(
                session_key=session_key,
                turn_id=turn_id,
            )
            updated_text = message[delta_kind] + text
            if len(updated_text) > _MAX_MESSAGE_CHARACTERS:
                raise RuntimeError(f"AI {delta_kind} exceeded {_MAX_MESSAGE_CHARACTERS} characters")
            message[delta_kind] = updated_text

    def complete_turn(
        self,
        *,
        session_key: str,
        turn_id: str,
        final_content: str,
        actions: list[dict[str, object]],
        request_tokens: dict[str, int],
    ) -> None:
        self._validate_session_key(session_key)
        self._validate_message_text(turn_id, label="turn_id")
        self._validate_message_text(final_content, label="final_content")
        if not isinstance(actions, list) or not all(isinstance(action, dict) for action in actions):
            raise TypeError("actions must be a list of action log entries")
        if not isinstance(request_tokens, dict) or set(request_tokens) != set(NO_REQUEST):
            raise ValueError(f"request_tokens must have {sorted(NO_REQUEST)}")
        with self._lock:
            message = self._require_streaming_turn(
                session_key=session_key,
                turn_id=turn_id,
            )
            message["content"] = final_content
            message["status"] = "complete"
            self._sessions[session_key].action_logs[turn_id] = [dict(action) for action in actions]
            self._sessions[session_key].last_request = dict(request_tokens)

    def last_request(self, *, session_key: str) -> dict[str, int]:
        """The make-up of the latest answer's last request; NO_REQUEST before any answer."""
        self._validate_session_key(session_key)
        with self._lock:
            if session_key not in self._sessions:
                return dict(NO_REQUEST)
            return dict(self._sessions[session_key].last_request)

    def is_streaming(self, *, session_key: str, turn_id: str) -> bool:
        with self._lock:
            if session_key not in self._sessions:
                return False
            return any(message['id'] == turn_id and message['status'] == 'streaming'
                       for message in self._sessions[session_key].messages)

    def fail_turn(self, *, session_key: str, turn_id: str, error: str) -> None:
        self._validate_session_key(session_key)
        self._validate_message_text(turn_id, label="turn_id")
        self._validate_message_text(error, label="error")
        with self._lock:
            message = self._require_streaming_turn(
                session_key=session_key,
                turn_id=turn_id,
            )
            message["status"] = "error"
            message["error"] = error

    def synchronize_disclosure_boundary(self, *, session_key: str, disclosure: HistoryDisclosure) -> bool:
        """Retain the display transcript, but never replay a previous disclosure context:
        the history resets when the privacy rules change or a note the AI could see has
        become private. A new note, a deleted one or one made visible changes nothing the
        AI saw (the maintainer, 2026-10-30). True when it reset."""
        self._validate_session_key(session_key)
        if not isinstance(disclosure, HistoryDisclosure) or disclosure.policy_key == "":
            raise ValueError("A disclosure boundary is required")
        with self._lock:
            session = self._session_locked(session_key)
            is_reset = session.disclosure_policy_key != disclosure.policy_key
            if not session.permitted_note_ids.isdisjoint(disclosure.hidden_note_ids):
                # A note the AI could see at the last turn is private now.
                is_reset = True
            if is_reset:
                # The summary drew on the turns it replaced, so it goes with them.
                session.history_start = len(session.messages)
                session.held_back_until = len(session.messages)
                session.active_summary = None
                session.disclosure_policy_key = disclosure.policy_key
            session.permitted_note_ids = disclosure.permitted_note_ids
            return is_reset

    def provider_messages(self, *, session_key: str) -> list[dict[str, str]]:
        self._validate_session_key(session_key)
        with self._lock:
            if session_key not in self._sessions:
                return []
            session = self._sessions[session_key]
            messages = session.messages
            assert len(messages) % _MESSAGES_PER_TURN == 0, "AI chat history must contain complete turn pairs"
            provider_messages: list[dict[str, str]] = []
            if session.active_summary is not None:
                assert session.active_summary.position == session.history_start, "the summary ends where the turns start"
                provider_messages.append(summary_message(session.active_summary.content))
            for index in range(session.history_start, len(messages), _MESSAGES_PER_TURN):
                provider_messages.extend(_turn_as_sent(messages, index))
            return provider_messages

    def summary_source(self, *, session_key: str) -> SummarySource:
        """The summary and the turns the model sees directly, for making a new summary.
        A turn being answered is left out: it is never summarized."""
        self._validate_session_key(session_key)
        with self._lock:
            session = self._session_locked(session_key)
            messages = session.messages
            end = len(messages)
            if end > 0 and messages[-1]["status"] == "streaming":
                end -= _MESSAGES_PER_TURN
            summary = ""
            if session.active_summary is not None:
                summary = session.active_summary.content
            turns = [
                TurnToSummarize(messages=_turn_as_sent(messages, index),
                                actions=_turn_actions(session, messages[index + 1]))
                for index in range(session.history_start, end, _MESSAGES_PER_TURN)
            ]
            return SummarySource(summary=summary, turns=turns, history_start=session.history_start,
                                 session_id=session.id)

    def apply_summary(
        self, *, session_key: str, content: str, turn_count: int, history_start: int, session_id: str,
    ) -> bool:
        """Replace the summary and the first turn_count turns the model sees with a new
        summary. False, changing nothing, when the chat was cleared or its history moved
        since summary_source() (a privacy change held it all back): that summary must not
        be sent."""
        self._validate_session_key(session_key)
        self._validate_message_text(content, label="summary")
        if not isinstance(turn_count, int) or isinstance(turn_count, bool) or turn_count < 1:
            raise ValueError("A summary replaces at least one turn")
        with self._lock:
            if session_key not in self._sessions:
                return False
            session = self._sessions[session_key]
            if session.id != session_id or session.history_start != history_start:
                return False
            position = history_start + turn_count * _MESSAGES_PER_TURN
            if position > len(session.messages) or session.messages[position - 1]["status"] == "streaming":
                raise RuntimeError("A summary cannot replace the turn being answered")
            summary = ChatSummary(id=str(uuid4()), content=content, position=position)
            session.summaries.append(summary)
            session.active_summary = summary
            session.history_start = position
            return True

    def begin_summary(self, *, session_key: str) -> bool:
        """Start making a summary on request; False when a turn is being answered or
        a summary is already being made."""
        self._validate_session_key(session_key)
        with self._lock:
            session = self._session_locked(session_key)
            if session.is_summarizing or any(message["status"] == "streaming" for message in session.messages):
                return False
            session.is_summarizing = True
            return True

    def is_summarizing(self, *, session_key: str) -> bool:
        self._validate_session_key(session_key)
        with self._lock:
            return session_key in self._sessions and self._sessions[session_key].is_summarizing

    def end_summary(self, *, session_key: str) -> None:
        self._validate_session_key(session_key)
        with self._lock:
            # Clear Chat may have removed the session meanwhile.
            if session_key not in self._sessions:
                return
            session = self._sessions[session_key]
            if not session.is_summarizing:
                raise RuntimeError("No summary is being made")
            session.is_summarizing = False

    def summary_content(self, *, session_key: str, summary_id: str) -> str | None:
        """A summary's text for Copy Response; None when the chat has no such summary."""
        self._validate_session_key(session_key)
        with self._lock:
            if session_key not in self._sessions:
                return None
            for summary in self._sessions[session_key].summaries:
                if summary.id == summary_id:
                    return summary.content
            return None

    def earlier_actions(self, *, session_key: str) -> list[dict[str, object]]:
        """What the agent did for each completed answer the model still sees, in the
        order of provider_messages(): {answer, question, actions}. Failed requests
        appear in provider_messages() with their explanation but have no record here."""
        self._validate_session_key(session_key)
        with self._lock:
            if session_key not in self._sessions:
                return []
            session = self._sessions[session_key]
            messages = session.messages
            session_action_logs = session.action_logs
            earlier: list[dict[str, object]] = []
            for index in range(session.history_start, len(messages), _MESSAGES_PER_TURN):
                user_message, assistant_message = messages[index], messages[index + 1]
                if assistant_message["status"] != "complete":
                    continue
                if assistant_message["id"] not in session_action_logs:
                    raise RuntimeError("Completed AI answer has no action log")
                earlier.append({
                    "answer": len(earlier) + 1,
                    "question": user_message["content"][:_ACTION_LOG_QUESTION_CHARACTERS],
                    "actions": [dict(action) for action in session_action_logs[assistant_message["id"]]],
                })
            return earlier

    def _require_streaming_turn(
        self,
        *,
        session_key: str,
        turn_id: str,
    ) -> dict[str, str]:
        if session_key not in self._sessions:
            raise RuntimeError("AI chat session missing")
        for message in self._sessions[session_key].messages:
            if message["id"] != turn_id:
                continue
            if message["role"] != "assistant":
                raise RuntimeError("AI turn id does not identify an assistant message")
            if message["status"] != "streaming":
                raise RuntimeError("AI turn is not streaming")
            return message
        raise RuntimeError("AI streaming turn missing")

    @staticmethod
    def _validate_session_key(session_key: str) -> None:
        if not isinstance(session_key, str) or session_key == "":
            raise ValueError("session_key must be a non-empty string")

    @staticmethod
    def _validate_message_text(value: str, *, label: str) -> None:
        if not isinstance(label, str) or label == "":
            raise ValueError("label must be a non-empty string")
        if not isinstance(value, str) or value.strip() == "":
            raise ValueError(f"{label} must be a non-empty string")
        if len(value) > _MAX_MESSAGE_CHARACTERS:
            raise ValueError(f"{label} exceeds {_MAX_MESSAGE_CHARACTERS} characters")


ai_chat_store = AiChatSessionStore()
