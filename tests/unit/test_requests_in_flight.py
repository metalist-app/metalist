"""The work the server does beside the requests gives way to them (app/services/requests_in_flight.py):
a link clicked just after login paused while the [[ catalog was built and the files read (2026-11-13)."""

from __future__ import annotations

import asyncio
from threading import Event, Thread
from types import SimpleNamespace

import pytest

from app.services.agent.scope import read_notes_off_request_loop
from app.services.requests_in_flight import (
    RequestsInFlight,
    RequestsInFlightMiddleware,
    interpreter_switch_seconds,
    requests_in_flight,
)

_WAIT_SECONDS = 2.0
# Long enough for a thread that would not wait to have finished.
_SETTLE_SECONDS = 0.2


def _give_way_on_a_background_thread(counter: RequestsInFlight) -> tuple[Thread, Event]:
    went_on = Event()

    def background_step() -> None:
        counter.give_way()
        went_on.set()

    thread = Thread(target=background_step, name="metalist-test-work", daemon=True)
    thread.start()
    return thread, went_on


def test_background_work_waits_while_a_request_is_answered() -> None:
    counter = RequestsInFlight()
    counter.started()

    thread, went_on = _give_way_on_a_background_thread(counter)

    assert not went_on.wait(_SETTLE_SECONDS), "the work went on while a request was answered"
    counter.answered()
    assert went_on.wait(_WAIT_SECONDS)
    thread.join()


def test_with_no_request_the_work_goes_straight_on() -> None:
    counter = RequestsInFlight()
    thread, went_on = _give_way_on_a_background_thread(counter)
    assert went_on.wait(_WAIT_SECONDS)
    thread.join()


def test_a_request_never_gives_way_to_itself() -> None:
    with pytest.raises(RuntimeError, match="Only background work"):
        RequestsInFlight().give_way()


def _counted_while(app, *, path: str) -> list[int]:
    """The requests counted at each message the app sends, and once it is done."""
    counted: list[int] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message) -> None:
        counted.append(requests_in_flight.count())

    asyncio.run(RequestsInFlightMiddleware(app)({"type": "http", "path": path}, receive, send))
    counted.append(requests_in_flight.count())
    return counted


def test_a_request_counts_until_its_response_starts() -> None:
    async def app(scope, receive, send) -> None:
        assert requests_in_flight.count() == 1, "counted while the route runs"
        await send({"type": "http.response.start", "status": 200, "headers": []})
        # A streamed answer (an AI reply, a file download) goes on without holding the work back.
        await send({"type": "http.response.body", "body": b"part", "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    assert _counted_while(app, path="/api2/ai/chat") == [0, 0, 0, 0]


def test_a_request_that_fails_before_answering_stops_counting() -> None:
    async def app(scope, receive, send) -> None:
        raise RuntimeError("the route failed")

    with pytest.raises(RuntimeError, match="the route failed"):
        _counted_while(app, path="/api2/notes/view")
    assert requests_in_flight.count() == 0


# Found 2026-11-15: the AI read a 100,000-note vault after its streamed answer had started, so its
# request no longer counted and the [[ catalog job computed beside it at full speed (160 s for the
# answer on Windows against 23 s with the job left out).
def test_background_work_waits_while_the_ai_reads_the_notes() -> None:
    is_reading = Event()
    may_finish = Event()

    def read_notes() -> str:
        is_reading.set()
        assert may_finish.wait(_WAIT_SECONDS)
        return "read"

    # Only a stopped run touches the snapshot: this one finishes.
    snapshot = SimpleNamespace(text_extraction=SimpleNamespace(stop=lambda: None))

    async def scenario() -> tuple[bool, str, bool]:
        reading = asyncio.ensure_future(read_notes_off_request_loop(snapshot=snapshot, read_notes=read_notes))
        assert await asyncio.to_thread(is_reading.wait, _WAIT_SECONDS)
        thread, went_on = _give_way_on_a_background_thread(requests_in_flight)
        went_on_beside_the_reading = await asyncio.to_thread(went_on.wait, _SETTLE_SECONDS)
        may_finish.set()
        notes_read = await reading
        went_on_afterwards = await asyncio.to_thread(went_on.wait, _WAIT_SECONDS)
        thread.join()
        return went_on_beside_the_reading, notes_read, went_on_afterwards

    went_on_beside_the_reading, notes_read, went_on_afterwards = asyncio.run(scenario())

    assert not went_on_beside_the_reading, "the work went on while the AI read the notes"
    assert notes_read == "read"
    assert went_on_afterwards
    assert requests_in_flight.count() == 0


def test_a_reading_that_fails_stops_holding_the_work_back() -> None:
    def read_notes() -> str:
        raise RuntimeError("the reading failed")

    stopped: list[bool] = []
    snapshot = SimpleNamespace(text_extraction=SimpleNamespace(stop=lambda: stopped.append(True)))

    with pytest.raises(RuntimeError, match="the reading failed"):
        asyncio.run(read_notes_off_request_loop(snapshot=snapshot, read_notes=read_notes))

    assert requests_in_flight.count() == 0
    assert stopped == [True]


# Found 2026-11-15: Windows counts the wait for Python's interpreter lock in whole milliseconds, so
# the half millisecond set on 2026-11-13 became no wait at all there. Every thread waiting for
# its turn spun instead of sleeping, and the server spent more processor time switching threads
# than working (228 s against 186 s, about 41,000 switches a second, during one AI answer).
def test_windows_waits_a_whole_millisecond_for_the_interpreter_lock() -> None:
    shortest_wait_windows_can_make = 0.001
    assert interpreter_switch_seconds(platform="win32") >= shortest_wait_windows_can_make


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_systems_hand_the_interpreter_lock_on_within_half_a_millisecond(platform: str) -> None:
    # What the 2026-11-13 measurement found good enough (test_requests_beside_background_work.py).
    assert interpreter_switch_seconds(platform=platform) <= 0.0005
