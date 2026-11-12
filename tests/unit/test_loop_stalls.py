"""The event-loop watchdog records every stall of a second or longer (app/services/
diagnostics.py, LoopStall): how long the loop answered nothing, the requests active
meanwhile and the stacks while it was stalled, in memory and in the file
METALIST_LOOP_STALL_LOG names. The browser suites fail on any (scripts/browser-loop-stalls.mjs)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

from app.services import diagnostics
from app.services import safe_log

# The watchdog probes every second; a probe scheduled while the loop is blocked for this
# long waits at least BLOCKED_SECONDS - 1 s, and the watchdog looks at it meanwhile.
BLOCKED_SECONDS = 2.6
SHORTEST_STALL_SEEN = BLOCKED_SECONDS - 1.0 - 0.2
LONGEST_STALL_SEEN = BLOCKED_SECONDS
# Time for the late ack and the watchdog's next tick, which records the stall.
RECORDING_WAIT_SECONDS = 1.5
# Long enough for two probes, each answered at once.
QUIET_SECONDS = 2.3


@pytest.fixture(autouse=True)
def _no_recorded_stalls() -> None:
    diagnostics.reset_recorded_loop_stalls()


def _run_watched(blocked_seconds: float, settle_seconds: float) -> None:
    async def watched() -> None:
        watchdog = diagnostics.EventLoopWatchdog(loop=asyncio.get_running_loop())
        watchdog.start()
        await asyncio.sleep(0.1)
        time.sleep(blocked_seconds)
        await asyncio.sleep(settle_seconds)
        watchdog.stop()

    asyncio.run(watched())


def test_a_blocked_loop_is_recorded_with_what_was_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stall_log = tmp_path / "loop-stalls.jsonl"
    monkeypatch.setenv(diagnostics.LOOP_STALL_LOG_ENVIRONMENT_VARIABLE, str(stall_log))
    chat_route = APIRoute("/api2/ai/chat", lambda: None, methods=["POST"])
    safe_log.allow_route_templates([chat_route])
    diagnostics.begin_request(request_id="stalling", method="POST", scope={"path": "/api2/ai/chat", "route": chat_route},
                              has_query=False, started_at=time.perf_counter())

    _run_watched(BLOCKED_SECONDS, RECORDING_WAIT_SECONDS)

    diagnostics.finish_request(request_id="stalling", ended_at=time.perf_counter())
    stalls = diagnostics.recorded_loop_stalls()
    assert len(stalls) == 1, stalls
    stall = stalls[0]
    assert SHORTEST_STALL_SEEN <= stall.seconds <= LONGEST_STALL_SEEN
    assert stall.requests == (("POST", "/api2/ai/chat"),)
    assert "# Thread MainThread" in stall.stacks and "time.sleep(blocked_seconds)" in stall.stacks
    assert stall.is_over
    # One line: the record written while the loop was held was replaced by the finished stall's.
    recorded = [json.loads(line) for line in stall_log.read_text(encoding="utf-8").splitlines()]
    assert recorded == [{"at": stall.at, "seconds": stall.seconds, "requests": [["POST", "/api2/ai/chat"]], "stacks": stall.stacks, "is_over": True}]


def test_a_stall_under_way_is_on_file_before_it_ends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A server stopped while its loop is still held leaves the stall's stacks behind."""
    stall_log = tmp_path / "loop-stalls.jsonl"
    monkeypatch.setenv(diagnostics.LOOP_STALL_LOG_ENVIRONMENT_VARIABLE, str(stall_log))
    seen_while_held: list[str] = []

    async def watched() -> None:
        watchdog = diagnostics.EventLoopWatchdog(loop=asyncio.get_running_loop())
        watchdog.start()
        await asyncio.sleep(0.1)
        time.sleep(BLOCKED_SECONDS)
        # Still on the loop's thread, before the ack: the file already names the stall.
        if stall_log.exists():
            seen_while_held.append(stall_log.read_text(encoding="utf-8"))
        await asyncio.sleep(RECORDING_WAIT_SECONDS)
        watchdog.stop()

    asyncio.run(watched())

    assert len(seen_while_held) == 1, "the stall was written while the loop was held"
    held = json.loads(seen_while_held[0].splitlines()[0])
    assert held["is_over"] is False and held["seconds"] >= 1.0 and "time.sleep(BLOCKED_SECONDS)" in held["stacks"]
    finished = [json.loads(line) for line in stall_log.read_text(encoding="utf-8").splitlines()]
    assert len(finished) == 1 and finished[0]["is_over"] is True and finished[0]["stacks"] == held["stacks"]
    assert diagnostics.recorded_loop_stalls() == [diagnostics.LoopStall(
        at=finished[0]["at"], seconds=finished[0]["seconds"], requests=tuple(finished[0]["requests"]), stacks=finished[0]["stacks"], is_over=True)]


def test_a_loop_that_answers_within_a_second_records_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stall_log = tmp_path / "loop-stalls.jsonl"
    monkeypatch.setenv(diagnostics.LOOP_STALL_LOG_ENVIRONMENT_VARIABLE, str(stall_log))

    _run_watched(0.0, QUIET_SECONDS)

    assert diagnostics.recorded_loop_stalls() == []
    assert not stall_log.exists()


def test_a_stall_shorter_than_the_threshold_is_refused() -> None:
    with pytest.raises(ValueError, match="1.0 s or longer"):
        diagnostics.record_loop_stall(
            diagnostics.LoopStall(at="2026-11-06T00:00:00+00:00", seconds=0.5, requests=(), stacks="", is_over=True), replaces_line_at=None)
