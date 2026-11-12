"""Session-only trace capture for the complete conversation and latest-run debug view."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from uuid import uuid4

from app.version import __version__

# Event durations are kept to the microsecond.
_DURATION_MS_DECIMALS = 3
# A session keeps its newest runs for the debug view and the history export; older ones go.
RUNS_PER_SESSION = 50
# A run keeps its newest events. Streaming records one event per provider chunk, so a
# long tool-using answer has a few thousand; this is far above any real run and only
# stops a runaway one from growing without end.
EVENTS_PER_RUN = 100_000
# Ids of dropped runs, kept so a late event for one (the cancellation of an old call)
# is discarded instead of refused. Late events arrive within a run's lifetime, long
# before this many later runs have been dropped.
DISCARDED_RUN_IDS_KEPT = 10_000


class AgentTraceStore:
    def __init__(self) -> None:
        self._exact_detail_hidden_sessions: set[str] = set()
        self._histories: dict[str, list[dict[str, object]]] = {}
        # Insertion-ordered, so the oldest ids leave first (_discard_run_ids_locked).
        self._discarded_run_ids: dict[str, None] = {}
        self._latest_runs: dict[str, dict[str, object]] = {}
        self._lock = Lock()

    def reset(self) -> None:
        with self._lock:
            self._exact_detail_hidden_sessions.clear()
            # Late events for the dropped runs are discarded, as after clear_session.
            for session_key in tuple(self._histories):
                self._forget_runs_locked(session_key)
            assert self._latest_runs == {} and self._histories == {}

    def clear_session(self, *, session_key: str) -> None:
        self._validate_session_key(session_key)
        with self._lock:
            self._exact_detail_hidden_sessions.discard(session_key)
            self._forget_runs_locked(session_key)

    def clear_trace(self, *, session_key: str) -> None:
        self._validate_session_key(session_key)
        with self._lock:
            self._forget_runs_locked(session_key)

    def _forget_runs_locked(self, session_key: str) -> None:
        """Drop the session's runs, so late events for them are discarded."""
        # A run starts both entries (start_run); a session that never ran has neither.
        if session_key not in self._histories:
            assert session_key not in self._latest_runs
            return
        self._discard_run_ids_locked([run["run_id"] for run in self._histories[session_key]])
        del self._latest_runs[session_key]
        del self._histories[session_key]

    def _discard_run_ids_locked(self, run_ids: list) -> None:
        """Remember dropped runs, so late events for them are discarded; keep the newest ids."""
        for run_id in run_ids:
            self._discarded_run_ids[run_id] = None
        while len(self._discarded_run_ids) > DISCARDED_RUN_IDS_KEPT:
            del self._discarded_run_ids[next(iter(self._discarded_run_ids))]

    def set_exact_details_enabled(self, *, session_key: str, enabled: bool) -> None:
        self._validate_session_key(session_key)
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        with self._lock:
            if enabled:
                self._exact_detail_hidden_sessions.discard(session_key)
            else:
                self._exact_detail_hidden_sessions.add(session_key)

    def start_run(self, *, session_key: str, model: str, user_message: str) -> str:
        self._validate_session_key(session_key)
        if not isinstance(model, str) or model == "":
            raise ValueError("Trace model must be non-empty")
        if not isinstance(user_message, str) or user_message == "":
            raise ValueError("Trace user message must be non-empty")
        run_id = str(uuid4())
        with self._lock:
            self._latest_runs[session_key] = {
                "run_id": run_id,
                "model": model,
                "user_message": user_message,
                "status": "running",
                "started_at": self._now_iso(),
                "finished_at": "",
                "error": "",
                "events": [],
                "dropped_events": 0,
            }
            if session_key not in self._histories:
                self._histories[session_key] = []
            history = self._histories[session_key]
            history.append(self._latest_runs[session_key])
            if len(history) > RUNS_PER_SESSION:
                dropped = history[:len(history) - RUNS_PER_SESSION]
                del history[:len(history) - RUNS_PER_SESSION]
                self._discard_run_ids_locked([run["run_id"] for run in dropped])
            assert len(history) <= RUNS_PER_SESSION and history[-1] is self._latest_runs[session_key]
        return run_id

    def append_event(
        self,
        *,
        session_key: str,
        run_id: str,
        event_type: str,
        label: str,
        detail: dict[str, object],
        duration_ms: float,
    ) -> None:
        self._validate_event_input(
            session_key=session_key,
            run_id=run_id,
            event_type=event_type,
            label=label,
            detail=detail,
            duration_ms=duration_ms,
        )
        with self._lock:
            run = self._find_run(session_key, run_id)
            if run is None:
                return
            events = run["events"]
            dropped_events = run["dropped_events"]
            assert isinstance(events, list) and isinstance(dropped_events, int)
            events.append(
                {
                    "sequence": dropped_events + len(events) + 1,
                    "type": event_type,
                    "label": label,
                    "timestamp": self._now_iso(),
                    "duration_ms": round(duration_ms, _DURATION_MS_DECIMALS),
                    "detail": deepcopy(detail),
                }
            )
            if len(events) > EVENTS_PER_RUN:
                excess = len(events) - EVENTS_PER_RUN
                del events[:excess]
                run["dropped_events"] = dropped_events + excess

    def complete_run(self, *, session_key: str, run_id: str) -> None:
        self._finish_run(session_key=session_key, run_id=run_id, status="complete", error="")

    def fail_run(self, *, session_key: str, run_id: str, error: str) -> None:
        if not isinstance(error, str) or error == "":
            raise ValueError("Trace failure error must be non-empty")
        self._finish_run(session_key=session_key, run_id=run_id, status="error", error=error)

    def snapshot(self, *, session_key: str) -> dict[str, object]:
        self._validate_session_key(session_key)
        with self._lock:
            enabled = session_key not in self._exact_detail_hidden_sessions
            if session_key not in self._latest_runs:
                return {"enabled": enabled, "has_trace": False, "run": {}}
            return {"enabled": enabled, "has_trace": True, "run": deepcopy(self._latest_runs[session_key])}

    def export_history(self, *, session_key: str) -> list:
        """One input/output pair per actual provider attempt, in request order."""
        self._validate_session_key(session_key)
        with self._lock:
            runs = []
            if session_key in self._histories:
                runs = deepcopy(self._histories[session_key])
        pairs = []
        for run in runs:
            calls = {}
            run_pair_start = len(pairs)
            for event in _events_of_whole_calls(run):
                detail = event["detail"]
                kind = event["type"]
                if kind == "LLM_CALL_STARTED":
                    calls[detail["call_id"]] = {"input": detail, "pairs": []}
                elif kind == "LLM_WIRE_REQUEST":
                    call = calls[detail["call_id"]]
                    pair = [{
                        "schema_version": 1, "application_version": __version__,
                        "run_id": run["run_id"], "call_id": detail["call_id"],
                        "attempt": len(call["pairs"]) + 1,
                        "timestamp": event["timestamp"],
                        "request": detail["body"],
                        "invocation": call["input"],
                    }, {"status": "running", "response": {}, "chunks": [], "error": ""}]
                    call["pairs"].append(pair)
                    pairs.append(pair)
                elif kind == "LLM_ATTEMPT_OUTPUT":
                    call = calls[detail["call_id"]]
                    if detail["attempt"] <= len(call["pairs"]):
                        output = call["pairs"][detail["attempt"] - 1][1]
                        output.update(response=detail["response"], error=detail["error"])
                        output["status"] = "complete"
                        if detail["error"] != "":
                            output["status"] = "error"
                elif kind == "LLM_RAW_CHUNK":
                    calls[detail["call_id"]]["pairs"][-1][1]["chunks"].append(
                        {key: value for key, value in detail.items() if key != "call_id"}
                    )
                elif kind in {"MENU_REQUESTED", "MENU_RESULT"}:
                    if len(pairs) > run_pair_start:
                        pairs[-1][1].setdefault("application_events", []).append(event)
                elif kind == "LLM_CALL_FINISHED":
                    call = calls[detail["call_id"]]
                    if not call["pairs"]:
                        # Failure before HTTP: retain the attempted invocation explicitly.
                        pair = [{"schema_version": 1, "application_version": __version__,
                                 "run_id": run["run_id"], "call_id": detail["call_id"],
                                 "attempt": 0, "timestamp": event["timestamp"],
                                 "request": {}, "invocation": call["input"]},
                                {"status": detail["status"], "response": {},
                                 "chunks": [], "error": detail["error"]}]
                        pairs.append(pair)
                    else:
                        output = call["pairs"][-1][1]
                        output["status"] = detail["status"]
                        if detail["error"]:
                            output["error"] = detail["error"]
        return pairs

    def _find_run(self, session_key: str, run_id: str):
        # A cleared or reset session may still receive the cancellation of an old call.
        if run_id in self._discarded_run_ids:
            return None
        # Any other run must be one start_run began: an invented id is a bug, in a
        # session with history or without.
        if session_key in self._histories:
            for run in self._histories[session_key]:
                if run["run_id"] == run_id:
                    return run
        raise RuntimeError("Agent trace run id does not match a recorded run")

    def _finish_run(self, *, session_key: str, run_id: str, status: str, error: str) -> None:
        self._validate_session_key(session_key)
        if not isinstance(run_id, str) or run_id == "":
            raise ValueError("run_id must be non-empty")
        if status not in {"complete", "error"}:
            raise ValueError("Unsupported trace completion status")
        with self._lock:
            run = self._find_run(session_key, run_id)
            if run is None:
                return
            run["status"] = status
            run["finished_at"] = self._now_iso()
            run["error"] = error

    @staticmethod
    def _validate_session_key(session_key: str) -> None:
        if not isinstance(session_key, str) or session_key == "":
            raise ValueError("session_key must be a non-empty string")

    @staticmethod
    def _validate_event_input(
        *,
        session_key: str,
        run_id: str,
        event_type: str,
        label: str,
        detail: dict[str, object],
        duration_ms: float,
    ) -> None:
        AgentTraceStore._validate_session_key(session_key)
        if not isinstance(run_id, str) or run_id == "":
            raise ValueError("run_id must be non-empty")
        if not isinstance(event_type, str) or event_type == "":
            raise ValueError("event_type must be non-empty")
        if not isinstance(label, str) or label == "":
            raise ValueError("label must be non-empty")
        if not isinstance(detail, dict):
            raise TypeError("detail must be a dictionary")
        if not isinstance(duration_ms, (int, float)) or duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


def _events_of_whole_calls(run: dict) -> list:
    """The run's events, without those of calls whose start EVENTS_PER_RUN dropped.

    Every provider event names the call LLM_CALL_STARTED opened; a run that kept all
    its events has every start, so its events come back as they are.
    """
    events = run["events"]
    if run["dropped_events"] == 0:
        return events
    started_call_ids = set()
    kept = []
    for event in events:
        detail = event["detail"]
        if event["type"] == "LLM_CALL_STARTED":
            started_call_ids.add(detail["call_id"])
        if "call_id" not in detail or detail["call_id"] in started_call_ids:
            kept.append(event)
    return kept


agent_trace_store = AgentTraceStore()
