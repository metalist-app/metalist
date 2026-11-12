"""What the server remembers of recent requests, in memory only, for problem reports
(docs/ready-to-build/error-reports.md, sections 2 and 6a).

- Every answered request, for 10 minutes (at most 2,000): its route as the app declares it,
  status, duration, how long it waited for its turn to change the vault, and for a failure
  the error's type and code line. A report names its requests by id and gets these back.
- Every slow request (1 s or more), for 15 minutes (at most 200), with how busy the computer
  and MetaList were at that moment: numbers only, never a program's name (decided
  2026-11-12).
- When a report is made, one more such reading of how busy they are now (snapshot).

Nothing here is written to disk; the safe log writes its own line for a slow request.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
import threading
import time

import psutil


ANSWERED_WINDOW_SECONDS = 600.0
ANSWERED_MAX_RECORDS = 2000
SLOW_WINDOW_SECONDS = 900.0
SLOW_MAX_RECORDS = 200
# The safe log's threshold for a slow static load, now for every request (section 6a).
SLOW_REQUEST_MS = 1000.0
PERCENT_OF_ALL = 100.0
# A report's own reading of how busy the computer is: long enough for a CPU percentage that
# means something, short enough that saving the report does not feel stuck (section 6a).
SNAPSHOT_SECONDS = 0.3
# macOS updates the whole computer's CPU counters in bursts, frozen for up to about 0.95 s
# (measured 2026-11-12): a snapshot whose window saw them frozen waits, checking this often,
# until they move, so it never reads 0% for a computer that was busy. Past the limit the
# counters are broken, not slow.
CPU_COUNTER_POLL_SECONDS = 0.02
CPU_COUNTER_WAIT_LIMIT_SECONDS = 2.0
NO_ERROR = ""


@dataclass
class RequestWait:
    """How long one request waited for its turn to change the vault; written by
    app/api/transactions.py while the request runs, read when it is answered."""

    waited_seconds: float


# The request being answered; None outside one (a route called directly by a test).
_CURRENT_WAIT: ContextVar[RequestWait | None] = ContextVar("current_request_wait", default=None)


def begin_request_wait() -> RequestWait:
    wait = RequestWait(waited_seconds=0.0)
    _CURRENT_WAIT.set(wait)
    return wait


def add_wait(seconds: float) -> None:
    """Adds a wait for the mutation slot or the bulk lock to the request being answered.
    A route run outside an HTTP request (a test calling it directly) has none to add it to."""
    if seconds < 0.0:
        raise ValueError(f"a wait cannot be negative: {seconds}")
    wait = _CURRENT_WAIT.get()
    if wait is None:
        return
    wait.waited_seconds += seconds


@dataclass(frozen=True)
class AnsweredRequest:
    request_id: str
    method: str
    route: str
    status: int
    duration_ms: float
    waited_ms: float
    error_type: str
    code_location: str
    answered_at: float


@dataclass(frozen=True)
class BusyNumbers:
    """How busy the computer and MetaList were: percentages of the whole computer."""

    machine_cpu_percent: float
    machine_available_bytes: int
    swap_used_bytes: int
    metalist_cpu_percent: float
    metalist_memory_bytes: int


@dataclass(frozen=True)
class SlowRequest:
    request_id: str
    method: str
    route: str
    status: int
    duration_ms: float
    waited_ms: float
    busy: BusyNumbers
    answered_at: float


class _BusyReader:
    """psutil's CPU percentages are measured since the previous reading, so the first reading
    of each is made at start-up (prime) and every later one covers the time since the last."""

    def __init__(self) -> None:
        self._process: psutil.Process | None = None
        self._lock = threading.Lock()

    def prime(self) -> None:
        with self._lock:
            self._process = psutil.Process()
            psutil.cpu_percent(interval=None)
            self._process.cpu_percent(interval=None)

    def read(self) -> BusyNumbers:
        with self._lock:
            if self._process is None:
                raise RuntimeError("busy numbers read before prime_busy_numbers ran at start-up")
            cpu_count = _cpu_count()
            memory = psutil.virtual_memory()
            # A process's percentage counts each core as 100; as a share of the whole computer
            # it is divided by the cores, so it compares with the computer's own.
            metalist_cpu = self._process.cpu_percent(interval=None) / cpu_count
            numbers = BusyNumbers(
                machine_cpu_percent=psutil.cpu_percent(interval=None),
                machine_available_bytes=memory.available,
                swap_used_bytes=psutil.swap_memory().used,
                metalist_cpu_percent=min(metalist_cpu, PERCENT_OF_ALL),
                metalist_memory_bytes=self._process.memory_info().rss,
            )
        return _checked(numbers)

    def snapshot(self) -> BusyNumbers:
        """How busy the computer and MetaList are now, measured over SNAPSHOT_SECONDS: for every
        problem report, so one that says MetaList feels slow says what the computer was doing.
        Its own baselines (this thread's for the computer, a fresh process handle for MetaList),
        and no lock, so a slow request's reading is neither moved nor kept waiting."""
        process = psutil.Process()
        cpu_count = _cpu_count()
        psutil.cpu_percent(interval=None)
        process.cpu_percent(interval=None)
        started = sum(psutil.cpu_times())
        time.sleep(SNAPSHOT_SECONDS)
        _wait_for_cpu_counters_to_move(since=started)
        machine_cpu = psutil.cpu_percent(interval=None)
        metalist_cpu = process.cpu_percent(interval=None) / cpu_count
        return _checked(BusyNumbers(
            machine_cpu_percent=machine_cpu,
            machine_available_bytes=psutil.virtual_memory().available,
            swap_used_bytes=psutil.swap_memory().used,
            metalist_cpu_percent=min(metalist_cpu, PERCENT_OF_ALL),
            metalist_memory_bytes=process.memory_info().rss,
        ))


def _wait_for_cpu_counters_to_move(*, since: float) -> None:
    """Returns once the computer's CPU counters total more than `since`."""
    deadline = time.monotonic() + CPU_COUNTER_WAIT_LIMIT_SECONDS
    while sum(psutil.cpu_times()) == since:
        if time.monotonic() > deadline:
            raise RuntimeError(f"the computer's CPU counters did not move in {CPU_COUNTER_WAIT_LIMIT_SECONDS} s")
        time.sleep(CPU_COUNTER_POLL_SECONDS)


def _cpu_count() -> int:
    cpu_count = psutil.cpu_count(logical=True)
    if cpu_count is None or cpu_count < 1:
        raise RuntimeError(f"psutil reported no CPUs: {cpu_count}")
    return cpu_count


def _checked(numbers: BusyNumbers) -> BusyNumbers:
    if not 0.0 <= numbers.machine_cpu_percent <= PERCENT_OF_ALL:
        raise RuntimeError(f"computer CPU outside 0-100%: {numbers.machine_cpu_percent}")
    return numbers


class RequestHistory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._answered: deque[AnsweredRequest] = deque(maxlen=ANSWERED_MAX_RECORDS)
        self._slow: deque[SlowRequest] = deque(maxlen=SLOW_MAX_RECORDS)

    def record_answered(self, record: AnsweredRequest) -> None:
        with self._lock:
            self._answered.append(record)
            _drop_older(self._answered, now=record.answered_at, window_seconds=ANSWERED_WINDOW_SECONDS)

    def record_slow(self, record: SlowRequest) -> None:
        with self._lock:
            self._slow.append(record)
            _drop_older(self._slow, now=record.answered_at, window_seconds=SLOW_WINDOW_SECONDS)

    def answered_by_id(self, request_ids: Iterable[str], *, now: float) -> Mapping[str, AnsweredRequest]:
        wanted = frozenset(request_ids)
        with self._lock:
            _drop_older(self._answered, now=now, window_seconds=ANSWERED_WINDOW_SECONDS)
            return {record.request_id: record for record in self._answered if record.request_id in wanted}

    def slow_requests(self, *, now: float) -> tuple[SlowRequest, ...]:
        with self._lock:
            _drop_older(self._slow, now=now, window_seconds=SLOW_WINDOW_SECONDS)
            return tuple(self._slow)

    def clear(self) -> None:
        with self._lock:
            self._answered.clear()
            self._slow.clear()


def _drop_older(records: deque, *, now: float, window_seconds: float) -> None:
    while records and records[0].answered_at < now - window_seconds:
        records.popleft()


REQUEST_HISTORY = RequestHistory()
BUSY_READER = _BusyReader()


def prime_busy_numbers() -> None:
    BUSY_READER.prime()


def now() -> float:
    return time.time()
