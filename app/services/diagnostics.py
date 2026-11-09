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
import secrets
import signal
import sys
import threading
import time
import traceback
from pathlib import Path

from loguru import logger

from app.security.authenticated_logging import EncryptedLogSink
from app.security.authenticated_logging import EncryptedTextStream
from app.security.sensitive_logging import traceback_frame_summary
from app.server_runtime import resolve_runtime_logs_directory
from app.utils.time_units import MS_PER_SECOND


# Smaller than any file's size, so the first log file counts as the largest so far.
_BELOW_ANY_FILE_SIZE = -1
_LOG_ROTATION = "25 MB"
_LOG_RETENTION = "14 days"
_DIRECT_APPEND_LOG_MAX_BYTES = 25 * 1024 * 1024
_DIRECT_APPEND_LOG_TAIL_BYTES = 10 * 1024 * 1024
_DIRECT_APPEND_LOG_RECYCLE_INTERVAL_SECONDS = 300.0
_LOG_DIRECTORY_MAX_BYTES = 512 * 1024 * 1024
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
# Random bytes in the session id that names each authenticated log file.
_LOG_SESSION_ID_RANDOM_BYTES = 8
_diagnostic_file_handle = None  # shockharness: ignore[STATE001] reason="set once while the app is imported, before any server thread runs"
_process_diagnostics_configured = False  # shockharness: ignore[STATE001] reason="checked and set only by configure_process_diagnostics, run once while the app is imported"
_request_watchdog_started = False  # shockharness: ignore[STATE001] reason="started once, from configure_process_diagnostics while the app is imported"
_event_loop_watchdog_started = False  # shockharness: ignore[STATE001] reason="set by the startup event, on the single event loop of the single server"
_direct_append_log_recycler_started = False  # shockharness: ignore[STATE001] reason="started once, from configure_process_diagnostics while the app is imported"
_authenticated_logging_active = False  # shockharness: ignore[STATE001] reason="written only under _authenticated_logging_lock; readers see one bool"
_authenticated_logging_lock = threading.Lock()
_authenticated_log_sink: EncryptedLogSink | None = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock"
_authenticated_log_sink_id: int | None = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock"
_authenticated_log_path: Path | None = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock"
_authenticated_stdout: EncryptedTextStream | None = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock; the stream serializes its own writes and close"
_authenticated_stderr: EncryptedTextStream | None = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock; the stream serializes its own writes and close"
_plaintext_stdout = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock"
_plaintext_stderr = None  # shockharness: ignore[STATE001] reason="every access holds _authenticated_logging_lock"


@dataclass
class ActiveRequest:
    request_id: str
    method: str
    path: str
    has_query: bool
    client: str
    user_agent: str
    started_at: float
    last_logged_at: float


@dataclass(frozen=True)
class LoopStall:
    """The event loop answered a probe late: nothing the server does on the loop ran
    meanwhile. What was running is captured while the stall is under way (the watchdog
    looks every second), so a stall that ended before it looked has no stacks."""

    # When the probe was scheduled (UTC, ISO 8601).
    at: str
    # How long the loop had answered nothing: the whole stall once it is over, else so far.
    seconds: float
    # "METHOD /path 3.2s" for each request active during the stall, oldest first.
    requests: tuple[str, ...]
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
    state = "held (stall under way)"
    if stall.is_over:
        state = "stall"
    logger.warning(
        "[diagnostics] event loop {state} seconds={seconds:.2f} requests={requests}",
        state=state, seconds=stall.seconds, requests=list(stall.requests),
    )
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
    path: str
    has_query: bool
    client: str
    user_agent: str
    duration_seconds: float


@dataclass(frozen=True)
class LogDiskUsage:
    file_count: int
    total_bytes: int
    largest_file_path: Path
    largest_file_bytes: int


_active_requests: dict[str, ActiveRequest] = {}  # shockharness: ignore[STATE001] reason="every access holds _active_requests_lock"
_active_requests_lock = threading.Lock()


def _diagnostic_log_path(*, namespace: str) -> Path:
    if namespace.strip() == "":
        raise ValueError("namespace must not be empty")
    logs_directory = resolve_runtime_logs_directory()
    logs_directory.mkdir(parents=True, exist_ok=True)
    return logs_directory / f"{namespace}-server.log"


def _new_authenticated_log_path(*, namespace: str) -> Path:
    if namespace.strip() == "":
        raise ValueError("namespace must not be empty")
    logs_directory = resolve_runtime_logs_directory()
    logs_directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    session_id = secrets.token_hex(_LOG_SESSION_ID_RANDOM_BYTES)
    return logs_directory / f"{namespace}-server.auth-{timestamp}-{session_id}.log.enc"


