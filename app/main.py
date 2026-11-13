from http import HTTPStatus
from starlette.concurrency import run_in_threadpool
from fastapi import FastAPI, Request, Depends
from app.db.files_sql import AttachmentSizeExceeded
from app.services import import_uploads
from app.services.file_storage import FileNotEditable, FilePreviewMissing, FileRevisionConflict, InvalidFileContent
from app.services.file_edit_sessions import FileEditSessionMissing
from app.services.hierarchy import HierarchyError
from app.services.sync import ClipboardCapacityError
from app.services.shell_session_service import shell_session_service, ShellCapacityError, ShellRunNotFound
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.exceptions import RequestValidationError
from pathlib import Path
from typing import Annotated
import json
import secrets
from app.api.upload_limits import UploadLimitMiddleware
from app.presentation.templates import get_templates
from .startup_environment import is_development_environment
from .api import dev
from .api.middleware.auth import AuthMiddleware
from app.config import ACTIVE_NAMESPACE, VERSION
from .db.session import begin_writer, enable_read_guard
from .db.schema import initialize_schema
from .db.migrations import CURRENT_DATABASE_VERSION
from .db.version import require_database_not_newer
from .db.migrations import read_database_version
from .db.migrations import run_database_migrations
from .db.notes_sql import clear_encryption_metadata_for_empty_notes
from .db.settings_sql import fetch_settings, insert_default_settings
from .api.deps import get_db
from .services.content_cache import populate_cache_from_db
from .process_memory import release_freed_memory
from .services.backup_service import back_up_before_passwordless_upgrade
from .services.backup_service import trim_safety_backups_once_vault_is_current
from .services.file_storage import bootstrap_file_registry, sweep_blob_leftovers
from .services.auth import AuthService
from .services.note_store import store as note_store
from app.services import auth_cache_state
from app.services.integrity import assert_linked_list_integrity
from app.services.tag_ontology import OntologyParseError
from app.services.ontology_rules_store import bootstrap_ontology_rules_store
from app.services.ai_chat import ai_chat_store
from app.services.tab_state import tab_state_store
from app.services.link_titles import link_title_store
from app.services.link_row_pruning import start_link_row_pruning
from app.services.reminders import reminder_store
from app.services.search_history import search_history_store
from app.services.runtime_hardening import apply_runtime_hardening
from app.security.encryption import set_encryption_required
from app.security.http_headers import apply_security_headers
from app.security.http_headers import own_host_on_any_port
from app.security.http_error_diagnostics import describe_server_exception
from app.security.request_boundary import RequestBoundaryMiddleware
from app.security.request_boundary import resolve_allowed_request_hosts
from app.security.request_hosts import binds_to_every_interface
from app.server_runtime import chosen_bind_host
from app.security.validation_errors import summarize_validation_errors
from app.server_runtime import resolve_https_redirect_url
from app.server_runtime import resolve_request_host_for_https_redirect
from app.server_runtime import validate_namespace
from app.services.exception_capture import CapturedExceptionContext
from app.services.namespace_deletion_jobs import load_namespace_deletion_job
from app.services.namespace_rename_jobs import load_namespace_rename_job
from app.services.namespace_switcher import build_namespace_catalog
from app.services.namespace_switcher import NamespaceOpenResult
from app.services.namespace_switcher import open_or_launch_namespace
from app.services.namespace_runtime_guard import start_namespace_runtime_guard
from app.services.diagnostics import configure_process_diagnostics
from app.services.diagnostics import log_unexpected_exception
from app.services.diagnostics import start_asyncio_diagnostics
from app.services.diagnostics import track_request
from app.services import safe_log
from app.services import request_history
from app.api.request_auth import clear_auth_cookie
from app.presentation.login_page import login_is_certainly_needed
from app.api.routes.notes import router as api2_router
from app.api.routes.auth import router as api2_auth_router
from app.api.routes.app_updates import router as api2_app_updates_router
from app.api.routes.files import router as api2_files_router
from app.api.routes.ontology import router as api2_ontology_router
from app.api.routes.backups import router as api2_backup_router
from app.api.routes.reminders import router as api2_reminders_router
from app.api.routes.remote_images import router as api2_remote_images_router
from app.api.routes.imports import router as api2_imports_router
from app.api.routes.virtual_folders import router as api2_virtual_folders_router
from app.api.routes.background_work import router as api2_background_work_router
from app.api.routes.problem_reports import router as api2_problem_reports_router
from app.api.routes.ai import router as api2_ai_router
from app.api.routes.test import router as api2_test_router  # shockharness: ignore[STUB002] reason="mounted only when TEST_MODE is on, and the endpoint asserts it too"
from app.api.transactions import transactional_route
from app.config import API_PREFIX, TEST_MODE, V1_API_PREFIX
from app.services.agent.scripted_inference import scripted_ai_script_path
from app.services.native_folder_picker import answered_folder_pick
from .models.database import SafeSession
from loguru import logger
import io
import logging
import time
import sys
import types
import uuid
from app.utils.sent_fields import sent_or_none
from app.utils.time_units import MS_PER_SECOND
from app.services.static_files_version import STATIC_DIRECTORY, STATIC_URL_PREFIX, MetaListStaticFiles, static_files_version
from fastapi.middleware.gzip import GZipMiddleware
import os
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit
from app.services.input_errors import InputRejected, NamespaceInputRejected

