"""Five fresh runs per case using production inference and explicit assertions."""

from __future__ import annotations

import hashlib
import json
import time

from app.services.agent.history import record_history
from app.services.agent.inference import InferenceProviderError
from app.services.agent.judging import OutputJudgment
from app.services.agent.openai_inference import OPENAI_API_BASE_URL
from app.services.agent.trace import AgentTraceStore
from evals.models import PreparedCase, PreviousOutput, RegressionCase
from evals.production import RESPONSE_MODELS, current_prompts, current_skills, prepare_step


REPETITIONS = 5


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def matches(expected, actual) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            key in actual and matches(value, actual[key]) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(
            matches(left, right) for left, right in zip(expected, actual)
        )
    return type(expected) is type(actual) and expected == actual


def prepare_case(case: RegressionCase) -> PreparedCase:
    """Build every request with current production code before provider calls."""
    if not case.reviewed:
        raise ValueError(f"Review expected behavior and set reviewed=true: {case.id}")
    prompts, skills = current_prompts(), current_skills()
    return PreparedCase(id=case.id, model=case.model, thinking_level=case.thinking_level,
        steps=[prepare_step(step, prompts=prompts, skills=skills) for step in case.steps])


async def call_step(adapter, *, case, step, messages):
    arguments = dict(base_url=OPENAI_API_BASE_URL, model=case.model,
                     thinking_level=case.thinking_level, messages=messages)
    if step.kind == "structured":
        response = await adapter.infer_structured(
            **arguments, response_model=RESPONSE_MODELS[step.response_model],
            on_progress=lambda progress: None,
        )
        return response.content
    chunks = []
    finished = False
    async for event in adapter.stream_text(
        **arguments,
        on_request=lambda request: None,
    ):
        if event["type"] == "content_delta":
            chunks.append(event["text"])
        if event["type"] == "done":
            finished = True
    if not finished or not "".join(chunks).strip():
        raise InferenceProviderError("Missing completed text output")
    return "".join(chunks)


async def evaluate_output(adapter, *, expectation, messages, output, judge):
    if expectation.kind == "action":
        actual = json.loads(output)
        return {"correct": any(matches(choice, actual) for choice in expectation.alternatives),
                "actual": actual, "expected": expectation.model_dump()}
    assert judge is not None, "Output cases require explicit judge configuration"
    response = await adapter.infer_structured(
        base_url=OPENAI_API_BASE_URL, model=judge.model,
        thinking_level=judge.thinking_level,
        messages=[{"role": "system", "content": judge.prompt},
                  {"role": "user", "content": json.dumps({
                      "context": messages, "candidate_output": output,
                      "rubric": expectation.model_dump(),
                  })}],
        response_model=OutputJudgment, on_progress=lambda progress: None,
    )
    verdict = OutputJudgment.model_validate_json(response.content)
    actual_ids = [item.criterion_id for item in verdict.criteria]
    expected_ids = [item.id for item in expectation.criteria]
    if len(actual_ids) != len(expected_ids) or set(actual_ids) != set(expected_ids):
        raise InferenceProviderError("Judge did not return each rubric criterion exactly once")
    return {"correct": all(item.passed for item in verdict.criteria),
            "judgment": verdict.model_dump(), "expected": expectation.model_dump()}


# lint: allow-PY005 rationale="documented five-trial default; explicit CLI override permits shorter live runs"
async def run_case(case, *, adapter, judge, on_repetition, repetitions=REPETITIONS):
    return await run_prepared_case(case, prepared=prepare_case(case), adapter=adapter,
        judge=judge, on_repetition=on_repetition, repetitions=repetitions)


async def run_prepared_case(case, *, prepared, adapter, judge, on_repetition, repetitions):
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError("Repetitions must be a positive integer")
    assert prepared.id == case.id
    if any(step.expectation.kind == "output" for step in prepared.steps) and judge is None:
        raise ValueError("Output cases require --judge configuration")
    outcomes = []
    for repetition in range(1, repetitions + 1):
        traces = AgentTraceStore()
        run_id = traces.start_run(session_key="regression", model=prepared.model, user_message=prepared.id)
        started = time.perf_counter()
        results, outputs = [], []
        status, error = "correct", ""
        # No application handlers or live note stores are invoked by replay.
        with record_history(traces, session_key="regression", run_id=run_id):
            # lint: allow-PY001 rationale="count external inference errors as failed repetitions; internal errors propagate"
            try:
                for step in prepared.steps:
                    messages = [
                        {"role": message.role, "content": outputs[message.from_step]}
                        if isinstance(message, PreviousOutput) else message.model_dump()
                        for message in step.messages
                    ]
                    output = await call_step(adapter, case=prepared, step=step, messages=messages)
                    outputs.append(output)
                    verdict = await evaluate_output(adapter, expectation=step.expectation,
                        messages=messages, output=output, judge=judge)
                    results.append({"output": output, **verdict})
                    if not verdict["correct"]:
                        status = "incorrect"
            # lint: allow-PY001 rationale="persist external provider errors in the repetition report, never count them as correct"
            except InferenceProviderError as exc:
                status, error = "error", f"{type(exc).__name__}: {exc}"
        pairs = traces.export_history(session_key="regression")
        outcomes.append({"repetition": repetition, "status": status, "error": error,
                         "steps": results, "outputs": outputs,
                         "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                         "provider_attempts": sum(pair[0]["attempt"] > 0 for pair in pairs),
                         "pairs": pairs})
        on_repetition(outcomes[-1])
    counts = {status: sum(item["status"] == status for item in outcomes)
              for status in ("correct", "incorrect", "error")}
    assert sum(counts.values()) == repetitions
    return {"schema_version": 2, "case_id": case.id, "prompt_source": "current-production",
            "case_fingerprint": fingerprint(case.model_dump()),
            "effective_case": prepared.model_dump(),
            "effective_fingerprint": fingerprint(prepared.model_dump()),
            "judge": judge.model_dump() if judge is not None else {},
            "repetitions": repetitions, "counts": counts,
            "percent_correct": 100 * counts["correct"] / repetitions,
            "outcomes": outcomes}
