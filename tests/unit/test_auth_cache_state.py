"""Work built ahead of the first request waits until the page has finished loading (the
maintainer, 2026-11-08): the `[[` catalog built during an unlock slowed the page's own first
requests from a few milliseconds to several hundred."""
from __future__ import annotations

import pytest

from app.services import auth_cache_state
from app.services.auth_cache_state import after_page_ready, mark_cache_ready, page_is_ready, reset_cache_state


@pytest.fixture
def ran(monkeypatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(auth_cache_state, "_ready_listeners", [])
    reset_cache_state()
    after_page_ready(lambda: calls.append("built"))
    yield calls
    reset_cache_state()


def test_loading_the_notes_starts_nothing(ran: list[str]) -> None:
    mark_cache_ready()
    assert ran == []


def test_the_page_being_ready_starts_the_work_once(ran: list[str]) -> None:
    mark_cache_ready()
    page_is_ready()
    page_is_ready()
    assert ran == ["built"]


def test_a_page_ready_before_the_notes_are_loaded_starts_nothing(ran: list[str]) -> None:
    page_is_ready()
    assert ran == []


def test_each_load_of_the_notes_starts_the_work_again(ran: list[str]) -> None:
    mark_cache_ready()
    page_is_ready()
    reset_cache_state()
    mark_cache_ready()
    page_is_ready()
    assert ran == ["built", "built"]


def test_work_dropped_when_the_notes_are_unloaded_first(ran: list[str]) -> None:
    mark_cache_ready()
    reset_cache_state()
    page_is_ready()
    assert ran == []
