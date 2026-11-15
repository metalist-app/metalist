"""The vault's one AI conversation, live in every view (multi-view editing step 5;
docs/design/multi-view-editing.md, "Step 5's cases").

Kept in memory, beside the saved conversation (ai_chat.py):
- the questions waiting their turn (case 6): one answer is written at a time, in the order sent;
- the answer being written, so Stop from any view ends it (case 7) and Clear Chat waits for it (8);
- the question the AI asks while it answers (a confirmation, which notes to tag), shown in every
  view so any can answer it (case 9).

Every view asks for this state (`GET /ai/chat/live`): often while an answer is written, at the
status check otherwise.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import Lock
from typing import AsyncIterator, Optional
from uuid import uuid4

# How often a waiting question looks whether its turn has come.
WAIT_POLL_SECONDS = 0.2


@dataclass
class _Waiting:
    id: str
    content: str
    view_id: str


class AiChatLive:
    def __init__(self) -> None:
        self._lock = Lock()
        self._waiting: list[_Waiting] = []
        self._answering: Optional[asyncio.Task] = None
        # Stop asked for the answer being written (from any view): it ends quietly, as stopped.
        self._is_stop_asked = False
        self._question: Optional[dict[str, object]] = None
        self._revision = 0

    # --- Waiting questions --------------------------------------------------------------------

    def enqueue(self, *, content: str, view_id: str) -> str:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("a waiting question has text")
        with self._lock:
            ticket = str(uuid4())
            self._waiting.append(_Waiting(id=ticket, content=content, view_id=view_id))
            self._revision += 1
            return ticket

    def _is_waiting_locked(self, ticket: str) -> bool:
        return any(waiting.id == ticket for waiting in self._waiting)

    async def wait_for_turn(self, *, ticket: str, is_answer_written: object) -> AsyncIterator[bool]:
        """Yields True once while this question waits behind another (so the view can say so),
        then returns when its turn has come; returns without its turn when it was dropped (Clear
        Chat). The caller asks took_turn(ticket) to tell which."""
        assert callable(is_answer_written), "the caller says whether an answer is being written"
        has_said_waiting = False
        while True:
            with self._lock:
                if not self._is_waiting_locked(ticket):
                    return
                is_first = self._waiting[0].id == ticket
                if is_first and self._answering is None and not is_answer_written():
                    return
            if not has_said_waiting:
                has_said_waiting = True
                yield True
            await asyncio.sleep(WAIT_POLL_SECONDS)

    def take_turn(self, *, ticket: str) -> bool:
        """The question leaves the queue to be answered now; False when it was dropped meanwhile."""
        with self._lock:
            if not self._is_waiting_locked(ticket):
                return False
            self._waiting = [waiting for waiting in self._waiting if waiting.id != ticket]
            self._answering = asyncio.current_task()
            self._is_stop_asked = False
            self._revision += 1
            return True

    def drop(self, *, ticket: str) -> None:
        """A waiting question its view stopped, or whose request ended."""
        with self._lock:
            if self._is_waiting_locked(ticket):
                self._waiting = [waiting for waiting in self._waiting if waiting.id != ticket]
                self._revision += 1

    # --- The answer being written ---------------------------------------------------------------

    def end_answer(self) -> None:
        with self._lock:
            self._answering = None
            self._is_stop_asked = False
            self._question = None
            self._revision += 1

    def was_stop_asked(self) -> bool:
        with self._lock:
            return self._is_stop_asked

    def stop(self, *, drops_waiting: bool) -> None:
        """Stop the answer being written; with drops_waiting (Clear Chat), the waiting ones too."""
        with self._lock:
            if drops_waiting and self._waiting:
                self._waiting = []
                self._revision += 1
            task = self._answering
            if task is None or task.done():
                return
            self._is_stop_asked = True
            self._revision += 1
        task.get_loop().call_soon_threadsafe(task.cancel)

    def is_answering(self) -> bool:
        with self._lock:
            return self._answering is not None

    # --- The AI's question ----------------------------------------------------------------------

    def show_question(self, event: dict[str, object]) -> None:
        with self._lock:
            self._question = dict(event)
            self._revision += 1

    def end_question(self) -> None:
        with self._lock:
            if self._question is not None:
                self._question = None
                self._revision += 1

    # --- What every view reads ------------------------------------------------------------------

    def state(self, *, view_id: str) -> dict[str, object]:
        with self._lock:
            return {
                "revision": self._revision,
                "isAnswering": self._answering is not None,
                "waiting": [
                    {"id": waiting.id, "content": waiting.content, "isOwn": waiting.view_id == view_id}
                    for waiting in self._waiting
                ],
                "question": self._question,
            }

    def reset(self) -> None:
        """The vault locked or its runtime started again: running work was cancelled with it."""
        with self._lock:
            self._waiting = []
            self._answering = None
            self._is_stop_asked = False
            self._question = None
            self._revision += 1


ai_chat_live = AiChatLive()