# Responses smaller than this go out uncompressed.
_GZIP_MINIMUM_RESPONSE_BYTES = 1000
# Hex digits of a random UUID kept as the short id that ties a request's log lines together.
_REQUEST_ID_HEX_LENGTH = 8
# Every answer names its request id in this header, so a failure the browser sees (a 409, a 500)
# matches its line in the server log.
REQUEST_ID_HEADER = "X-Request-Id"
# A static file answered successfully is not logged unless it took this long (21,110 of 21,990
# lines of one log were static loads); a failed one always is.
_SLOW_STATIC_LOAD_MS = request_history.SLOW_REQUEST_MS
_CSP_NONCE_RANDOM_BYTES = 24
# URL-safe base64 of the random bytes, without padding.
_CSP_NONCE_TEXT_LENGTH = 32

# The log is UTF-8 on every OS, as the launcher reads child logs: Windows writes a pipe
# or a file in its code page (cp1252), which has no ⇒ or ⇐, and every request's line
# failed to write there (2026-10-21). A character UTF-8 cannot carry is escaped.
# stderr too: the launcher writes both into one log file.
for _console_stream in (sys.stdout, sys.stderr):
    if not isinstance(_console_stream, io.TextIOWrapper):
        raise RuntimeError(f"MetaList logs to text streams, not {type(_console_stream).__name__}")
    _console_stream.reconfigure(encoding="utf-8", errors="backslashreplace")
# One plain log, before and after login, of allow-listed events only (app/services/safe_log.py):
# every record is checked before any sink writes it, and anything else throws.
safe_log.install_safe_log_guard()
logger.remove()
logger.add(
    sys.stdout,
    level="INFO",
    backtrace=False,
    diagnose=False,
    format=safe_log.SAFE_LOG_FORMAT,
)


class InterceptHandler(logging.Handler):
    """Libraries' records from the logging module: never written as they are
    (safe_log.forward_standard_log_record)."""

    def emit(self, record):
        safe_log.forward_standard_log_record(record)


logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)


def _resolve_diagnostics_namespace(*, namespace: str | None) -> str:
    if namespace is None:
        return "default"
    if namespace == "":
        raise RuntimeError("Active namespace must not be empty")
    return namespace


# A scripted AI (scripted_inference.py) and a folder dialog answered for a test
# (native_folder_picker.py) are refused outside a test server before anything starts.
scripted_ai_script_path(environ=os.environ)
answered_folder_pick(environ=os.environ)

# Link titles and icons no note links to go, each time the notes have been loaded.
auth_cache_state.after_page_ready(start_link_row_pruning)

configure_process_diagnostics(
    namespace=_resolve_diagnostics_namespace(namespace=ACTIVE_NAMESPACE),
    enabled=not TEST_MODE,
)

app = FastAPI()
app.add_middleware(UploadLimitMiddleware)


@app.on_event("startup")
async def discard_left_import_uploads():
    # A dropped folder's upload interrupted by a restart starts over (import_uploads.py).
    import_uploads.discard_every_upload()


@app.on_event("startup")
async def start_diagnostics_watchdogs():
    start_asyncio_diagnostics(enabled=not TEST_MODE)
    # The first CPU reading only starts the measure; slow requests read the ones after it.
    request_history.prime_busy_numbers()
    start_namespace_runtime_guard(
        namespace=ACTIVE_NAMESPACE,
        enabled=not TEST_MODE,
    )

@app.exception_handler(RequestValidationError)
async def request_validation_error(request: Request, exc: RequestValidationError):
    # External input errors are not internal programming failures.
    return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, content={"detail": summarize_validation_errors(exc.errors())})


@app.exception_handler(InputRejected)
async def handle_input_rejected(request: Request, exc: InputRejected):
    # Expected, validated user-input failures (e.g. a search that does not
    # parse): a polite 400 the browser shows as a warning, never a 500.
    return JSONResponse(status_code=HTTPStatus.BAD_REQUEST, content={"detail": str(exc), "inputRejected": True})


@app.exception_handler(OntologyParseError)
async def handle_ontology_parse_error(request: Request, exc: OntologyParseError):
    return JSONResponse(status_code=HTTPStatus.BAD_REQUEST, content={"detail": str(exc)})


