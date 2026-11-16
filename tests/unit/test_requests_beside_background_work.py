"""A request is not held up by the work the server starts beside it (the [[ catalog, file texts,
PDF pages, link pruning: all begin once the page is ready). Python hands its interpreter lock to
a waiting thread only every switch interval, and a request waits for it again each time it comes
back from the database. At Python's 5 ms, a link clicked just after startup took about a second
(1,008 ms in a 100,000-note vault, against 125 ms once the work was done); at 0.5 ms, 232-257 ms
(2026-11-13). So the server sets the interval as it starts."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from app.services.requests_in_flight import interpreter_switch_seconds

_IMPORT_TIMEOUT_SECONDS = 60


def test_the_server_hands_the_interpreter_lock_on_quickly(tmp_path) -> None:
    # Its own process: importing the app starts services that must not run in the tests.
    script = (
        "import json, sys\n"
        "import app.main\n"
        "print(json.dumps(sys.getswitchinterval()))\n"
    )
    environment = dict(os.environ, METALIST_DATA_DIRECTORY=str(tmp_path), METALIST_ENVIRONMENT="production")
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=_IMPORT_TIMEOUT_SECONDS,
    )
    assert result.returncode == 0, result.stderr[-3000:]
    switch_seconds = json.loads(result.stdout.strip().splitlines()[-1])
    # Half a millisecond where the system can wait that short; a whole one on Windows
    # (test_requests_in_flight.py checks each system's value on every machine).
    assert switch_seconds == pytest.approx(interpreter_switch_seconds(platform=sys.platform))
