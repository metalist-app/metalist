"""The one plain log MetaList writes, before and after login (docs/ready-to-build/error-reports.md,
section 6): only MetaList's own events from the allow-list below, each with typed fields.

The guarantee is checked, not hoped for. Every record passes install_safe_log_guard's check
before any sink sees it: a record that is not an allow-listed event, has a field the event
does not declare, misses one, or holds a value outside its field's type, throws
UnsafeLogRecord in the code that logged it. Nothing else reaches the log: no free text, no
error messages, no note text, no paths as the browser sent them (a route is the template the
app declares, `/api/v2/notes/{note_id}/save`). Libraries' records (httpx logs every URL it
fetches, which after login includes links in notes) never pass as they are: only their
warnings and errors, as the logger's package and the error's type and code lines.

The error a rejected record raises names the event and field, never the value."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import logging
import math
from pathlib import Path
import re
import sysconfig
import threading
import traceback
from types import FrameType, TracebackType

from fastapi.routing import iter_route_contexts
from loguru import logger
from starlette.routing import BaseRoute, Mount


class UnsafeLogRecord(RuntimeError):
    """A record that is not an allow-listed event with valid typed fields: a bug in the code
    that logged it, never written."""


# What the plain log's sinks write: the time, the level and the checked event line only.
SAFE_LOG_FORMAT = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | pid={process} | {message}"

# The route of a request no route matched, and of every static file (its name is not written).
NO_ROUTE = "(no route)"
STATIC_ROUTE = "/static/{path}"
# A value a field has no value for: no request id, no error type, no errno, no size.
NONE_VALUE = "-"
# A frame of code outside MetaList, its libraries and Python itself.
EXTERNAL_FRAME = "external"
# A library logger whose package is not on the list below.
OTHER_LIBRARY = "other"

_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
_HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "OTHER"})
_LOWEST_HTTP_STATUS = 100
_HIGHEST_HTTP_STATUS = 599
_REQUEST_ID = re.compile(r"[0-9a-f]{8}")
_CODE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# A request under way is written as its method and route.
_REQUEST_LINE_PARTS = 2
_RESPONSE_SIZE = re.compile(r"[0-9]+")
_CODE_FRAME = re.compile(r"(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_.\-]+\.py:[0-9]+:[A-Za-z0-9_.<>]+")
# Thread names come from code (MetaList's own, the standard library's "Thread-3 (worker)").
_THREAD_NAME = re.compile(r"[A-Za-z0-9_.\-]+(?: \([A-Za-z0-9_.<>]+\))?")

# The packages whose loggers MetaList runs with; a logger from any other is "other".
LIBRARY_LOGGER_PACKAGES = frozenset({
    "anyio", "asyncio", "concurrent", "fastapi", "h11", "h2", "httpcore", "httpx", "markdown_it",
    "multipart", "openai", "PIL", "python_multipart", "sqlite3", "starlette", "urllib3", "uvicorn",
    "watchfiles", "websockets",
})
# Loggers named after MetaList's own modules: its code logs through log_event only.
_METALIST_LOGGER_ROOTS = frozenset({"app", "main", "__main__"})

# uvicorn's lifecycle lines, by the message template in its code (never its arguments): scripts
# wait for "server stage=listening" (scripts/throwaway-metalist.mjs) and count
# "server stage=startup_complete" (scripts/browser-smoke.mjs).
_UVICORN_STAGE_BY_TEMPLATE: Mapping[str, str] = {
    "Started server process [%d]": "process_started",
    "Waiting for application startup.": "waiting_for_startup",
    "Application startup complete.": "startup_complete",
    "Shutting down": "shutting_down",
    "Waiting for application shutdown.": "waiting_for_shutdown",
    "Application shutdown complete.": "shutdown_complete",
    "Finished server process [%d]": "process_finished",
}
# uvicorn writes its address into this line itself; the line is recognized by its start.
_UVICORN_LISTENING_PREFIX = "Uvicorn running on "
SERVER_STAGES = frozenset({*_UVICORN_STAGE_BY_TEMPLATE.values(), "listening"})
EXCEPTION_CONTEXTS = frozenset({"process", "thread", "asyncio task", "HTTP request"})
STARTUP_STEPS = frozenset({
    "runtime hardening checks", "schema + settings bootstrap", "file registry bootstrap",
    "linked list integrity check", "empty-note encryption metadata repair", "cache population",
    "note store hydration", "freed memory release", "read guard enable", "total startup",
})
UNDO_DIRECTIONS = frozenset({"undo", "redo"})
UNDO_OP_TYPES = frozenset({
    "update_content", "tag_sources", "tag_sources_batch", "move", "collapse", "collapse_batch",
    "paste_into", "split_note", "file_content", "create_note", "delete_subtree", "paste_subtree",
})
LOOP_STALL_STATES = frozenset({"held", "over"})
PROXY_STAGES = frozenset({"upstream", "response"})
DATABASES = frozenset({"notes", "files"})
DEV_DATABASES = frozenset({"test", "file"})
SQL_VERBS = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER",
                       "PRAGMA", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE", "WITH", "OTHER"})


@dataclass(frozen=True)
class FieldKind:
    """A field's type: what it accepts, and how it is written."""

    name: str
    render: Callable[[object], str | None]