def _diagnostic_request_id(request: Request) -> str:
    """The id log_requests gave the request; "" for one that failed before reaching it."""
    if "state" not in request.scope or "diagnostic_request_id" not in request.scope["state"]:
        return ""
    return request.scope["state"]["diagnostic_request_id"]


def _handler_name(request: Request) -> str:
    """What answered a request, for its log line: routing sets it while the request
    runs. A route's endpoint is a function (or an endpoint class); a mounted app
    (the static files) is an object, named by its class; a path no route matches
    has none."""
    if "endpoint" not in request.scope:
        return "(no route)"
    endpoint = request.scope["endpoint"]
    if isinstance(endpoint, (types.FunctionType, types.MethodType, type)):
        return endpoint.__qualname__
    return type(endpoint).__name__


def _header_for_log(headers, name: str) -> str:
    """A header as the request log shows it: "-" when the request or response has none."""
    if name not in headers:  # shockharness: ignore[DEF002] reason="the request log shows a dash for a header the request or response does not have"
        return "-"
    return headers[name]


def _page_param(request: Request, name: str) -> str | None:
    """A query parameter of a page opened from a link; None when missing or blank,
    which the page answers with a plain 400."""
    if name not in request.query_params or request.query_params[name].strip() == "":
        return None
    return request.query_params[name]


@app.exception_handler(Exception)
async def handle_unexpected_server_error(request: Request, exc: Exception):
    request_id = _diagnostic_request_id(request)
    headers = {"Cache-Control": "no-store, private", "X-Content-Type-Options": "nosniff"}
    diagnostic = describe_server_exception(exc)
    if request_id:
        _remember_answered_request(
            request=request, route=safe_log.route_template(request.scope),
            status=HTTPStatus.INTERNAL_SERVER_ERROR,
            duration_ms=(time.perf_counter() - request.state.diagnostic_started_at) * MS_PER_SECOND,
            error_type=diagnostic["errorType"], code_location=diagnostic["codeLocation"],
        )
        # log_requests' tracking has logged the failure with its request and route.
        diagnostic["requestId"] = request_id
        headers[REQUEST_ID_HEADER] = request_id
    else:
        log_unexpected_exception(context="HTTP request", exception=exc, level="ERROR")
    return JSONResponse(
        status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
        content={
            "detail": "Internal server error",
            "diagnostic": diagnostic,
        },
        headers=headers,
    )

_startup_timing_enabled = True


def _log_startup_step(step: str, elapsed: float) -> None:
    if not _startup_timing_enabled:
        return
    safe_log.log_event("INFO", "startup.step", step=step, seconds=elapsed)


overall_start = time.perf_counter()

hardening_start = time.perf_counter()
apply_runtime_hardening()
_log_startup_step("runtime hardening checks", time.perf_counter() - hardening_start)

schema_start = time.perf_counter()
passwordless_upgrade_backed_up = False
if not SafeSession._use_memory:
    # Before anything writes to it: an older MetaList would set up its own tables in a newer vault.
    require_database_not_newer(SafeSession._db_path)
    passwordless_upgrade_backed_up = back_up_before_passwordless_upgrade(SafeSession._db_path)
with begin_writer() as connection:
    initialize_schema(connection.raw_connection)
    settings = fetch_settings(connection)
    if not settings:
        insert_default_settings(connection)
        settings = fetch_settings(connection)
    if settings is None:
        raise RuntimeError("App settings missing after schema initialization")
    database_version = read_database_version(connection.raw_connection)
    if database_version > CURRENT_DATABASE_VERSION:
        raise RuntimeError(
            f"Database version {database_version} is newer than supported version "
            f"{CURRENT_DATABASE_VERSION}"
        )
    if not bool(settings["encryption_enabled"]):
        run_database_migrations(
            connection=connection.raw_connection,
            encryption_enabled=False,
            encryption_service=None,
        )
        database_version = CURRENT_DATABASE_VERSION
    bootstrap_ontology_rules_store(connection=connection)
    tab_state_store.bootstrap(connection=connection)
    link_title_store.bootstrap(connection=connection)
    reminder_store.bootstrap(connection=connection)
    # A vault with a password upgrades at unlock: until then its tables may be older.
    if not bool(settings["encryption_enabled"]) or database_version >= CURRENT_DATABASE_VERSION:
        search_history_store.bootstrap(connection=connection)
        ai_chat_store.bootstrap(connection=connection)
    else:
        search_history_store.reset()
        ai_chat_store.reset()
if passwordless_upgrade_backed_up:
    # The upgrade above has committed: keep the newest safety backups, as after an unlock's.
    trim_safety_backups_once_vault_is_current(SafeSession._db_path)
