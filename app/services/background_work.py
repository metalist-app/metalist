"""Work the server does beside the requests (reading PDF text, an import), listed with how far
it got, so the page can show it as it goes (the maintainer, 2026-11-02: what is computed in
the background is shown, not hidden). GET /background-work answers the list."""

from __future__ import annotations

import time
from contextlib import contextmanager
from threading import Condition
from typing import Dict, Iterator, List, TypedDict


# The work there is.
IMPORT_KEY = "import"
READING_PDF_TEXT_KEY = "file-texts"


class _RunningWork(TypedDict):
    """One piece of work as the page lists it: done of total parts."""

    key: str
    label: str
    done: int
    total: int


class WorkProgress:
    """One piece of work's count, advanced as each part of it is done."""

    def __init__(self, owner: "BackgroundWork", key: str) -> None:
        self._owner = owner
        self._key = key

    def advance(self) -> None:
        self._owner._advance(self._key)

    def set_total(self, total: int) -> None:
        """The number of parts, once known (0 until then: the page shows it running)."""
        self._owner._set_total(self._key, total)


class BackgroundWork:
    def __init__(self) -> None:
        self._lock = Condition()
        self._running: Dict[str, _RunningWork] = {}
        self._started_at: Dict[str, float] = {}

    @contextmanager
    def track(self, key: str, label: str, *, total: int) -> Iterator[WorkProgress]:
        """List the work while the block runs (done, failed or not), total parts of it."""
        if not isinstance(total, int) or total < 0:
            raise ValueError("total must be a non-negative int")
        with self._lock:
            assert key not in self._running, f"{key} runs once at a time"
            self._running[key] = {"key": key, "label": label, "done": 0, "total": total}
            self._started_at[key] = time.monotonic()
        try:
            yield WorkProgress(self, key)
        finally:
            with self._lock:
                del self._running[key]
                del self._started_at[key]
                self._lock.notify_all()

    def _advance(self, key: str) -> None:
        with self._lock:
            entry = self._running[key]
            assert entry["done"] < entry["total"], f"{key} is past its total"
            entry["done"] = entry["done"] + 1

    def _set_total(self, key: str, total: int) -> None:
        if not isinstance(total, int) or total < 0:
            raise ValueError("total must be a non-negative int")
        with self._lock:
            entry = self._running[key]
            assert entry["done"] <= total, f"{key} is past the new total"
            entry["total"] = total

    def wait_until_finished(self, key: str) -> None:
        """Return once no work under key runs (at once when none does)."""
        with self._lock:
            self._lock.wait_for(lambda: key not in self._running)

    def snapshot(self) -> List[Dict[str, object]]:
        """Each piece of work with how long it has run (whole seconds), for the page's elapsed
        time and its estimate of the time left (the maintainer, 2026-11-02)."""
        now = time.monotonic()
        with self._lock:
            return [
                {**entry, "elapsedSeconds": int(now - self._started_at[entry["key"]])}
                for entry in self._running.values()
            ]


background_work = BackgroundWork()