def allow_plaintext_diagnostics(record: Mapping[str, object]) -> bool:
    del record
    return not _authenticated_logging_active


def log_unexpected_exception(
    *, context: str, exception: BaseException, request_id: str, level: str,
) -> None:
    """Keep plaintext diagnostics data-free; retain full traces in encrypted logs."""
    if context == "":
        raise ValueError("Exception context must not be empty")
    if level not in {"ERROR", "CRITICAL"}:
        raise ValueError(f"Unsupported unexpected-exception level: {level}")
    # An OS error's number (EADDRINUSE, ENOENT, ...) names the failure without
    # carrying data, unlike its message: it is the one detail kept in plaintext.
    errno_detail = ""
    if isinstance(exception, OSError) and exception.errno is not None:
        errno_detail = f" errno={exception.errno}"
    logger.bind(request_id=request_id).log(
        level,
        "[diagnostics] unexpected {context} exception "
        "error_type={error_type}{errno_detail} frames={frames}",
        context=context,
        error_type=type(exception).__name__,
        errno_detail=errno_detail,
        frames=traceback_frame_summary(exception.__traceback__),
    )
    write_encrypted_exception_trace(
        context=context, exception=exception, request_id=request_id,
    )


def write_encrypted_exception_trace(
    *, context: str, exception: BaseException, request_id: str,
) -> None:
    """Write exception messages only to the authenticated encrypted sink."""
    with _authenticated_logging_lock:
        if not _authenticated_logging_active:
            return
        if _authenticated_log_sink is None:
            raise RuntimeError("Authenticated logging is active without an encrypted sink")
        formatted = "".join(traceback.format_exception(exception))
        _authenticated_log_sink.write(
            f"[diagnostics] {context} request_id={request_id}\n{formatted}"
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


def activate_authenticated_logging(*, namespace: str, dek: bytes) -> Path:
    global _authenticated_logging_active
    global _authenticated_log_sink
    global _authenticated_log_sink_id
    global _authenticated_log_path
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
            if _authenticated_log_path is None:
                raise RuntimeError("Authenticated logging is active without a log path")
            return _authenticated_log_path

        _authenticated_log_path = _new_authenticated_log_path(namespace=namespace)
        _authenticated_log_sink = EncryptedLogSink(path=_authenticated_log_path, dek=dek)
        _authenticated_log_sink_id = logger.add(
            _authenticated_log_sink,
            level="INFO",
            backtrace=False,
            diagnose=False,
            enqueue=False,
            format=(
                "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | "
                "pid={process} thread={thread.name} | {message} | {extra}"
            ),
        )
        _disable_plaintext_fault_logging()
        _plaintext_stdout = sys.stdout
        _plaintext_stderr = sys.stderr
        _authenticated_stdout = EncryptedTextStream(destination=sys.stdout, dek=dek)
        _authenticated_stderr = EncryptedTextStream(destination=sys.stderr, dek=dek)
        sys.stdout = _authenticated_stdout
        sys.stderr = _authenticated_stderr
        _authenticated_logging_active = True
        return _authenticated_log_path


def deactivate_authenticated_logging() -> bool:
    global _authenticated_logging_active
    global _authenticated_log_sink
    global _authenticated_log_sink_id
    global _authenticated_log_path
    global _authenticated_stdout
    global _authenticated_stderr
    global _plaintext_stdout
    global _plaintext_stderr

    with _authenticated_logging_lock:
        if not _authenticated_logging_active:
            return False
        if _authenticated_log_sink is None or _authenticated_log_sink_id is None:
            raise RuntimeError("Authenticated logging is active without an encrypted sink")
        if _authenticated_stdout is None or _authenticated_stderr is None:
            raise RuntimeError("Authenticated logging is active without encrypted process streams")
        if _plaintext_stdout is None or _plaintext_stderr is None:
            raise RuntimeError("Authenticated logging is active without original process streams")

        logger.remove(_authenticated_log_sink_id)
        _authenticated_log_sink.close()
        sys.stdout = _plaintext_stdout
        sys.stderr = _plaintext_stderr
        _authenticated_stdout.close()
        _authenticated_stderr.close()

        _authenticated_log_sink = None
        _authenticated_log_sink_id = None
        _authenticated_log_path = None
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
    logger.add(
        str(log_path),
        level="INFO",
        backtrace=False,
        diagnose=False,
        rotation=_LOG_ROTATION,
        retention=_LOG_RETENTION,
        enqueue=True,
        filter=allow_plaintext_diagnostics,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | pid={process} thread={thread.name} | {message} | {extra}",
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

    logger.info(
        "[diagnostics] process diagnostics enabled log_path={log_path} fault_log_path={fault_log_path}",
        log_path=str(log_path),
        fault_log_path=str(fault_path),
    )
    start_request_watchdog()
    start_direct_append_log_recycler()
    assert_log_disk_usage_within_bounds()
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
    logger.warning(
        "[diagnostics] compacted append log path={path} old_size={old_size} retained_bytes={retained_bytes}",
        path=str(path),
        old_size=size_bytes,
        retained_bytes=len(tail_bytes),
    )
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


def _iter_log_files(*, logs_directory: Path) -> list[Path]:
    if not isinstance(logs_directory, Path):
        raise TypeError(f"logs_directory must be a Path, got {type(logs_directory)}")
    if not logs_directory.exists():
        return []
    return sorted(path for path in logs_directory.iterdir() if path.is_file())


def _matches_direct_append_pattern(*, path: Path) -> bool:
    for pattern in _DIRECT_APPEND_LOG_PATTERNS:
        if path.match(pattern):
            return True
    return False


def calculate_log_disk_usage(*, logs_directory: Path) -> LogDiskUsage:
    log_files = _iter_log_files(logs_directory=logs_directory)
    if len(log_files) == 0:
        return LogDiskUsage(
            file_count=0,
            total_bytes=0,
            largest_file_path=logs_directory,
            largest_file_bytes=0,
        )

    total_bytes = 0
    largest_file_path = log_files[0]
    largest_file_bytes = _BELOW_ANY_FILE_SIZE
    for path in log_files:
        size_bytes = path.stat().st_size
        total_bytes += size_bytes
        if size_bytes > largest_file_bytes:
            largest_file_path = path
            largest_file_bytes = size_bytes

    return LogDiskUsage(
        file_count=len(log_files),
        total_bytes=total_bytes,
        largest_file_path=largest_file_path,
        largest_file_bytes=largest_file_bytes,
    )


def assert_log_disk_usage_within_bounds() -> None:
    recycle_direct_append_logs()
    logs_directory = resolve_runtime_logs_directory()
    log_files = _iter_log_files(logs_directory=logs_directory)
    for path in log_files:
        if not _matches_direct_append_pattern(path=path):
            continue
        size_bytes = path.stat().st_size
        if size_bytes > _DIRECT_APPEND_LOG_MAX_BYTES:
            raise RuntimeError(
                f"Log file exceeds direct append cap after recycling: "
                f"path={path} size={size_bytes} cap={_DIRECT_APPEND_LOG_MAX_BYTES}"
            )

    usage = calculate_log_disk_usage(logs_directory=logs_directory)
    if usage.total_bytes > _LOG_DIRECTORY_MAX_BYTES:
        raise RuntimeError(
            f"Log directory exceeds disk bound: directory={logs_directory} "
            f"total={usage.total_bytes} cap={_LOG_DIRECTORY_MAX_BYTES} "
            f"files={usage.file_count} largest={usage.largest_file_path} "
            f"largest_size={usage.largest_file_bytes}"
        )


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
    log_unexpected_exception(
        context="process", exception=exc_value, request_id="", level="CRITICAL",
    )


def _log_unhandled_thread_exception(args: threading.ExceptHookArgs) -> None:
    if args.thread is None:
        raise RuntimeError("Thread exception hook missing thread")
    exception = args.exc_value
    if exception is None:
        raise RuntimeError("Thread exception hook missing exception")
    log_unexpected_exception(
        context=f"thread {args.thread.name}", exception=exception,
        request_id="", level="CRITICAL",
    )


def _format_thread_stacks() -> str:
    frames = sys._current_frames()
    lines: list[str] = []
    for thread in threading.enumerate():
        lines.append(f"\n# Thread {thread.name} ident={thread.ident} daemon={thread.daemon}")
        if thread.ident not in frames:
            lines.append("  <no frame>")
            continue
        lines.extend(traceback.format_stack(frames[thread.ident]))
    return "".join(lines)


def log_thread_dump(*, reason: str) -> None:
    if reason.strip() == "":
        raise ValueError("reason must not be empty")
    logger.error(
        "[diagnostics] thread dump reason={reason}\n{stacks}",
        reason=reason,
        stacks=_format_thread_stacks(),
    )


class TrackedRequest:
    def __init__(
        self,
        *,
        request_id: str,
        method: str,
        path: str,
        has_query: bool,
        client: str,
        user_agent: str,
        started_at: float,
    ) -> None:
        self._request_id = request_id
        begin_request(
            request_id=request_id,
            method=method,
            path=path,
            has_query=has_query,
            client=client,
            user_agent=user_agent,
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
        duration_ms = finish_request(
            request_id=self._request_id,
            ended_at=time.perf_counter(),
        )
        if exc_type is not None:
            if exc is None:
                raise RuntimeError("Tracked request exited with an exception type but no exception")
            log_unexpected_exception(
                context=f"request after {duration_ms:.2f} ms",
                exception=exc,
                request_id=self._request_id,
                level="ERROR",
            )
        return False


def track_request(
    *,
    request_id: str,
    method: str,
    path: str,
    has_query: bool,
    client: str,
    user_agent: str,
    started_at: float,
) -> TrackedRequest:
    return TrackedRequest(
        request_id=request_id,
        method=method,
        path=path,
        has_query=has_query,
        client=client,
        user_agent=user_agent,
        started_at=started_at,
    )


def begin_request(
    *,
    request_id: str,
    method: str,
    path: str,
    has_query: bool,
    client: str,
    user_agent: str,
    started_at: float,
) -> None:
    assert request_id != ""
    assert method != ""
    assert path.startswith("/")
    if not isinstance(has_query, bool):
        raise TypeError("has_query must be a bool")
    request = ActiveRequest(
        request_id=request_id,
        method=method,
        path=path,
        has_query=has_query,
        client=client,
        user_agent=user_agent,
        started_at=started_at,
        last_logged_at=started_at,
    )
    with _active_requests_lock:
        if request_id in _active_requests:
            raise RuntimeError(f"Request id {request_id} is already in flight")
        _active_requests[request_id] = request


def finish_request(*, request_id: str, ended_at: float) -> float:
    with _active_requests_lock:
        request = _active_requests.pop(request_id)
    duration_ms = (ended_at - request.started_at) * MS_PER_SECOND
    return duration_ms


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
                    path=request.path,
                    has_query=request.has_query,
                    client=request.client,
                    user_agent=request.user_agent,
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
            logger.warning(
                "[diagnostics] slow in-flight request request_id={request_id} method={method} path={path} has_query={has_query} client={client} duration={duration:.2f}s user_agent={user_agent}",
                request_id=request.request_id,
                method=request.method,
                path=request.path,
                has_query=request.has_query,
                client=request.client,
                duration=request.duration_seconds,
                user_agent=request.user_agent,
            )


def _describe_active_requests(*, now: float) -> tuple[str, ...]:
    requests = sorted(snapshot_active_requests().values(), key=lambda request: request.started_at)
    return tuple(f"{request.method} {request.path} {now - request.started_at:.1f}s" for request in requests)


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
        held = LoopStall(at=scheduled_wall_time, seconds=now - scheduled_at, requests=_describe_active_requests(now=now),
                         stacks=_format_thread_stacks(), is_over=False)
        self._stall_capture = (scheduled_at, held, record_loop_stall(held, replaces_line_at=None))

    def _record_finished_stalls(self) -> None:
        """Records each probe answered late as a finished stall, with the stacks taken while
        it was under way when the watchdog looked in time (replacing that record)."""
        with self._lock:
            late_acks = list(self._late_acks)
            self._late_acks.clear()
        for scheduled_at, scheduled_wall_time, waited in late_acks:
            requests: tuple[str, ...] = ()
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
        logger.error(
            "[diagnostics] event loop unresponsive blocked_for={blocked:.2f}s active_requests={active_count}",
            blocked=blocked_seconds,
            active_count=len(active_requests),
        )
        for request in active_requests.values():
            logger.error(
                "[diagnostics] active during loop stall request_id={request_id} method={method} path={path} has_query={has_query} client={client} duration={duration:.2f}s",
                request_id=request.request_id,
                method=request.method,
                path=request.path,
                has_query=request.has_query,
                client=request.client,
                duration=now - request.started_at,
            )
        log_thread_dump(reason=f"event loop unresponsive for {blocked_seconds:.2f}s")


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
    logger.info("[diagnostics] asyncio diagnostics enabled")


def _handle_asyncio_exception(
    loop: asyncio.AbstractEventLoop,
    context: dict[str, object],
) -> None:
    # asyncio's error context carries an exception only when one was raised.
    if "exception" in context and isinstance(context["exception"], BaseException):
        exception = context["exception"]
        log_unexpected_exception(
            context="asyncio task", exception=exception, request_id="", level="ERROR",
        )
        return
    logger.error(
        "[diagnostics] asyncio error without exception context_keys={context_keys}",
        context_keys=sorted(str(key) for key in context),
    )
