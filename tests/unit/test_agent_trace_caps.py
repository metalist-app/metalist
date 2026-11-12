"""The AI trace store keeps a bounded number of runs, events and discarded run ids
(docs/ready-to-build/unbounded-growth-audit.md, M3)."""

import app.services.agent.trace as trace_module
from app.services.agent.trace import AgentTraceStore


def _event(traces, run_id, event_type, detail):
    traces.append_event(session_key="a", run_id=run_id, event_type=event_type, label=event_type,
                        detail=detail, duration_ms=1.0)


def test_a_session_keeps_its_newest_fifty_runs():
    traces = AgentTraceStore()
    run_ids = [traces.start_run(session_key="a", model="gpt-5.6-luna", user_message=f"Question {index}")
               for index in range(60)]

    kept = [run["run_id"] for run in traces._histories["a"]]

    assert kept == run_ids[10:]
    assert traces.snapshot(session_key="a")["run"]["run_id"] == run_ids[-1]


def test_a_late_event_for_a_run_dropped_by_the_cap_is_discarded():
    traces = AgentTraceStore()
    oldest = traces.start_run(session_key="a", model="gpt-5.6-luna", user_message="Oldest")
    for index in range(50):
        traces.start_run(session_key="a", model="gpt-5.6-luna", user_message=f"Question {index}")

    _event(traces, oldest, "LLM_CALL_FINISHED", {"call_id": "c", "status": "cancelled", "error": "Interrupted"})
    traces.fail_run(session_key="a", run_id=oldest, error="Late cancellation")

    assert oldest not in [run["run_id"] for run in traces._histories["a"]]


def test_a_run_keeps_its_newest_events(monkeypatch):
    monkeypatch.setattr(trace_module, "EVENTS_PER_RUN", 5)
    traces = AgentTraceStore()
    run_id = traces.start_run(session_key="a", model="gpt-5.6-luna", user_message="Long run")
    for index in range(8):
        _event(traces, run_id, "STEP", {"index": index})

    run = traces.snapshot(session_key="a")["run"]

    assert [event["detail"]["index"] for event in run["events"]] == [3, 4, 5, 6, 7]
    assert [event["sequence"] for event in run["events"]] == [4, 5, 6, 7, 8]
    assert run["dropped_events"] == 3


def test_the_export_of_a_trimmed_run_keeps_the_calls_whose_start_it_kept(monkeypatch):
    monkeypatch.setattr(trace_module, "EVENTS_PER_RUN", 4)
    traces = AgentTraceStore()
    run_id = traces.start_run(session_key="a", model="gpt-5.6-luna", user_message="Two calls")
    for call_id in ("first", "second"):
        _event(traces, run_id, "LLM_CALL_STARTED", {"call_id": call_id, "kind": "text"})
        _event(traces, run_id, "LLM_WIRE_REQUEST", {"call_id": call_id, "body": {"call": call_id}})
        _event(traces, run_id, "LLM_CALL_FINISHED", {"call_id": call_id, "status": "complete", "error": ""})

    pairs = traces.export_history(session_key="a")

    assert [pair[0]["call_id"] for pair in pairs] == ["second"]
    assert pairs[0][1]["status"] == "complete"


def test_discarded_run_ids_keep_only_the_newest(monkeypatch):
    monkeypatch.setattr(trace_module, "DISCARDED_RUN_IDS_KEPT", 3)
    traces = AgentTraceStore()
    run_ids = []
    for index in range(5):
        run_ids.append(traces.start_run(session_key="a", model="gpt-5.6-luna", user_message=f"Question {index}"))
        traces.clear_trace(session_key="a")

    assert list(traces._discarded_run_ids) == run_ids[2:]
    traces.fail_run(session_key="a", run_id=run_ids[-1], error="Late cancellation")
