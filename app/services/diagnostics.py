from __future__ import annotations

from app.security.crypto_sizes import AES_256_KEY_BYTES
import asyncio
from collections import deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import faulthandler
import json
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

from loguru import logger

from app.security.authenticated_logging import EncryptedTextStream
from app.services import safe_log
from app.services.log_retention import retain_newest_rotated_server_logs
from app.services.log_retention import trim_logs_directory
from app.server_runtime import resolve_namespaces_directory
from app.server_runtime import resolve_runtime_logs_directory
from app.utils.time_units import MS_PER_SECOND


_LOG_ROTATION = "25 MB"
_DIRECT_APPEND_LOG_MAX_BYTES = 25 * 1024 * 1024
_DIRECT_APPEND_LOG_TAIL_BYTES = 10 * 1024 * 1024
_DIRECT_APPEND_LOG_RECYCLE_INTERVAL_SECONDS = 300.0
_DIRECT_APPEND_LOG_PATTERNS = (
    "namespace-*.log",
    "namespace-delete-*.log",
    "*-server.fault.log",
)
_EVENT_LOOP_PROBE_INTERVAL_SECONDS = 1.0
_EVENT_LOOP_STALL_SECONDS = 5.0
# A probe the loop answers this late or later is a recorded stall (recorded_loop_stalls, and
# the file METALIST_LOOP_STALL_LOG names): the browser suites fail on any (docs/future-plans/scale-testing.md,
# part 2: 0.26.0 held the loop for 100 s and only logged it).
RECORDED_LOOP_STALL_SECONDS = 1.0
_MAX_RECORDED_LOOP_STALLS = 50
LOOP_STALL_LOG_ENVIRONMENT_VARIABLE = "METALIST_LOOP_STALL_LOG"
_EVENT_LOOP_STALL_LOG_INTERVAL_SECONDS = 5.0
_SLOW_REQUEST_SECONDS = 10.0
_SLOW_REQUEST_LOG_INTERVAL_SECONDS = 10.0
_REQUEST_WATCH_INTERVAL_SECONDS = 2.0
_diagnostic_file_handle = None  # shockharness: ignore[STATE001] reason="set once while the app is imported, before any server thread runs"
_process_diagnostics_configured = False  # shockharness: ignore[STATE001] reason="checked and set only by configure_process_diagnostics, run once while the app is imported"
_request_watchdog_started = False  # shockharness: ignore[STATE001] reason="started once, from configure_process_diagnostics while the app is imported"
_event_loop_watchdog_started = False  # shockharness: ignore[STATE001] reason="set by the startup event, on the single event loop of the single server"
_direct_append_log_recycler_started = False  # shockharness: ignore[STATE001] reason="started once, from configure_process_diagnostics while the app is imported"
_authenticated_logging_active = False  # shockharness: ignore[STATE001] reason="written only under _authenticated_logging_lock; readers see one bool"
_authenticated_logging_lock = threading.Lock()
_authenticated_stdout: EncryptedTextStream | None = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock; the stream serializes its own writes and close"
_authenticated_stderr: EncryptedTextStream | None = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock; the stream serializes its own writes and close"
_plaintext_stdout = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock"
_plaintext_stderr = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock"


@dataclass
class ActiveRequest:
    request_id: str
    method: str
    # The request's ASGI scope: routing writes the matched route into it while the request runs.
    scope: Mapping[str, object]
    has_query: bool
    started_at: float
    last_logged_at: float

    @property
    def route(self) -> str:
        return safe_log.route_template(self.scope)


@dataclass(frozen=True)
class LoopStall:
    """The event loop answered a probe late: nothing the server does on the loop ran
    meanwhile. What was running is captured while the stall is under way (the watchdog
    looks every second), so a stall that ended before it looked has no stacks."""

    # When the probe was scheduled (UTC, ISO 8601).
    at: str
    # How long the loop had answered nothing: the whole stall once it is over, else so far.
    seconds: float
    # (method, route template) of each request active during the stall, oldest first.
    requests: tuple[tuple[str, str], ...]
    # Every thread's stack while stalled; "" when the stall ended before the watchdog looked.
    stacks: str
    # False for the record written while the loop is still held (when its stacks are taken),
    # which the finished stall's record replaces: a server stopped mid-stall leaves it behind.
    is_over: bool


