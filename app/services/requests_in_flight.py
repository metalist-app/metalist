"""The work the server does beside the requests gives way to them (2026-11-13).

Once the page has started, the server builds the [[ catalog, reads the files' text, draws PDF first
pages and drops unused link titles, each on a thread of its own. Python runs one thread at a time,
so a request made meanwhile waited its turn again each time it came back from the database: a link
clicked just after login paused for half a second or more. Now each of those jobs works in small
steps and, before each step, waits until no request is being answered.

A request counts from its arrival until its response starts: a streamed answer (an AI reply, a file
download) stops counting once it starts, so it never holds the work back for long.
"""

from __future__ import annotations

from threading import Condition, current_thread

# The threads that give way: the background jobs (each named so). A request giving way would wait
# for itself.
BACKGROUND_THREAD_PREFIX = "metalist-"


class RequestsInFlight:
    def __init__(self) -> None:
        self._changed = Condition()
        self._count = 0

    def started(self) -> None:
        with self._changed:
            self._count += 1

    def answered(self) -> None:
        with self._changed:
            assert self._count > 0, "a request answered that never started"
            self._count -= 1
            if self._count == 0:
                self._changed.notify_all()

    def count(self) -> int:
        with self._changed:
            return self._count

    def give_way(self) -> None:
        """Wait until no request is being answered. Only a background job calls this, between
        steps and holding no lock a request may need."""
        thread_name = current_thread().name
        if not thread_name.startswith(BACKGROUND_THREAD_PREFIX):
            raise RuntimeError(f"Only background work gives way to requests, not thread {thread_name!r}")
        with self._changed:
            self._changed.wait_for(lambda: self._count == 0)


requests_in_flight = RequestsInFlight()


class RequestsInFlightMiddleware:
    """Counts each HTTP request from its arrival until its response starts."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        requests_in_flight.started()
        is_answered = False

        async def send_counting_the_answer(message) -> None:
            nonlocal is_answered
            if message["type"] == "http.response.start" and not is_answered:
                is_answered = True
                requests_in_flight.answered()
            await send(message)

        try:
            await self.app(scope, receive, send_counting_the_answer)
        finally:
            # A request that ended without a response (it failed, or the browser left) ends here.
            if not is_answered:
                requests_in_flight.answered()
