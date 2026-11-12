"""The one plain log MetaList writes, before and after login, holds only allow-listed
events with typed fields (docs/ready-to-build/error-reports.md, section 6). Anything else
throws before it is written."""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
import subprocess
import sys

import pytest
from loguru import logger

from app.services import safe_log


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MARKER = "ZEBRAQUARTZ"


@pytest.fixture
def written_lines():
    """What the plain log's sinks would write: the guard installed, one sink in the same format."""
    lines: list[str] = []
    safe_log.install_safe_log_guard()
    sink_id = logger.add(lambda message: lines.append(str(message)), level="INFO", format=safe_log.SAFE_LOG_FORMAT)
    yield lines
    logger.remove(sink_id)


def test_an_allow_listed_event_writes_its_typed_fields(written_lines) -> None:
    safe_log.log_event("INFO", "startup.step", step="cache population", seconds=1.5)
    assert len(written_lines) == 1
    assert written_lines[0].endswith("| startup.step step=cache population seconds=1.50\n")


def test_an_event_not_on_the_allow_list_throws(written_lines) -> None:
    with pytest.raises(safe_log.UnsafeLogRecord):
        safe_log.log_event("INFO", "note.saved")
    assert written_lines == []


@pytest.mark.parametrize("fields", [
    {"step": MARKER, "seconds": 1.0},
    {"step": "cache population", "seconds": MARKER},
    {"step": "cache population", "seconds": -1.0},
    {"step": "cache population"},
    {"step": "cache population", "seconds": 1.0, "note": MARKER},
])
def test_a_field_outside_its_type_throws_and_never_names_the_value(written_lines, fields) -> None:
    with pytest.raises(safe_log.UnsafeLogRecord) as raised:
        safe_log.log_event("INFO", "startup.step", **fields)
    assert MARKER not in str(raised.value)
    assert written_lines == []


def test_free_text_through_loguru_throws(written_lines) -> None:
    with pytest.raises(safe_log.UnsafeLogRecord):
        logger.info(f"saved note {MARKER}")
    assert written_lines == []


def test_a_route_is_written_only_as_a_template_from_the_app(written_lines) -> None:
    with pytest.raises(safe_log.UnsafeLogRecord):
        safe_log.log_event(
            "INFO", "request", status=404, method="GET", route=f"/api2/tags/{MARKER}",
            handler=safe_log.NO_ROUTE, duration_ms=1.0, size="-", request_id="a1b2c3d4",
        )
    safe_log.log_event(
        "INFO", "request", status=404, method="GET", route=safe_log.NO_ROUTE,
        handler=safe_log.NO_ROUTE, duration_ms=1.0, size="-", request_id="a1b2c3d4",
    )
    assert len(written_lines) == 1
    assert "route=(no route)" in written_lines[0]


def test_code_frames_are_relative_and_hold_no_message() -> None:
    with pytest.raises(ValueError) as raised:
        raise ValueError(MARKER)
    frames = safe_log.safe_code_frames(raised.value.__traceback__)
    assert frames == (f"tests/unit/test_safe_log.py:{test_code_frames_are_relative_and_hold_no_message.__code__.co_firstlineno + 2}:test_code_frames_are_relative_and_hold_no_message",)
    assert str(Path.home()) not in "".join(frames)


def test_a_frame_outside_known_code_is_external() -> None:
    source = compile(f"raise RuntimeError('{MARKER}')", f"/Users/private/{MARKER}.py", "exec")
    with pytest.raises(RuntimeError) as raised:
        exec(source)
    frames = safe_log.safe_code_frames(raised.value.__traceback__)
    assert frames[-1] == "external"
    assert MARKER not in "".join(frames)


def test_a_library_logger_below_warning_is_dropped(written_lines) -> None:
    record = logging.LogRecord("httpx", logging.INFO, "client.py", 1, f'HTTP Request: GET https://{MARKER}.example/ "HTTP/1.1 200 OK"', (), None)
    safe_log.forward_standard_log_record(record)
    assert written_lines == []


def test_a_library_warning_keeps_only_its_logger_and_error_type(written_lines) -> None:
    with pytest.raises(OSError) as raised:
        raise OSError(f"cannot reach https://{MARKER}.example/")
    error = raised.value
    record = logging.LogRecord("httpx._client", logging.ERROR, "client.py", 1, f"failed {MARKER}", (), (OSError, error, error.__traceback__))
    safe_log.forward_standard_log_record(record)
    assert len(written_lines) == 1
    assert "| library logger=httpx error_type=OSError frames=[" in written_lines[0]
    assert MARKER not in written_lines[0]