_recorded_loop_stalls: deque[LoopStall] = deque(maxlen=_MAX_RECORDED_LOOP_STALLS)  # shockharness: ignore[STATE001] reason="every access holds _recorded_loop_stalls_lock"
_recorded_loop_stalls_lock = threading.Lock()


def record_loop_stall(stall: LoopStall, *, replaces_line_at: int | None) -> int | None:
    """Keeps a finished stall (the newest _MAX_RECORDED_LOOP_STALLS), writes the stall as a
    JSON line to the file METALIST_LOOP_STALL_LOG names when set, and logs it. Returns where
    its line starts in that file (None without one): a stall still under way is written when
    its stacks are taken, and the finished stall's line replaces it through replaces_line_at
    (the file has one writer, this process)."""
    if stall.seconds < RECORDED_LOOP_STALL_SECONDS:
        raise ValueError(f"a recorded stall is {RECORDED_LOOP_STALL_SECONDS} s or longer, got {stall.seconds}")
    if stall.is_over:
        with _recorded_loop_stalls_lock:
            _recorded_loop_stalls.append(stall)
    line_at: int | None = None
    if LOOP_STALL_LOG_ENVIRONMENT_VARIABLE in os.environ:
        with open(os.environ[LOOP_STALL_LOG_ENVIRONMENT_VARIABLE], "a", encoding="utf-8") as stall_log:
            if replaces_line_at is not None:
                stall_log.truncate(replaces_line_at)
            stall_log.seek(0, os.SEEK_END)
            line_at = stall_log.tell()
            stall_log.write(json.dumps(asdict(stall)) + "\n")
    state = "held"
    if stall.is_over:
        state = "over"
    safe_log.log_event("WARNING", "loop.stall", state=state, seconds=stall.seconds, requests=stall.requests)
    return line_at


def recorded_loop_stalls() -> list[LoopStall]:
    with _recorded_loop_stalls_lock:
        return list(_recorded_loop_stalls)


def reset_recorded_loop_stalls() -> None:
    with _recorded_loop_stalls_lock:
        _recorded_loop_stalls.clear()


@dataclass(frozen=True)
class SlowRequestLog:
    request_id: str
    method: str
    route: str
    has_query: bool
    duration_seconds: float


_active_requests: dict[str, ActiveRequest] = {}  # shockharness: ignore[STATE001] reason="every access holds _active_requests_lock"
_active_requests_lock = threading.Lock()


def _diagnostic_log_path(*, namespace: str) -> Path:
    if namespace.strip() == "":
        raise ValueError("namespace must not be empty")
    logs_directory = resolve_runtime_logs_directory()
    logs_directory.mkdir(parents=True, exist_ok=True)
    return logs_directory / f"{namespace}-server.log"


def _errno_of(exception: BaseException) -> int | None:
    """An OS error's number (EADDRINUSE, ENOENT, ...) names the failure without carrying data,
    unlike its message: it is the one detail of an exception kept besides its type and frames."""
    if isinstance(exception, OSError) and exception.errno is not None:
        return exception.errno
    return None


def log_unexpected_exception(*, context: str, exception: BaseException, level: str) -> None:
    """Record the exception's type and code locations only, never its message."""
    if level not in {"ERROR", "CRITICAL"}:
        raise ValueError(f"Unsupported unexpected-exception level: {level}")
    safe_log.log_event(
        level, "exception",
        context=context,
        error_type=type(exception).__name__,
        errno=_errno_of(exception),
        frames=safe_log.safe_code_frames(exception.__traceback__),
    )


def log_request_exception(*, request: ActiveRequest, exception: BaseException, duration_ms: float) -> None:
    """A request that failed: its id and route with the exception's type and code locations."""
    safe_log.log_event(
        "ERROR", "request.exception",
        request_id=request.request_id,
        method=request.method,
        route=request.route,
        duration_ms=duration_ms,
        error_type=type(exception).__name__,
        errno=_errno_of(exception),
        frames=safe_log.safe_code_frames(exception.__traceback__),
    )


def _disable_plaintext_fault_logging() -> None:
    if hasattr(signal, "SIGUSR1"):
        faulthandler.unregister(signal.SIGUSR1)
    if faulthandler.is_enabled():
        faulthandler.disable()


def _enable_plaintext_fault_logging() -> None:
    if _diagnostic_file_handle is None:
        return
    faulthandler.enable(file=_diagnostic_file_handle, all_threads=True)
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(
            signal.SIGUSR1,
            file=_diagnostic_file_handle,
            all_threads=True,
            chain=False,
        )