_log_startup_step("schema + settings bootstrap", time.perf_counter() - schema_start)

startup_has_password = False
encryption_enabled = False
if settings:
    encryption_enabled = bool(settings["encryption_enabled"])
    startup_has_password = encryption_enabled
set_encryption_required(encryption_enabled)

file_registry_start = time.perf_counter()
bootstrap_file_registry()
sweep_blob_leftovers()
_log_startup_step("file registry bootstrap", time.perf_counter() - file_registry_start)



def _resolve_page_title(*, base_title: str) -> str:
    if ACTIVE_NAMESPACE in {None, "default"}:
        return base_title
    return f"{base_title} [{ACTIVE_NAMESPACE}]"

integrity_start = time.perf_counter()
integrity_session = SafeSession()
try:
    assert_linked_list_integrity(integrity_session, "startup")
    integrity_session.commit()
finally:
    integrity_session.close()
_log_startup_step("linked list integrity check", time.perf_counter() - integrity_start)

if startup_has_password:
    safe_log.log_event("INFO", "startup.waiting_for_login")
    auth_cache_state.reset_cache_state()
    guard_start = time.perf_counter()
    enable_read_guard()
    _log_startup_step("read guard enable", time.perf_counter() - guard_start)
    _log_startup_step("total startup", time.perf_counter() - overall_start)
else:
    # Populate content cache on startup
    repair_start = time.perf_counter()
    with begin_writer() as connection:
        repaired = clear_encryption_metadata_for_empty_notes(connection)
    if repaired:
        safe_log.log_event("INFO", "startup.repaired_empty_notes", notes=repaired)
    _log_startup_step(
        "empty-note encryption metadata repair",
        time.perf_counter() - repair_start,
    )

    cache_start = time.perf_counter()
    cache_session = SafeSession()
    try:
        prefetched_rows = populate_cache_from_db(cache_session, saved_searches=tab_state_store)
        cache_session.commit()
    finally:
        cache_session.close()
    _log_startup_step("cache population", time.perf_counter() - cache_start)

    store_start = time.perf_counter()
    note_store.load_from_db(None, prefetched_rows=prefetched_rows)
    _log_startup_step("note store hydration", time.perf_counter() - store_start)
    # Loading made and dropped many short-lived objects: hand their memory back.
    del prefetched_rows
    release_start = time.perf_counter()
    release_freed_memory()
    _log_startup_step("freed memory release", time.perf_counter() - release_start)
    auth_cache_state.mark_cache_ready()

    guard_start = time.perf_counter()
    enable_read_guard()
    _log_startup_step("read guard enable", time.perf_counter() - guard_start)

    _log_startup_step("total startup", time.perf_counter() - overall_start)


# Add GZip compression
app.add_middleware(GZipMiddleware, minimum_size=_GZIP_MINIMUM_RESPONSE_BYTES)

# Add authentication middleware
app.add_middleware(AuthMiddleware)

app.mount(
    "/static",
    MetaListStaticFiles(directory=str(STATIC_DIRECTORY), version=static_files_version),
    name="static",
)

templates = get_templates(
    template_directory=Path(__file__).resolve().parent / "templates",
)
_bind_host = chosen_bind_host(environ=os.environ)
allowed_request_hosts = resolve_allowed_request_hosts(environ=os.environ, bind_host=_bind_host)

# v2 routers mounted under configured API_PREFIX
app.include_router(api2_router, prefix=API_PREFIX, tags=["api2"]) 
app.include_router(api2_auth_router, prefix=API_PREFIX)
app.include_router(api2_app_updates_router, prefix=API_PREFIX)
app.include_router(api2_backup_router, prefix=API_PREFIX)
app.include_router(api2_files_router, prefix=API_PREFIX)
app.include_router(api2_ontology_router, prefix=API_PREFIX)
app.include_router(api2_reminders_router, prefix=API_PREFIX)
app.include_router(api2_remote_images_router, prefix=API_PREFIX)
app.include_router(api2_imports_router, prefix=API_PREFIX)
app.include_router(api2_virtual_folders_router, prefix=API_PREFIX)
app.include_router(api2_background_work_router, prefix=API_PREFIX)
app.include_router(api2_problem_reports_router, prefix=API_PREFIX)
app.include_router(api2_ai_router, prefix=API_PREFIX)
if TEST_MODE:
    app.include_router(dev.router, prefix="/dev", tags=["dev"])
    app.include_router(api2_test_router, prefix=API_PREFIX, tags=["api2-test"])

