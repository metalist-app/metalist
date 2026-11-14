"""Search suggestions are answered beside a change, not after it: they took the vault's write
slot, so each keystroke's suggestions queued behind the last, and the list's view behind them all.
On a slow machine a page waited a minute for its notes and the watchdog stopped it (a problem
report, 2026-11-14: suggestions waiting up to 113 s, the view 61 s)."""

from __future__ import annotations

from threading import Event, Thread

import pytest

import app.api.routes.notes as notes_routes
from app.services.bulk_operation import bulk_operation_guard

# Long enough for suggestions answered beside the change; far shorter than the change.
_ANSWER_WITHIN_SECONDS = 2.0
_CHANGE_HELD_SECONDS = 10.0


class _Index:
    def suggest_all_tag_completions(self, *, query: str) -> list[str]:
        return []

    def describe_search_suggestions(self, *, query: str, terms: list[str]) -> None:
        assert terms == [], "no suggestions, nothing to describe"


@pytest.fixture
def change_running(monkeypatch: pytest.MonkeyPatch):
    """A change holding its turn and the writes' lock, as one runs for its whole length."""
    monkeypatch.setattr(notes_routes, "search_index", _Index())
    monkeypatch.setattr(notes_routes, "is_first_search_tag_suggestion_context", lambda query: False)
    holding = Event()
    finish = Event()

    def change() -> None:
        with bulk_operation_guard.track_mutation():
            with bulk_operation_guard.lock:
                holding.set()
                finish.wait(timeout=_CHANGE_HELD_SECONDS)

    changing = Thread(target=change, daemon=True)
    changing.start()
    assert holding.wait(timeout=_CHANGE_HELD_SECONDS), "the change began"
    yield
    finish.set()
    changing.join(timeout=_CHANGE_HELD_SECONDS)


def test_suggestions_are_answered_while_a_change_runs(change_running) -> None:
    answers: list[dict] = []

    def ask() -> None:
        answers.append(notes_routes.search_suggestions(None, {"query": "work ", "windowDays": []}))

    asking = Thread(target=ask, daemon=True)
    asking.start()
    asking.join(timeout=_ANSWER_WITHIN_SECONDS)

    assert answers == [{"suggestions": [], "personalizedSuggestions": [], "reasons": {}, "labels": {}}], (
        "suggestions waited for the change to finish"
    )