def activate_authenticated_logging(*, namespace: str, dek: bytes) -> None:
    """While a vault is unlocked the plain log keeps going: it holds only allow-listed events
    (app/services/safe_log.py), before and after login alike. Fault logging is off, and
    anything printed reaches the process streams only encrypted. No encrypted log file is
    kept (docs/ready-to-build/error-reports.md section 6, 2026-11-11)."""
    global _authenticated_logging_active
    global _authenticated_stdout
    global _authenticated_stderr
    global _plaintext_stdout
    global _plaintext_stderr

    if not isinstance(namespace, str) or namespace.strip() == "":
        raise ValueError("namespace must be a non-empty string")
    if not isinstance(dek, bytes) or len(dek) != AES_256_KEY_BYTES:
        raise ValueError(f"authenticated logging requires a {AES_256_KEY_BYTES}-byte DEK")

    with _authenticated_logging_lock:
        if _authenticated_logging_active:
            return
        _disable_plaintext_fault_logging()
        _plaintext_stdout = sys.stdout
        _plaintext_stderr = sys.stderr
        _authenticated_stdout = EncryptedTextStream(destination=sys.stdout, dek=dek)
        _authenticated_stderr = EncryptedTextStream(destination=sys.stderr, dek=dek)
        sys.stdout = _authenticated_stdout
        sys.stderr = _authenticated_stderr
        _authenticated_logging_active = True


def deactivate_authenticated_logging() -> bool:
    global _authenticated_logging_active
    global _authenticated_stdout
    global _authenticated_stderr
    global _plaintext_stdout
    global _plaintext_stderr

    with _authenticated_logging_lock:
        if not _authenticated_logging_active:
            return False
        if _authenticated_stdout is None or _authenticated_stderr is None:
            raise RuntimeError("Authenticated logging is active without encrypted process streams")
        if _plaintext_stdout is None or _plaintext_stderr is None:
            raise RuntimeError("Authenticated logging is active without original process streams")

        sys.stdout = _plaintext_stdout
        sys.stderr = _plaintext_stderr
        _authenticated_stdout.close()
        _authenticated_stderr.close()

        _authenticated_stdout = None
        _authenticated_stderr = None
        _plaintext_stdout = None
        _plaintext_stderr = None
        _enable_plaintext_fault_logging()
        _authenticated_logging_active = False
        return True


def configure_process_diagnostics(*, namespace: str, enabled: bool) -> Path | None:
    global _diagnostic_file_handle
    global _process_diagnostics_configured

    if not enabled:
        return None
    if _process_diagnostics_configured:
        return _diagnostic_log_path(namespace=namespace)

    log_path = _diagnostic_log_path(namespace=namespace)
    # Before this vault's server log opens: the logs folder stays bounded per vault, and logs
    # of removed vaults go (log_retention.py), so no size cap has to refuse a start.
    trim_logs_directory(
        logs_directory=log_path.parent,
        namespaces_directory=resolve_namespaces_directory(),
        own_vault=namespace,
        now=time.time(),
    )
    logger.add(
        str(log_path),
        level="INFO",
        backtrace=False,
        diagnose=False,
        rotation=_LOG_ROTATION,
        retention=retain_newest_rotated_server_logs,
        enqueue=True,
        format=safe_log.SAFE_LOG_FORMAT,
    )

    fault_path = log_path.with_suffix(".fault.log")
    recycle_direct_append_log_file(path=fault_path)
    _diagnostic_file_handle = fault_path.open("a", buffering=1)
    faulthandler.enable(file=_diagnostic_file_handle, all_threads=True)
    if hasattr(signal, "SIGUSR1"):
        faulthandler.register(
            signal.SIGUSR1,
            file=_diagnostic_file_handle,
            all_threads=True,
            chain=False,
        )

    sys.excepthook = _log_unhandled_exception
    threading.excepthook = _log_unhandled_thread_exception
    _process_diagnostics_configured = True

    safe_log.log_event("INFO", "diagnostics.enabled")
    start_request_watchdog()
    start_direct_append_log_recycler()
    return log_path