# Retired v1 requests are external compatibility errors.
@app.api_route(f"{V1_API_PREFIX}/{{rest_of_path:path}}", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
@transactional_route
async def block_v1_any(rest_of_path: str):
    return JSONResponse(status_code=HTTPStatus.GONE, content={"detail": "Use the current API version"})

@app.api_route(f"{V1_API_PREFIX}", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
@transactional_route
async def block_v1_root():
    return JSONResponse(status_code=HTTPStatus.GONE, content={"detail": "Use the current API version"})


@app.middleware("http")
async def redirect_remote_http_to_https(request: Request, call_next):
    request_host = resolve_request_host_for_https_redirect(
        # HTTP/1.0 requests may have no Host header.
        host_header=sent_or_none(request.headers, "host"),
        fallback_host=request.url.hostname,
    )
    redirect_url = resolve_https_redirect_url(
        environ=os.environ,
        request_scheme=request.url.scheme,
        request_host=request_host,
        request_path=request.url.path,
        request_query=request.url.query,
    )
    if redirect_url is not None:
        return RedirectResponse(url=redirect_url, status_code=HTTPStatus.TEMPORARY_REDIRECT)
    return await call_next(request)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """One line per answered request: its route as the app declares it (never the path or query
    the browser sent), status, handler, time and size. Every answer names its request id in a
    header. Polls, locks and successful static loads are not logged."""
    request_id = uuid.uuid4().hex[:_REQUEST_ID_HEX_LENGTH]
    request.state.diagnostic_request_id = request_id

    path = request.url.path
    is_noisy_poll = request.method == "GET" and path == f"{API_PREFIX}/auth/status"
    is_noisy_lock = request.method == "POST" and path in {
        f"{API_PREFIX}/notes/acquire-lock",
        f"{API_PREFIX}/notes/release-lock",
    }

    start = time.perf_counter()
    # How long it waits for its turn to change the vault (app/api/transactions.py), and when it
    # started, for the 500 handler too.
    request.state.diagnostic_wait = request_history.begin_request_wait()
    request.state.diagnostic_started_at = start
    request_tracker = track_request(
        request_id=request_id,
        method=safe_log.method_for_log(request.method),
        scope=request.scope,
        has_query=request.url.query != "",
        started_at=start,
    )
    with request_tracker:
        response = await call_next(request)
    response.headers[REQUEST_ID_HEADER] = request_id

    duration_ms = (time.perf_counter() - start) * MS_PER_SECOND
    route = safe_log.route_template(request.scope)
    is_quiet_static_load = (
        route == safe_log.STATIC_ROUTE
        and response.status_code < HTTPStatus.BAD_REQUEST
        and duration_ms < _SLOW_STATIC_LOAD_MS
    )
    if not (is_noisy_poll or is_noisy_lock or is_quiet_static_load):
        safe_log.log_event(
            "INFO", "request",
            status=response.status_code,
            method=safe_log.method_for_log(request.method),
            route=route,
            handler=_handler_name(request),
            duration_ms=duration_ms,
            size=_header_for_log(response.headers, "content-length"),
            request_id=request_id,
        )
    _remember_answered_request(
        request=request, route=route, status=response.status_code, duration_ms=duration_ms,
        error_type=request_history.NO_ERROR, code_location=request_history.NO_ERROR,
    )
    return response


def _remember_answered_request(
    *, request: Request, route: str, status: int, duration_ms: float, error_type: str, code_location: str,
) -> None:
    """Keeps the answered request in memory for problem reports, and for a slow one (1 s or
    more) logs and keeps how busy the computer and MetaList were (app/services/request_history.py)."""
    request_id = request.state.diagnostic_request_id
    method = safe_log.method_for_log(request.method)
    waited_ms = request.state.diagnostic_wait.waited_seconds * MS_PER_SECOND
    answered_at = request_history.now()
    request_history.REQUEST_HISTORY.record_answered(request_history.AnsweredRequest(
        request_id=request_id, method=method, route=route, status=status, duration_ms=duration_ms,
        waited_ms=waited_ms, error_type=error_type, code_location=code_location, answered_at=answered_at,
    ))
    if duration_ms < request_history.SLOW_REQUEST_MS:
        return
    busy = request_history.BUSY_READER.read()
    safe_log.log_event(
        "WARNING", "request.busy",
        request_id=request_id, method=method, route=route, status=status,
        duration_ms=duration_ms, waited_ms=waited_ms,
        machine_cpu_percent=busy.machine_cpu_percent,
        machine_available_bytes=busy.machine_available_bytes,
        swap_used_bytes=busy.swap_used_bytes,
        metalist_cpu_percent=busy.metalist_cpu_percent,
        metalist_memory_bytes=busy.metalist_memory_bytes,
    )
    request_history.REQUEST_HISTORY.record_slow(request_history.SlowRequest(
        request_id=request_id, method=method, route=route, status=status, duration_ms=duration_ms,
        waited_ms=waited_ms, busy=busy, answered_at=answered_at,
    ))


app.add_middleware(
    RequestBoundaryMiddleware,
    allowed_hosts=allowed_request_hosts,
    accepts_own_addresses=binds_to_every_interface(bind_host=_bind_host),
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    nonce = secrets.token_urlsafe(_CSP_NONCE_RANDOM_BYTES)
    if len(nonce) != _CSP_NONCE_TEXT_LENGTH:
        raise RuntimeError("Generated CSP nonce has unexpected length")
    request.state.csp_nonce = nonce
    response = await call_next(request)
    apply_security_headers(
        response=response, nonce=nonce, is_static_file=request.url.path.startswith(STATIC_URL_PREFIX),
        extra_connect_sources=own_host_on_any_port(scheme=request.url.scheme, hostname=request.url.hostname),
    )
    return response

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, db: Annotated[SafeSession, Depends(get_db)]):
    template = templates.get_template("index.html")

    auth = AuthService(db)
    needs_auth = auth.has_password()

    if needs_auth:
        return template.render(
            request=request,
            version=VERSION,
            asset_version=static_files_version.for_page(),
            page_title=_resolve_page_title(base_title="MetaList"),
            needs_auth=True,
            shows_login_at_once=login_is_certainly_needed(request),
            shows_ai_cost_estimate=is_development_environment(),
            vault_name=ACTIVE_NAMESPACE,
        )
    return template.render(
        request=request,
        notes=[],
        version=VERSION,
        asset_version=static_files_version.for_page(),
        page_title=_resolve_page_title(base_title="MetaList"),
        needs_auth=False,
        shows_login_at_once=False,
        shows_ai_cost_estimate=is_development_environment(),
        vault_name=ACTIVE_NAMESPACE,
    )



@app.get("/maintenance", response_class=HTMLResponse)
async def maintenance_page(request: Request):
    """Maintenance mode page shown during bulk operations."""
    template = templates.get_template("maintenance.html")
    return template.render(
        request=request,
        version=VERSION,
        asset_version=static_files_version.for_page(),
        page_title=_resolve_page_title(base_title="MetaList - Processing"),
    )


def _build_namespace_deleted_links(*, job_id: str, redirect_namespace: str) -> list[dict[str, str]]:
    normalized_redirect_namespace = validate_namespace(namespace=redirect_namespace)
    query = urlencode({"job": job_id, "namespace": normalized_redirect_namespace})
    return [
        {
            "namespace": normalized_redirect_namespace,
            "label": normalized_redirect_namespace,
            "meta": "Selected destination",
            "href": f"/namespace-deleted/open?{query}",
        }
    ]


def _resolve_catalog_profile(*, namespace: str) -> tuple[int, int | None]:
    catalog = build_namespace_catalog(
        environ=os.environ,
        current_namespace=ACTIVE_NAMESPACE,
    )
    raw_namespaces = catalog["namespaces"]
    if not isinstance(raw_namespaces, list):
        raise RuntimeError("Namespace catalog missing namespaces")
    for entry in raw_namespaces:
        if not isinstance(entry, dict):
            raise RuntimeError("Namespace catalog entry must be an object")
        if entry["namespace"] != namespace:
            continue
        profile = entry["default_profile"]
        if not isinstance(profile, dict):
            raise RuntimeError(f"Namespace {namespace} is missing default profile")
        port = profile["port"]
        https_port = profile["https_port"]
        if not isinstance(port, int):
            raise RuntimeError(f"Namespace {namespace} profile missing port")
        if https_port is not None and not isinstance(https_port, int):
            raise RuntimeError(f"Namespace {namespace} profile has invalid https_port")
        return port, https_port
    raise RuntimeError(f"Unknown namespace: {namespace}")


def _build_force_reauth_url(*, url: str) -> str:
    if not isinstance(url, str) or url == "":
        raise TypeError("url must be a non-empty string")
    parsed = urlsplit(url)
    path = parsed.path
    if path == "":
        path = "/"
    query_items = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if name != "force_reauth"
    ]
    query_items.append(("force_reauth", "1"))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            path,
            urlencode(query_items),
            parsed.fragment,
        )
    )


