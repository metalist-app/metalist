"""The work the server does beside the requests gives way to them (app/services/requests_in_flight.py):
a link clicked just after login paused while the [[ catalog was built and the files read (2026-11-13)."""

from __future__ import annotations

import asyncio
from threading import Event, Thread

import pytest

from app.services.requests_in_flight import RequestsInFlight, RequestsInFlightMiddleware, requests_in_flight

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