def recycle_direct_append_log_file(*, path: Path) -> bool:
    if not isinstance(path, Path):
        raise TypeError(f"path must be a Path, got {type(path)}")
    if not path.exists():
        return False
    size_bytes = path.stat().st_size
    if size_bytes <= _DIRECT_APPEND_LOG_MAX_BYTES:
        return False

    tail_bytes = path.read_bytes()[-_DIRECT_APPEND_LOG_TAIL_BYTES:]
    marker = (
        b"\n[diagnostics] log compacted because it exceeded "
        + str(_DIRECT_APPEND_LOG_MAX_BYTES).encode("ascii")
        + b" bytes; retained tail follows\n"
    )
    path.write_bytes(marker + tail_bytes)
    safe_log.log_event("WARNING", "log.compacted", old_bytes=size_bytes, kept_bytes=len(tail_bytes))
    return True


def recycle_direct_append_logs() -> int:
    logs_directory = resolve_runtime_logs_directory()
    if not logs_directory.exists():
        return 0
    recycled_count = 0
    for pattern in _DIRECT_APPEND_LOG_PATTERNS:
        for path in logs_directory.glob(pattern):
            if not path.is_file():
                continue
            if recycle_direct_append_log_file(path=path):
                recycled_count += 1
    return recycled_count


def start_direct_append_log_recycler() -> None:
    global _direct_append_log_recycler_started

    if _direct_append_log_recycler_started:
        return
    recycle_direct_append_logs()
    thread = threading.Thread(
        target=_direct_append_log_recycler_loop,
        name="metalist-log-recycler",
        daemon=True,
    )
    _direct_append_log_recycler_started = True
    thread.start()


def _direct_append_log_recycler_loop() -> None:
    while True:
        time.sleep(_DIRECT_APPEND_LOG_RECYCLE_INTERVAL_SECONDS)
        recycle_direct_append_logs()


def _log_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
    log_unexpected_exception(context="process", exception=exc_value, level="CRITICAL")


def _log_unhandled_thread_exception(args: threading.ExceptHookArgs) -> None:
    if args.thread is None:
        raise RuntimeError("Thread exception hook missing thread")
    exception = args.exc_value
    if exception is None:
        raise RuntimeError("Thread exception hook missing exception")
    log_unexpected_exception(context="thread", exception=exception, level="CRITICAL")


def _format_thread_stacks() -> str:
    """Every thread's stack as text, for the loop-stall file a test run names (never the log)."""
    frames = sys._current_frames()
    lines: list[str] = []
    for thread in threading.enumerate():
        lines.append(f"\n# Thread {thread.name} ident={thread.ident} daemon={thread.daemon}")
        if thread.ident not in frames:
            lines.append("  <no frame>")
            continue
        lines.extend(traceback.format_stack(frames[thread.ident]))
    return "".join(lines)


def log_thread_stacks() -> None:
    """Every thread's stack as code locations, one record per thread."""
    frames = sys._current_frames()
    for thread in threading.enumerate():
        if thread.ident not in frames:
            continue
        safe_log.log_event(
            "ERROR", "thread.stack",
            thread=safe_log.safe_thread_name(thread.name),
            frames=safe_log.safe_stack_frames(frames[thread.ident]),
        )


class TrackedRequest:
    def __init__(
        self,
        *,
        request_id: str,
        method: str,
        scope: Mapping[str, object],
        has_query: bool,
        started_at: float,
    ) -> None:
        self._request_id = request_id
        begin_request(
            request_id=request_id,
            method=method,
            scope=scope,
            has_query=has_query,
            started_at=started_at,
        )

    def __enter__(self) -> "TrackedRequest":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_traceback: object,
    ) -> bool:
        request, duration_ms = finish_request(
            request_id=self._request_id,
            ended_at=time.perf_counter(),
        )
        if exc_type is not None:
            if exc is None:
                raise RuntimeError("Tracked request exited with an exception type but no exception")
            log_request_exception(request=request, exception=exc, duration_ms=duration_ms)
        return False


def track_request(
    *,
    request_id: str,
    method: str,
    scope: Mapping[str, object],
    has_query: bool,
    started_at: float,
) -> TrackedRequest:
    return TrackedRequest(
        request_id=request_id,
        method=method,
        scope=scope,
        has_query=has_query,
        started_at=started_at,
    )