@app.get("/namespace-deleted", response_class=HTMLResponse)
async def namespace_deleted_page(request: Request):
    job_id = _page_param(request, "job")
    if job_id is None:
        return HTMLResponse("Missing vault deletion job", status_code=HTTPStatus.BAD_REQUEST)
    job_record_capture = CapturedExceptionContext(NamespaceInputRejected, FileNotFoundError, boundary='app/main.py:namespace_deleted_page:job_record_capture')
    job_record: dict[str, object] | None = None
    with job_record_capture:
        job_record = load_namespace_deletion_job(job_id=job_id)
    if job_record_capture.captured_exception is not None:
        exc = job_record_capture.captured_exception
        return HTMLResponse(str(exc), status_code=HTTPStatus.BAD_REQUEST)
    if job_record is None:
        return HTMLResponse(f"Vault deletion job not found: {job_id}", status_code=HTTPStatus.NOT_FOUND)

    template = templates.get_template("namespace_deleted.html")
    namespace_links = _build_namespace_deleted_links(
        job_id=job_record["job_id"],
        redirect_namespace=job_record["redirect_namespace"],
    )
    page_state = json.dumps(
        {
            "jobId": job_record["job_id"],
            "deletedNamespace": job_record["deleted_namespace"],
            "initialStatus": job_record["status"],
            "initialError": job_record["error"],
            "redirectNamespace": job_record["redirect_namespace"],
        }
    )
    return template.render(
        request=request,
        version=VERSION,
        asset_version=static_files_version.for_page(),
        page_title="MetaList - Vault Deleted",
        deleted_namespace=job_record["deleted_namespace"],
        namespace_links=namespace_links,
        page_state_json=page_state,
    )