def test_an_unknown_library_is_named_other(written_lines) -> None:
    record = logging.LogRecord(f"{MARKER}.module", logging.WARNING, "x.py", 1, MARKER, (), None)
    safe_log.forward_standard_log_record(record)
    assert len(written_lines) == 1
    assert "| library logger=other error_type=- frames=[]\n" in written_lines[0]
    assert MARKER not in written_lines[0]


def test_metalist_code_through_the_logging_module_throws(written_lines) -> None:
    record = logging.LogRecord("app.services.content_cache", logging.INFO, "x.py", 1, MARKER, (), None)
    with pytest.raises(safe_log.UnsafeLogRecord):
        safe_log.forward_standard_log_record(record)
    assert written_lines == []


def test_application_code_logs_only_through_safe_log() -> None:
    """Every MetaList log line is an allow-listed event: app/ never calls loguru or the logging
    module's loggers directly, except where the plain log itself is set up."""
    allowed = {
        PROJECT_ROOT / "app" / "services" / "safe_log.py",
    }
    offenders: list[str] = []
    for path in sorted((PROJECT_ROOT / "app").rglob("*.py")):
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "getLogger":
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} getLogger")
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in {"logger", "LOGGER"}:
                if not (path.name in {"main.py", "diagnostics.py"} and node.attr in {"remove", "add", "complete"}):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} {node.value.id}.{node.attr}")
            if isinstance(node, ast.Attribute) and node.attr == "_logger":
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} _logger")
    assert offenders == []


def test_uvicorn_logs_through_the_safe_log_only() -> None:
    """uvicorn's own log handlers would print its error messages (with exception text) to the
    console as they are: run without them, so its records reach forward_standard_log_record."""
    source = (PROJECT_ROOT / "main.py").read_text(encoding="utf-8")
    assert "log_config=None" in source


_REAL_APP_PRELUDE = '''
import re
from fastapi.testclient import TestClient
from loguru import logger
from app.main import app
from app.config import API_PREFIX
from app.services.tokens import token_service
from app.services import safe_log

MARKER = "ZEBRAQUARTZ"
token = token_service.create_token(client_info="fixture", owner_tab_id="tab", dek=None)
headers = {"Authorization": "Bearer " + token, "X-Metalist-Tab-Id": "tab", "Origin": "http://localhost"}
viewport = {"scrollY": 0, "scrollAnchor": None}
'''