def _render_milliseconds_or_seconds(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return f"{value:.2f}"


_PERCENT_MAX = 100.0


def _render_percent(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= _PERCENT_MAX:
        return None
    return f"{value:.1f}"


def _render_count(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return str(value)


def _render_flag(value: object) -> str | None:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return None


def _render_request_id(value: object) -> str | None:
    if value == "":
        return NONE_VALUE
    if not isinstance(value, str) or _REQUEST_ID.fullmatch(value) is None:
        return None
    return value


def _render_http_method(value: object) -> str | None:
    if value not in _HTTP_METHODS:
        return None
    return str(value)


def _render_http_status(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value < _LOWEST_HTTP_STATUS or value > _HIGHEST_HTTP_STATUS:
        return None
    return str(value)


def _render_code_name(value: object) -> str | None:
    if value == NONE_VALUE:
        return NONE_VALUE
    if not isinstance(value, str) or _CODE_NAME.fullmatch(value) is None:
        return None
    return value


def _render_code_names(value: object) -> str | None:
    if not isinstance(value, tuple):
        return None
    rendered = [_render_code_name(name) for name in value]
    if None in rendered or NONE_VALUE in value:
        return None
    return "[" + ", ".join(str(name) for name in rendered) + "]"


def _render_errno(value: object) -> str | None:
    if value is None:
        return NONE_VALUE
    return _render_count(value)


def _render_response_size(value: object) -> str | None:
    if value == NONE_VALUE:
        return NONE_VALUE
    if not isinstance(value, str) or _RESPONSE_SIZE.fullmatch(value) is None:
        return None
    return value


def _render_code_frames(value: object) -> str | None:
    if not isinstance(value, tuple):
        return None
    for frame in value:
        if frame != EXTERNAL_FRAME and (not isinstance(frame, str) or _CODE_FRAME.fullmatch(frame) is None):
            return None
    return "[" + ", ".join(value) + "]"


def _render_thread_name(value: object) -> str | None:
    if not isinstance(value, str) or _THREAD_NAME.fullmatch(value) is None:
        return None
    return value


def _choice(name: str, values: frozenset[str]) -> FieldKind:
    def render(value: object) -> str | None:
        if value not in values:
            return None
        return str(value)
    return FieldKind(name=name, render=render)


# The routes and handlers the app declares (allow_route_templates); written as they are.
_allowed_routes: frozenset[str] = frozenset({NO_ROUTE, STATIC_ROUTE})  # shockharness: ignore[STATE001] reason="replaced whole under _allowed_routes_lock; readers see one frozenset"
_allowed_handlers: frozenset[str] = frozenset({NO_ROUTE})  # shockharness: ignore[STATE001] reason="replaced whole under _allowed_routes_lock; readers see one frozenset"
# Each declared route object (kept alive, so its id stays its own) with its full template, with
# its router's prefix, by the object's id.
_template_by_route_id: Mapping[int, tuple[BaseRoute, str]] = {}  # shockharness: ignore[STATE001] reason="replaced whole under _allowed_routes_lock; readers see one mapping"
_allowed_routes_lock = threading.Lock()


def declared_routes() -> frozenset[str]:
    """Every route template the app declares, with the static files' and no route."""
    return _allowed_routes


def is_declared_route(value: str) -> bool:
    """Whether a route template is one the app declares (or the static files' or no route)."""
    return value in _allowed_routes


def _render_route(value: object) -> str | None:
    if value not in _allowed_routes:
        return None
    return str(value)


def _render_handler(value: object) -> str | None:
    if not isinstance(value, str) or value not in _allowed_handlers:
        return None
    return value


def _render_request_lines(value: object) -> str | None:
    """Requests under way, as (method, route) pairs."""
    if not isinstance(value, tuple):
        return None
    lines: list[str] = []
    for pair in value:
        if not isinstance(pair, tuple) or len(pair) != _REQUEST_LINE_PARTS:
            return None
        method, route = pair
        if _render_http_method(method) is None or _render_route(route) is None:
            return None
        lines.append(f"{method} {route}")
    return "[" + ", ".join(lines) + "]"


MILLISECONDS = FieldKind("milliseconds", _render_milliseconds_or_seconds)
SECONDS = FieldKind("seconds", _render_milliseconds_or_seconds)
COUNT = FieldKind("count", _render_count)
PERCENT = FieldKind("percent", _render_percent)
FLAG = FieldKind("flag", _render_flag)
REQUEST_ID = FieldKind("request id", _render_request_id)
HTTP_METHOD = FieldKind("HTTP method", _render_http_method)
HTTP_STATUS = FieldKind("HTTP status", _render_http_status)
ROUTE = FieldKind("route template", _render_route)
HANDLER = FieldKind("handler", _render_handler)
ERROR_TYPE = FieldKind("error type", _render_code_name)
CODE_NAMES = FieldKind("code names", _render_code_names)
ERRNO = FieldKind("errno", _render_errno)
RESPONSE_SIZE = FieldKind("response size", _render_response_size)
CODE_FRAMES = FieldKind("code frames", _render_code_frames)
THREAD_NAME = FieldKind("thread name", _render_thread_name)
REQUEST_LINES = FieldKind("requests", _render_request_lines)

_REQUEST_FIELDS = {
    "request_id": REQUEST_ID, "method": HTTP_METHOD, "route": ROUTE,
}
_ERROR_FIELDS = {"error_type": ERROR_TYPE, "errno": ERRNO, "frames": CODE_FRAMES}

# The allow-list: every event MetaList logs, with its fields in the order they are written.
EVENTS: Mapping[str, Mapping[str, FieldKind]] = {
    # Requests
    "request": {
        "status": HTTP_STATUS, "method": HTTP_METHOD, "route": ROUTE, "handler": HANDLER,
        "duration_ms": MILLISECONDS, "size": RESPONSE_SIZE, "request_id": REQUEST_ID,
    },
    "request.exception": {**_REQUEST_FIELDS, "duration_ms": MILLISECONDS, **_ERROR_FIELDS},
    "request.slow": {**_REQUEST_FIELDS, "seconds": SECONDS, "has_query": FLAG},
    # A request answered in 1 s or more, with how busy the computer and MetaList were (numbers
    # only, never a program's name; docs/ready-to-build/error-reports.md section 6a).
    "request.busy": {
        **_REQUEST_FIELDS, "status": HTTP_STATUS, "duration_ms": MILLISECONDS, "waited_ms": MILLISECONDS,
        "machine_cpu_percent": PERCENT, "machine_available_bytes": COUNT, "swap_used_bytes": COUNT,
        "metalist_cpu_percent": PERCENT, "metalist_memory_bytes": COUNT,
    },
    "request.active_during_stall": {**_REQUEST_FIELDS, "seconds": SECONDS, "has_query": FLAG},
    # Failures and the process's health
    "exception": {"context": _choice("exception context", EXCEPTION_CONTEXTS), **_ERROR_FIELDS},
    "library": {
        "logger": _choice("library", LIBRARY_LOGGER_PACKAGES | {OTHER_LIBRARY}),
        "error_type": ERROR_TYPE, "frames": CODE_FRAMES,
    },
    "asyncio.error_without_exception": {"context_keys": CODE_NAMES},
    "server": {"stage": _choice("server stage", SERVER_STAGES)},
    "diagnostics.enabled": {},
    "asyncio_diagnostics.enabled": {},
    "log.compacted": {"old_bytes": COUNT, "kept_bytes": COUNT},
    "loop.stall": {"state": _choice("stall state", LOOP_STALL_STATES), "seconds": SECONDS, "requests": REQUEST_LINES},
    "loop.unresponsive": {"seconds": SECONDS, "active_requests": COUNT},
    "thread.stack": {"thread": THREAD_NAME, "frames": CODE_FRAMES},
    "hydration.failed": {"error_type": ERROR_TYPE, "frames": CODE_FRAMES},
    "proxy.transport_failed": {
        "stage": _choice("proxy stage", PROXY_STAGES), "method": HTTP_METHOD, "error_type": ERROR_TYPE,
    },
    "database.rollback_fatal": {"database": _choice("database", DATABASES), "error_type": ERROR_TYPE, "frames": CODE_FRAMES},
    "sqlite.statement": {"statement": _choice("SQL verb", SQL_VERBS)},
    "namespace_guard.failed": {},
    "dev.database_switched": {"database": _choice("dev database", DEV_DATABASES)},
    "dev.notes_cleared": {},
    # Start-up and the note cache
    "startup.step": {"step": _choice("startup step", STARTUP_STEPS), "seconds": SECONDS},
    "startup.waiting_for_login": {},
    "startup.repaired_empty_notes": {"notes": COUNT},
    "cache.cleared": {},
    "cache.populate_start": {},
    "cache.populating": {"notes": COUNT},
    "cache.decrypt_progress": {"notes": COUNT, "batch_notes": COUNT, "batch_seconds": SECONDS, "total_seconds": SECONDS},
    "cache.decrypt_loop": {"notes": COUNT, "seconds": SECONDS},
    "cache.populated": {"notes": COUNT},
    "cache.html_cleaned": {"notes": COUNT},
    "tags.builtin_renamed": {"notes": COUNT, "searches": COUNT},
    # Search and the view
    "search.index.rebuild": {"elapsed_ms": MILLISECONDS, "notes": COUNT, "unique_tag_terms": COUNT, "revision": COUNT},
    "search.index.upsert": {"elapsed_ms": MILLISECONDS, "revision": COUNT},
    "search.index.bulk_update_tag_terms": {"elapsed_ms": MILLISECONDS, "revision": COUNT, "touched": COUNT, "updates": COUNT},
    "search.index.remove_many": {"elapsed_ms": MILLISECONDS, "notes": COUNT, "revision": COUNT},
    "search.query.cached": {"total_ms": MILLISECONDS, "revision": COUNT, "matched": COUNT},
    "search.query": {
        "parse_ms": MILLISECONDS, "candidate_ms": MILLISECONDS, "verify_ms": MILLISECONDS, "total_ms": MILLISECONDS,
        "candidates": COUNT, "verified": COUNT, "matched": COUNT, "required_tags": COUNT, "forbidden_tags": COUNT,
        "required_texts": COUNT, "forbidden_texts": COUNT, "or_clauses": COUNT, "revision": COUNT,
    },
    "notes.view_state": {"elapsed_ms": MILLISECONDS, "structure": COUNT, "payloads": COUNT, "roots": COUNT},
    # Undo
    "undo.reset": {},
    "undo.start": {"direction": _choice("undo direction", UNDO_DIRECTIONS), "history": COUNT, "redo": COUNT},
    "undo.pop": {
        "direction": _choice("undo direction", UNDO_DIRECTIONS), "op_type": _choice("undo op type", UNDO_OP_TYPES),
        "history": COUNT, "redo": COUNT,
    },
    "undo.finish": {
        "direction": _choice("undo direction", UNDO_DIRECTIONS), "op_type": _choice("undo op type", UNDO_OP_TYPES),
        "history": COUNT, "redo": COUNT,
    },
}

# Where the guard finds an event and its fields on a record.
_EVENT_KEY = "safe_log_event"
_FIELDS_KEY = "safe_log_fields"


def render_event(event: str, fields: Mapping[str, object]) -> str:
    """The event's log line, after checking it against the allow-list: throws UnsafeLogRecord
    for an unknown event, a missing or undeclared field, or a value outside its type. The error
    names the event and the field, never the value."""
    if not isinstance(event, str) or event not in EVENTS:
        raise UnsafeLogRecord("A log record is not an allow-listed MetaList event (app/services/safe_log.py EVENTS)")
    declared = EVENTS[event]
    if set(fields) != set(declared):
        missing = sorted(set(declared) - set(fields))
        undeclared = sorted(name for name in fields if name not in declared)
        raise UnsafeLogRecord(
            f"Log event {event} needs exactly its declared fields: missing {missing}, "
            f"{len(undeclared)} undeclared",
        )
    parts = [event]
    for name, kind in declared.items():
        rendered = kind.render(fields[name])
        if rendered is None:
            raise UnsafeLogRecord(f"Log event {event} field {name} is not a {kind.name}")
        parts.append(f"{name}={rendered}")
    return " ".join(parts)


def log_event(level: str, event: str, **fields: object) -> None:
    """Log one allow-listed event. Checked here and again by the guard every record passes."""
    if level not in _LEVELS:
        raise UnsafeLogRecord(f"Log level must be one of {sorted(_LEVELS)}")
    line = render_event(event, fields)
    logger.bind(**{_EVENT_KEY: event, _FIELDS_KEY: dict(fields)}).opt(depth=1).log(level, line)


def _require_safe_record(record: dict) -> None:
    """Loguru's patcher: runs in the logging thread before any sink, outside the sinks' error
    handling, so a record that fails the check raises where it was logged. The message every
    sink writes is the checked line, rebuilt from the typed fields."""
    extra = record["extra"]
    if _EVENT_KEY not in extra or _FIELDS_KEY not in extra:
        raise UnsafeLogRecord(
            f"A log record from {record['name']} is not an allow-listed MetaList event: "
            "log through app.services.safe_log.log_event",
        )
    if record["exception"] is not None:
        raise UnsafeLogRecord("A log record carries an exception: log its type and code frames as fields")
    record["message"] = render_event(extra[_EVENT_KEY], extra[_FIELDS_KEY])


def install_safe_log_guard() -> None:
    """Every loguru record in this process passes _require_safe_record before any sink."""
    logger.configure(patcher=_require_safe_record)


def allow_route_templates(routes: Sequence[BaseRoute]) -> None:
    """Adds the route templates and handler names the app declares to the only routes and
    handlers the log writes. Called once the app's routes are all in place (and again by a test
    that adds a route)."""
    global _allowed_routes
    global _allowed_handlers
    global _template_by_route_id

    with _allowed_routes_lock:
        templates = set(_allowed_routes)
        handlers = set(_allowed_handlers)
        template_by_route_id = dict(_template_by_route_id)
    for context in iter_route_contexts(routes):
        template = context.path
        if not isinstance(template, str) or not template.startswith("/"):
            raise TypeError(f"A declared route without a path: {type(context.original_route).__name__}")
        route_id = id(context.original_route)
        if route_id in template_by_route_id and template_by_route_id[route_id][1] != template:
            raise RuntimeError(f"One route is declared at two paths: {template_by_route_id[route_id][1]} and {template}")
        template_by_route_id[route_id] = (context.original_route, template)
        templates.add(template)
        if context.endpoint is not None:
            handlers.add(context.endpoint.__qualname__)
        elif isinstance(context.original_route, Mount):
            handlers.add(type(context.original_route.app).__name__)
    with _allowed_routes_lock:
        _allowed_routes = frozenset(templates)
        _allowed_handlers = frozenset(handlers)
        _template_by_route_id = template_by_route_id


def route_template(scope: Mapping[str, object]) -> str:
    """A request's route as the app declares it: the matched route's full template, the static
    files' one, or NO_ROUTE before routing has matched one. Never the path the browser sent."""
    path = scope["path"]
    if isinstance(path, str) and path.startswith("/static/"):
        return STATIC_ROUTE
    if "route" not in scope:
        return NO_ROUTE
    template_by_route_id = _template_by_route_id
    route = scope["route"]
    if id(route) not in template_by_route_id or template_by_route_id[id(route)][0] is not route:
        raise UnsafeLogRecord("A request matched a route the app had not declared to the log: call allow_route_templates")
    return template_by_route_id[id(route)][1]


def sql_verb(statement: str) -> str:
    """A SQL statement as the log writes it: its first keyword, never its text or values."""
    words = statement.split(maxsplit=1)
    if len(words) == 0 or words[0].upper() not in SQL_VERBS:
        return "OTHER"
    return words[0].upper()


def method_for_log(method: str) -> str:
    """An HTTP method as the log writes it: a method outside the standard ones is OTHER."""
    if method in _HTTP_METHODS:
        return method
    return "OTHER"


def _code_roots() -> tuple[tuple[Path, str], ...]:
    """Where code lives, most specific first, with the prefix a frame there is written with.
    The virtual environment sits inside the repository, so libraries come first."""
    paths = sysconfig.get_paths()
    # app/services/safe_log.py: the repository is three folders up.
    repository = Path(__file__).resolve().parent.parent.parent
    roots: list[tuple[Path, str]] = []
    for key, label in (("purelib", "site-packages"), ("platlib", "site-packages"), ("stdlib", "lib"), ("platstdlib", "lib")):
        roots.append((Path(paths[key]).resolve(), label))
    roots.append((repository, ""))
    return tuple(roots)


_CODE_ROOTS = _code_roots()


def _safe_frame(filename: str, line_number: int | None, function: str) -> str:
    path = Path(filename)
    if not path.is_absolute():
        return EXTERNAL_FRAME
    resolved = path.resolve()
    for root, label in _CODE_ROOTS:
        if not resolved.is_relative_to(root):
            continue
        relative = resolved.relative_to(root).as_posix()
        if label != "":
            relative = f"{label}/{relative}"
        frame = f"{relative}:{line_number}:{function}"
        if _CODE_FRAME.fullmatch(frame) is None:
            return EXTERNAL_FRAME
        return frame
    return EXTERNAL_FRAME


def safe_code_frames(exception_traceback: TracebackType | None) -> tuple[str, ...]:
    """A traceback's code locations, relative to MetaList, its libraries or Python: no message,
    no values, no folder outside the code (a home folder's name)."""
    if exception_traceback is None:
        return ()
    return tuple(
        _safe_frame(frame.filename, frame.lineno, frame.name)
        for frame in traceback.extract_tb(exception_traceback)
    )


def safe_stack_frames(frame: FrameType) -> tuple[str, ...]:
    """A running stack's code locations, oldest first, written as safe_code_frames writes them."""
    return tuple(
        _safe_frame(summary.filename, summary.lineno, summary.name)
        for summary in traceback.extract_stack(frame)
    )


def safe_thread_name(name: str) -> str:
    """A thread's name as the log writes it; a name outside the usual shape is "other"."""
    if _THREAD_NAME.fullmatch(name) is None:
        return OTHER_LIBRARY
    return name


def _library_of(logger_name: str) -> str:
    package = logger_name.split(".")[0]
    if package in LIBRARY_LOGGER_PACKAGES:
        return package
    return OTHER_LIBRARY


def _uvicorn_stage(record: logging.LogRecord) -> str | None:
    """The lifecycle stage a uvicorn record announces, from its message template; None for any
    other record."""
    if record.name.split(".")[0] != "uvicorn" or not isinstance(record.msg, str):
        return None
    if record.msg in _UVICORN_STAGE_BY_TEMPLATE:
        return _UVICORN_STAGE_BY_TEMPLATE[record.msg]
    if record.msg.startswith(_UVICORN_LISTENING_PREFIX):
        return "listening"
    return None


def forward_standard_log_record(record: logging.LogRecord) -> None:
    """A record from the logging module. MetaList's own code never logs that way (it throws);
    uvicorn's lifecycle lines become a `server` event; any other library record below WARNING
    is dropped (httpx's lines name every URL it fetches); a library's warning or error keeps its
    package, level, error type and code frames, never its message."""
    if record.name.split(".")[0] in _METALIST_LOGGER_ROOTS:
        raise UnsafeLogRecord(
            f"MetaList module {record.name} logs through the logging module: use app.services.safe_log.log_event",
        )
    stage = _uvicorn_stage(record)
    if stage is not None:
        log_event("INFO", "server", stage=stage)
        return
    if record.levelno < logging.WARNING:
        return
    error_type = NONE_VALUE
    frames: tuple[str, ...] = ()
    if record.exc_info is not None:
        _error_class, error, error_traceback = record.exc_info
        if error is not None:
            error_type = type(error).__name__
            frames = safe_code_frames(error_traceback)
    level = "WARNING"
    if record.levelno >= logging.CRITICAL:
        level = "CRITICAL"
    elif record.levelno >= logging.ERROR:
        level = "ERROR"
    log_event(level, "library", logger=_library_of(record.name), error_type=error_type, frames=frames)