def _open_catalog_namespace(*, namespace: str) -> NamespaceOpenResult:
    port, https_port = _resolve_catalog_profile(namespace=namespace)
    return open_or_launch_namespace(
        environ=os.environ,
        current_namespace=ACTIVE_NAMESPACE,
        namespace=namespace,
        port=port,
        https_port=https_port,
    )


@app.get("/namespace-deleted/open")
async def namespace_deleted_open_page(request: Request):
    job_id = _page_param(request, "job")
    if job_id is None:
        return HTMLResponse("Missing vault deletion job", status_code=HTTPStatus.BAD_REQUEST)
    namespace = _page_param(request, "namespace")
    if namespace is None:
        return HTMLResponse("Missing vault", status_code=HTTPStatus.BAD_REQUEST)
    job_record_capture = CapturedExceptionContext(NamespaceInputRejected, FileNotFoundError, boundary='app/main.py:namespace_deleted_open_page:job_record_capture')
    job_record: dict[str, object] | None = None
    with job_record_capture:
        job_record = load_namespace_deletion_job(job_id=job_id)
    if job_record_capture.captured_exception is not None:
        exc = job_record_capture.captured_exception
        return HTMLResponse(str(exc), status_code=HTTPStatus.BAD_REQUEST)
    if job_record is None:
        return HTMLResponse(f"Vault deletion job not found: {job_id}", status_code=HTTPStatus.NOT_FOUND)
    if job_record["status"] == "pending":
        return HTMLResponse("Vault deletion is still in progress", status_code=HTTPStatus.CONFLICT)
    if (
        namespace == job_record["deleted_namespace"]
        and namespace != job_record["redirect_namespace"]
    ):
        return HTMLResponse("Deleted vault is unavailable", status_code=HTTPStatus.BAD_REQUEST)

    launch_capture = CapturedExceptionContext(NamespaceInputRejected, FileNotFoundError, boundary='app/main.py:namespace_deleted_open_page:launch_capture')
    result = None
    with launch_capture:
        result = _open_catalog_namespace(namespace=namespace)
    if launch_capture.captured_exception is not None:
        exc = launch_capture.captured_exception
        return HTMLResponse(str(exc), status_code=HTTPStatus.BAD_REQUEST)
    if result is None:
        raise RuntimeError("Namespace launch did not return a result")
    response = RedirectResponse(url=_build_force_reauth_url(url=result.url), status_code=HTTPStatus.TEMPORARY_REDIRECT)
    clear_auth_cookie(response=response)
    return response


@app.get("/namespace-renamed", response_class=HTMLResponse)
async def namespace_renamed_page(request: Request):
    job_id = _page_param(request, "job")
    if job_id is None:
        return HTMLResponse("Missing vault rename job", status_code=HTTPStatus.BAD_REQUEST)
    job_record_capture = CapturedExceptionContext(NamespaceInputRejected, FileNotFoundError, boundary='app/main.py:namespace_renamed_page:job_record_capture')
    job_record: dict[str, object] | None = None
    with job_record_capture:
        job_record = load_namespace_rename_job(job_id=job_id)
    if job_record_capture.captured_exception is not None:
        exc = job_record_capture.captured_exception
        return HTMLResponse(str(exc), status_code=HTTPStatus.BAD_REQUEST)
    if job_record is None:
        return HTMLResponse(f"Vault rename job not found: {job_id}", status_code=HTTPStatus.NOT_FOUND)

    page_state = json.dumps(
        {
            "jobId": job_record["job_id"],
            "sourceNamespace": job_record["source_namespace"],
            "targetNamespace": job_record["target_namespace"],
            "initialStatus": job_record["status"],
            "initialError": job_record["error"],
        }
    )
    template = templates.get_template("namespace_renamed.html")
    return template.render(
        request=request,
        version=VERSION,
        asset_version=static_files_version.for_page(),
        page_title="MetaList - Vault Renamed",
        source_namespace=job_record["source_namespace"],
        target_namespace=job_record["target_namespace"],
        page_state_json=page_state,
    )