def _run_real_app(script: str, tmp_path: Path) -> str:
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run(
        [sys.executable, "-c", _REAL_APP_PRELUDE + script],
        env=environment, capture_output=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, (result.stdout[-3000:], result.stderr[-3000:])
    return result.stdout + result.stderr


def test_every_answer_carries_its_request_id_and_static_successes_are_not_logged(tmp_path) -> None:
    output = _run_real_app('''
def fixture_failure():
    raise ValueError(MARKER)

app.add_api_route(API_PREFIX + "/request-id-fixture", fixture_failure)
safe_log.allow_route_templates(app.routes)
with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
    answers = {
        "ok": client.get(API_PREFIX + "/notes/tab-state", headers=headers),
        "static": client.get("/static/css/main.css"),
        "missing static": client.get("/static/" + MARKER + ".js"),
        "no route": client.get(API_PREFIX + "/" + MARKER, headers=headers),
        "no token": client.get(API_PREFIX + "/notes/tab-state"),
        "invalid": client.post(API_PREFIX + "/notes/view", headers=headers, json={"clientId": MARKER}),
        "server error": client.get(API_PREFIX + "/request-id-fixture", headers=headers),
    }
for name, answer in answers.items():
    assert re.fullmatch("[0-9a-f]{8}", answer.headers["X-Request-Id"]), (name, answer.status_code, dict(answer.headers))
assert answers["static"].status_code == 200
assert answers["server error"].json()["diagnostic"]["requestId"] == answers["server error"].headers["X-Request-Id"]
logger.complete()
''', tmp_path)
    request_lines = [line for line in output.splitlines() if "| request " in line]
    assert not any("route=/static/{path}" in line and "status=200" in line for line in request_lines), request_lines
    assert any("status=404 method=GET route=/static/{path}" in line for line in request_lines), request_lines
    assert any("status=401 method=GET route=(no route)" in line for line in request_lines), request_lines
    assert any("| request.exception " in line and "error_type=ValueError" in line for line in output.splitlines()), output
    assert MARKER not in output


def test_canary_marker_words_never_reach_the_log_after_login(tmp_path) -> None:
    """Marker words in a note, its tags, a search, a missing path, a query string, an error
    message and a fetched URL: none of them appears in what MetaList writes, while a vault is
    unlocked, in the console or in the log file."""
    output = _run_real_app('''
import http.server
import threading
import httpx
from app.server_runtime import resolve_runtime_logs_directory
from app.services.diagnostics import activate_authenticated_logging

class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<title>" + MARKER.encode() + b"</title>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *arguments):
        pass

page_server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Page)
threading.Thread(target=page_server.serve_forever, daemon=True).start()
activate_authenticated_logging(namespace="default", dek=b"k" * 32)

def failing_with_marker():
    raise RuntimeError("note text " + MARKER)

app.add_api_route(API_PREFIX + "/canary-fixture", failing_with_marker)
safe_log.allow_route_templates(app.routes)
with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
    state = client.get(API_PREFIX + "/notes/tab-state", headers=headers).json()
    tab_id = state["activeTabId"]
    created = client.post(API_PREFIX + "/notes/new", headers=headers, json={
        "first_visible_note_id": None, "search_query": None, "tabId": tab_id,
        "clientId": "client", "undoContext": "client", "viewport": viewport,
    })
    assert created.status_code == 200, created.text
    note_id = created.json()["id"]
    saved = client.put(API_PREFIX + "/notes/" + note_id + "/save", headers=headers, json={
        "clientId": "client", "content": MARKER + " https://" + MARKER.lower() + ".example/" + MARKER,
        "tags": MARKER.lower(), "undoContext": "client", "viewport": viewport,
    })
    assert saved.status_code == 200, saved.text
    for search in (MARKER, MARKER.lower(), "#" + MARKER.lower()):
        view = client.post(API_PREFIX + "/notes/view", headers=headers, json={
            "clientId": "client", "editingNoteId": None, "findRevealNoteId": None, "search": search,
            "tabId": tab_id, "undoContext": "client", "tabViewEmpty": False, "visibleTopRootId": None,
            "visibleBottomRootId": None, "isUntaggedView": False, "startAtListEnd": False,
        })
        assert view.status_code == 200, view.text
    client.post(API_PREFIX + "/notes/search-suggestions", headers=headers, json={"query": MARKER, "windowDays": []})
    client.get(API_PREFIX + "/notes/" + MARKER + "/preview?search=" + MARKER, headers=headers)
    client.get("/static/" + MARKER + ".css")
    client.get(API_PREFIX + "/canary-fixture?q=" + MARKER, headers=headers)
    fetched = httpx.get("http://127.0.0.1:" + str(page_server.server_address[1]) + "/" + MARKER)
    assert fetched.status_code == 200
    assert client.get(API_PREFIX + "/notes/tab-state", headers=headers).status_code == 200
logger.complete()
log_text = "".join(path.read_text(encoding="utf-8") for path in resolve_runtime_logs_directory().glob("*.log"))
assert "| request status=200 method=PUT route=/api2/notes/{note_id}/save" in log_text, log_text
assert "| notes.view_state " in log_text, log_text
assert "| request.exception " in log_text, log_text
assert MARKER not in log_text and MARKER.lower() not in log_text, "marker in the log file"
''', tmp_path)
    assert "| request status=200 method=PUT route=/api2/notes/{note_id}/save" in output
    assert MARKER not in output and MARKER.lower() not in output


@pytest.mark.parametrize(("template", "arguments", "stage"), [
    ("Started server process [%d]", (4242,), "process_started"),
    ("Application startup complete.", (), "startup_complete"),
    ("Uvicorn running on http://127.0.0.1:8600 (Press CTRL+C to quit)", (), "listening"),
])
def test_uvicorn_lifecycle_lines_are_written_by_stage_only(written_lines, template, arguments, stage) -> None:
    """Scripts wait for these (scripts/throwaway-metalist.mjs, scripts/browser-smoke.mjs)."""
    safe_log.forward_standard_log_record(logging.LogRecord("uvicorn.error", logging.INFO, "server.py", 1, template, arguments, None))
    assert len(written_lines) == 1
    assert written_lines[0].endswith(f"| server stage={stage}\n")
    assert "8600" not in written_lines[0] and "4242" not in written_lines[0]
