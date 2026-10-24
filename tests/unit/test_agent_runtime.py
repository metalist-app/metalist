from __future__ import annotations

from app.services.agent.inference import StructuredInferenceProgress
from app.services.agent.model_policy import InferencePurpose
from app.services.agent.runtime import AgentRuntime


def test_structured_progress_reports_output_without_naming_removed_routes() -> None:
    progress = StructuredInferenceProgress(
        phase="output_progress",
        attempt=1,
        max_attempts=2,
        failure_kind="",
        error_type="",
        error_message="",
        duration_ms=50.0,
        wire_request={
            "method": "POST",
            "url": "http://127.0.0.1/v1/chat/completions",
            "body": {"messages": [{"role": "user", "content": "Summarize"}]},
        },
        output_tokens_received=24,
        partial_output={},
    )
    event = AgentRuntime._progress_status_event(
        progress,
        purpose=InferencePurpose.SUMMARY_BATCH,
        provider_label="OpenAI",
    )
    assert event["output_tokens_received"] == 24
    assert event["label"] == "OpenAI writing a structured reply"