def begin_request(
    *,
    request_id: str,
    method: str,
    scope: Mapping[str, object],
    has_query: bool,
    started_at: float,
) -> None:
    assert request_id != ""
    assert method != ""
    assert isinstance(scope["path"], str) and scope["path"].startswith("/")
    if not isinstance(has_query, bool):
        raise TypeError("has_query must be a bool")
    request = ActiveRequest(
        request_id=request_id,
        method=method,
        scope=scope,
        has_query=has_query,
        started_at=started_at,
        last_logged_at=started_at,
    )
    with _active_requests_lock:
        if request_id in _active_requests:
            raise RuntimeError(f"Request id {request_id} is already in flight")
        _active_requests[request_id] = request


def finish_request(*, request_id: str, ended_at: float) -> tuple[ActiveRequest, float]:
    """The finished request and how long it took, in milliseconds."""
    with _active_requests_lock:
        request = _active_requests.pop(request_id)
    duration_ms = (ended_at - request.started_at) * MS_PER_SECOND
    return request, duration_ms


def snapshot_active_requests() -> Mapping[str, ActiveRequest]:
    with _active_requests_lock:
        return dict(_active_requests)


def collect_slow_request_logs(*, now: float, threshold_seconds: float) -> list[SlowRequestLog]:
    if threshold_seconds <= 0.0:
        raise ValueError("threshold_seconds must be positive")
    slow_requests: list[SlowRequestLog] = []
    with _active_requests_lock:
        for request in _active_requests.values():
            duration_seconds = now - request.started_at
            since_last_log_seconds = now - request.last_logged_at
            if duration_seconds < threshold_seconds:
                continue
            if since_last_log_seconds < _SLOW_REQUEST_LOG_INTERVAL_SECONDS:
                continue
            request.last_logged_at = now
            slow_requests.append(
                SlowRequestLog(
                    request_id=request.request_id,
                    method=request.method,
                    route=request.route,
                    has_query=request.has_query,
                    duration_seconds=duration_seconds,
                )
            )
    return slow_requests


def start_request_watchdog() -> None:
    global _request_watchdog_started

    if _request_watchdog_started:
        return
    thread = threading.Thread(
        target=_request_watchdog_loop,
        name="metalist-request-watchdog",
        daemon=True,
    )
    _request_watchdog_started = True
    thread.start()


def _request_watchdog_loop() -> None:
    while True:
        time.sleep(_REQUEST_WATCH_INTERVAL_SECONDS)
        slow_requests = collect_slow_request_logs(
            now=time.perf_counter(),
            threshold_seconds=_SLOW_REQUEST_SECONDS,
        )
        for request in slow_requests:
            safe_log.log_event(
                "WARNING", "request.slow",
                request_id=request.request_id,
                method=request.method,
                route=request.route,
                seconds=request.duration_seconds,
                has_query=request.has_query,
            )


def _describe_active_requests() -> tuple[tuple[str, str], ...]:
    requests = sorted(snapshot_active_requests().values(), key=lambda request: request.started_at)
    return tuple((request.method, request.route) for request in requests)