@app.get("/namespace-renamed/open")
async def namespace_renamed_open_page(request: Request):
    job_id = _page_param(request, "job")
    if job_id is None:
        return HTMLResponse("Missing vault rename job", status_code=HTTPStatus.BAD_REQUEST)
    job_record_capture = CapturedExceptionContext(NamespaceInputRejected, FileNotFoundError, boundary='app/main.py:namespace_renamed_open_page:job_record_capture')
    job_record: dict[str, object] | None = None
    with job_record_capture:
        job_record = load_namespace_rename_job(job_id=job_id)
    if job_record_capture.captured_exception is not None:
        exc = job_record_capture.captured_exception
        return HTMLResponse(str(exc), status_code=HTTPStatus.BAD_REQUEST)
    if job_record is None:
        return HTMLResponse(f"Vault rename job not found: {job_id}", status_code=HTTPStatus.NOT_FOUND)
    if job_record["status"] != "succeeded":
        return HTMLResponse("Vault rename is not complete", status_code=HTTPStatus.CONFLICT)
    if ACTIVE_NAMESPACE != job_record["target_namespace"]:
        return HTMLResponse("Renamed vault is not running here", status_code=HTTPStatus.CONFLICT)
    response = RedirectResponse(url="/?force_reauth=1", status_code=HTTPStatus.TEMPORARY_REDIRECT)
    clear_auth_cookie(response=response)
    return response


@app.get("/locked", response_class=HTMLResponse)
async def locked_page(request: Request, db: Annotated[SafeSession, Depends(get_db)]):
    """Render a dedicated locked screen when a session is invalidated."""
    template = templates.get_template("locked.html")
    auth = AuthService(db)
    has_password = auth.has_password()
    return template.render(
        request=request,
        version=VERSION,
        asset_version=static_files_version.for_page(),
        page_title=_resolve_page_title(base_title="MetaList – Locked"),
        has_password=has_password,
    )


@app.exception_handler(AttachmentSizeExceeded)
async def attachment_size_error(request: Request, exc: AttachmentSizeExceeded):
    return JSONResponse(status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, content={"detail": str(exc)})


@app.exception_handler(FileRevisionConflict)
async def file_revision_conflict(request: Request, exc: FileRevisionConflict):
    return JSONResponse(status_code=HTTPStatus.CONFLICT, content={"detail": str(exc), "currentRevision": exc.current_revision})


@app.exception_handler(FileNotEditable)
async def file_not_editable(request: Request, exc: FileNotEditable):
    return JSONResponse(status_code=HTTPStatus.BAD_REQUEST, content={"detail": str(exc)})


@app.exception_handler(InvalidFileContent)
async def invalid_file_content(request: Request, exc: InvalidFileContent):
    return JSONResponse(status_code=HTTPStatus.BAD_REQUEST, content={"detail": str(exc)})


@app.exception_handler(FilePreviewMissing)
async def file_preview_missing(request: Request, exc: FilePreviewMissing):
    return JSONResponse(status_code=HTTPStatus.NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(FileEditSessionMissing)
async def file_edit_session_missing(request: Request, exc: FileEditSessionMissing):
    return JSONResponse(status_code=HTTPStatus.GONE, content={"detail": str(exc)})


@app.exception_handler(HierarchyError)
async def hierarchy_error(request: Request, exc: HierarchyError):
    return JSONResponse(status_code=HTTPStatus.UNPROCESSABLE_ENTITY, content={'detail': str(exc)})


@app.exception_handler(ShellCapacityError)
async def shell_capacity_error(request: Request, exc: ShellCapacityError):
    return JSONResponse(status_code=HTTPStatus.TOO_MANY_REQUESTS, content={'detail': str(exc)})


@app.on_event('shutdown')
async def stop_shell_runs():
    await run_in_threadpool(shell_session_service.reset)


@app.exception_handler(ClipboardCapacityError)
async def clipboard_capacity_error(request: Request, exc: ClipboardCapacityError):
    return JSONResponse(status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE, content={'detail': str(exc)})


@app.exception_handler(ShellRunNotFound)
async def shell_run_not_found(request: Request, exc: ShellRunNotFound):
    return JSONResponse(status_code=HTTPStatus.NOT_FOUND, content={"detail": str(exc)})


# The log writes a request's route and handler only as the app declares them: every route is in place now.
safe_log.allow_route_templates(app.routes)