class EventLoopWatchdog:
    """A thread that probes the event loop every second. A probe answered a second or more
    late is recorded as a LoopStall, with the requests and thread stacks captured while it
    was still waiting; one five seconds late is also logged with a thread dump."""

    def __init__(self, *, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._lock = threading.Lock()
        self._last_ack_at = time.perf_counter()
        self._last_logged_at = self._last_ack_at
        self._probe_pending = False
        self._probe_scheduled_at = self._last_ack_at
        self._probe_scheduled_wall_time = ""
        # The stall under way, written when the pending probe had waited a second: the probe's
        # scheduling time, the record, and where its line is in the stall file. Only the
        # watchdog thread touches it.
        self._stall_capture: tuple[float, LoopStall, int | None] | None = None
        # Probes the loop thread answered a second or more late: (scheduled at, scheduled
        # wall time, waited), recorded by the watchdog thread.
        self._late_acks: list[tuple[float, str, float]] = []
        self._stopped = threading.Event()

    def start(self) -> None:
        thread = threading.Thread(
            target=self._watch_loop,
            name="metalist-event-loop-watchdog",
            daemon=True,
        )
        thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def _ack_probe(self) -> None:
        now = time.perf_counter()
        with self._lock:
            waited = now - self._probe_scheduled_at
            self._last_ack_at = now
            self._probe_pending = False
            if waited >= RECORDED_LOOP_STALL_SECONDS:
                self._late_acks.append((self._probe_scheduled_at, self._probe_scheduled_wall_time, waited))

    def _schedule_probe_if_needed(self) -> None:
        with self._lock:
            if self._probe_pending:
                return
            self._probe_pending = True
            self._probe_scheduled_at = time.perf_counter()
            self._probe_scheduled_wall_time = datetime.now(timezone.utc).isoformat()
        self._loop.call_soon_threadsafe(self._ack_probe)

    def _capture_if_stalled(self, *, now: float) -> None:
        """Once the pending probe has waited a second, records the stall under way: the
        requests and every thread's stack, which show what holds the loop. Written at once,
        so a server stopped while still held leaves it behind."""
        with self._lock:
            if not self._probe_pending:
                return
            scheduled_at = self._probe_scheduled_at
            scheduled_wall_time = self._probe_scheduled_wall_time
            if now - scheduled_at < RECORDED_LOOP_STALL_SECONDS:
                return
        if self._stall_capture is not None and self._stall_capture[0] == scheduled_at:
            return
        held = LoopStall(at=scheduled_wall_time, seconds=now - scheduled_at, requests=_describe_active_requests(),
                         stacks=_format_thread_stacks(), is_over=False)
        self._stall_capture = (scheduled_at, held, record_loop_stall(held, replaces_line_at=None))

    def _record_finished_stalls(self) -> None:
        """Records each probe answered late as a finished stall, with the stacks taken while
        it was under way when the watchdog looked in time (replacing that record)."""
        with self._lock:
            late_acks = list(self._late_acks)
            self._late_acks.clear()
        for scheduled_at, scheduled_wall_time, waited in late_acks:
            requests: tuple[tuple[str, str], ...] = ()
            stacks = ""
            line_at: int | None = None
            if self._stall_capture is not None and self._stall_capture[0] == scheduled_at:
                _scheduled_at, held, line_at = self._stall_capture
                requests, stacks = held.requests, held.stacks
            self._stall_capture = None
            record_loop_stall(LoopStall(at=scheduled_wall_time, seconds=waited, requests=requests, stacks=stacks, is_over=True),
                              replaces_line_at=line_at)

    def _watch_loop(self) -> None:
        while not self._stopped.wait(_EVENT_LOOP_PROBE_INTERVAL_SECONDS):
            self._record_finished_stalls()
            self._schedule_probe_if_needed()
            now = time.perf_counter()
            self._capture_if_stalled(now=now)
            self._log_stall_if_needed(now=now)

    def _log_stall_if_needed(self, *, now: float) -> None:
        should_log = False
        blocked_seconds = 0.0
        active_requests = snapshot_active_requests()
        with self._lock:
            blocked_seconds = now - self._last_ack_at
            since_last_log_seconds = now - self._last_logged_at
            if (
                blocked_seconds >= _EVENT_LOOP_STALL_SECONDS
                and since_last_log_seconds >= _EVENT_LOOP_STALL_LOG_INTERVAL_SECONDS
            ):
                self._last_logged_at = now
                should_log = True
        if not should_log:
            return
        safe_log.log_event(
            "ERROR", "loop.unresponsive", seconds=blocked_seconds, active_requests=len(active_requests),
        )
        for request in active_requests.values():
            safe_log.log_event(
                "ERROR", "request.active_during_stall",
                request_id=request.request_id,
                method=request.method,
                route=request.route,
                seconds=now - request.started_at,
                has_query=request.has_query,
            )
        log_thread_stacks()


def start_asyncio_diagnostics(*, enabled: bool) -> None:
    global _event_loop_watchdog_started

    if not enabled:
        return
    if _event_loop_watchdog_started:
        return
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(_handle_asyncio_exception)
    watchdog = EventLoopWatchdog(loop=loop)
    _event_loop_watchdog_started = True
    watchdog.start()
    safe_log.log_event("INFO", "asyncio_diagnostics.enabled")


def _handle_asyncio_exception(
    loop: asyncio.AbstractEventLoop,
    context: dict[str, object],
) -> None:
    # asyncio's error context carries an exception only when one was raised.
    if "exception" in context and isinstance(context["exception"], BaseException):
        exception = context["exception"]
        log_unexpected_exception(context="asyncio task", exception=exception, level="ERROR")
        return
    safe_log.log_event(
        "ERROR", "asyncio.error_without_exception",
        context_keys=tuple(sorted(key for key in context if isinstance(key, str) and key.isidentifier())),
    )
