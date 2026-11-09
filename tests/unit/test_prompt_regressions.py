import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.agent import context as production_context
from app.services.agent.inference import InferenceProviderError
from app.services.agent.judging import OutputJudgment
from evals import __main__ as cli
from evals import production
from evals.__main__ import compare
from evals.models import JudgeConfig, RegressionCase
from evals.runner import fingerprint, matches, prepare_case, run_case, with_note_ids


ROOT = Path(__file__).resolve().parents[2]
SUMMARY_CASE = ROOT / "evals/cases/staged-summary/complete-scope.json"
# Replies to the summary batch step: the expectation wants findings citing both notes.
GOOD_FINDINGS = json.dumps({"findings": [{"text": "Both agree.", "supporting_note_ids": ["note-a", "note-b"]}]})
BAD_FINDINGS = json.dumps({"findings": [{"text": "Only one.", "supporting_note_ids": ["note-a"]}]})


def summary_case() -> RegressionCase:
    return RegressionCase.model_validate_json(SUMMARY_CASE.read_text())


def batch_case() -> RegressionCase:
    complete = json.loads(SUMMARY_CASE.read_text())
    return RegressionCase.model_validate(complete | {"id": "summary-batch", "steps": complete["steps"][:1]})


def final_case() -> RegressionCase:
    complete = json.loads(SUMMARY_CASE.read_text())
    return RegressionCase.model_validate(complete | {"id": "summary-final", "steps": complete["steps"][1:]})


def with_selected_note(case: RegressionCase, selected_note: dict) -> RegressionCase:
    fixture = case.model_dump()
    fixture["steps"][0]["context"]["selected_note"] = selected_note
    return RegressionCase.model_validate(fixture)


def _selected_tree() -> dict:
    return {"status": "available", "note_id": "child", "tree_notes": [
        {"note_id": "root", "parent_id": "", "content_text": "Reading list", "tags": "papers"},
        {"note_id": "child", "parent_id": "root", "content_text": "Attention paper", "tags": ""},
    ]}


def test_every_live_case_uses_changed_production_system_prompt(monkeypatch):
    original_loader = production.load_prompt
    monkeypatch.setattr(production, "load_prompt", lambda name:
        "Changed production system instructions" if name == "system.md" else original_loader(name))
    paths = list((ROOT / "evals/cases").rglob("*.json"))
    assert paths
    for path in paths:
        scenario = RegressionCase.model_validate_json(path.read_text())
        before = scenario.model_dump()
        prepared = prepare_case(scenario)
        assert all(step.messages[0].content == "Changed production system instructions" for step in prepared.steps)
        assert scenario.model_dump() == before


def test_summary_builder_changes_reach_existing_cases(monkeypatch):
    original = production_context.AgentContextBuilder.build_staged_summary_batch_messages

    def changed(self, **kwargs):
        return original(self, **kwargs) + [{"role": "user", "content": "New runtime context"}]

    monkeypatch.setattr(production_context.AgentContextBuilder, "build_staged_summary_batch_messages", changed)
    prepared = prepare_case(batch_case())
    assert any(message.content == "New runtime context" for message in prepared.steps[0].messages)
    assert any(m.content.startswith("SELECTED_NOTE_CONTEXT\n") for m in prepared.steps[0].messages)


def test_schema_changes_flow_into_requests_without_revising_scenarios(monkeypatch):
    model = production.RESPONSE_MODELS["SummaryFindingsResult"]
    schema = model.model_json_schema()
    schema["description"] = "Current schema changed"
    monkeypatch.setattr(model, "model_json_schema", classmethod(lambda cls: schema))
    source = batch_case()
    before = source.model_dump()
    assert prepare_case(source).steps[0].response_schema == schema
    assert source.model_dump() == before


def test_current_skill_changes_effective_fingerprint_only(monkeypatch):
    source = final_case()
    before = prepare_case(source).model_dump()
    scenario_fingerprint = fingerprint(source.model_dump())
    original_loader = production.load_skill
    monkeypatch.setattr(production, "load_skill", lambda name:
        "Changed summary skill" if name == "staged-summary.md" else original_loader(name))
    after = prepare_case(source).model_dump()
    assert fingerprint(before) != fingerprint(after)
    assert fingerprint(source.model_dump()) == scenario_fingerprint
    assert before["steps"][0]["expectation"] == after["steps"][0]["expectation"]
    assert "Changed summary skill" in json.dumps(after)


def test_captured_prompts_and_schemas_are_not_allowed_in_scenarios():
    fixture = batch_case().model_dump()
    fixture["steps"][0]["prompt_bindings"] = []
    with pytest.raises(ValueError, match="Extra inputs"):
        RegressionCase.model_validate(fixture)
    fixture = batch_case().model_dump()
    fixture["steps"][0]["conversation"].insert(0, {"role": "system", "content": "Frozen instructions"})
    with pytest.raises(ValueError):
        RegressionCase.model_validate(fixture)


def test_selected_note_tree_is_rebuilt_by_current_production_code():
    scenario = with_selected_note(batch_case(), _selected_tree())
    step = prepare_case(scenario).steps[0]
    selected = next(m for m in step.messages if m.content.startswith("SELECTED_NOTE_CONTEXT\n"))
    payload = json.loads(selected.content.split("\n", 1)[1])["selected_note"]
    # Sent by short note IDs (n1, n2…), as the runtime sends them.
    note_ids = step.note_ids_by_alias
    assert [note_ids[node["note_id"]] for node in payload["tree_notes"]] == ["root", "child"]
    assert [note_ids[node["note_id"]] for node in payload["tree_notes"] if node["is_selected"]] == ["child"]


def test_cached_title_case_uses_current_production_extraction(monkeypatch):
    url = "https://example.test/paper"
    scenario = with_selected_note(batch_case(), {"status": "available", "note_id": "html", "tree_notes": [
        {"note_id": "html", "parent_id": "", "content_html": f'<p><a href="{url}">{url}</a></p>', "tags": "",
         "cached_url_titles": {url: "Do Transformers Need Three Projections?"}},
    ]})
    original = scenario.model_dump()
    assert "Do Transformers Need Three Projections?" in str(prepare_case(scenario).model_dump())
    extract = production.extract_agent_note_text

    def changed(**kwargs):
        content, redacted = extract(**kwargs)
        return content + " UPDATED_PRODUCTION_TITLE_FORMAT", redacted

    monkeypatch.setattr(production, "extract_agent_note_text", changed)
    assert "UPDATED_PRODUCTION_TITLE_FORMAT" in str(prepare_case(scenario).model_dump())
    assert scenario.model_dump() == original


@pytest.mark.parametrize("invalid", ["missing_selection", "missing_parent", "duplicate", "cycle"])
def test_selected_tree_rejects_invalid_structure_before_live_requests(invalid):
    selected = _selected_tree()
    if invalid == "missing_selection":
        selected["note_id"] = "missing"
    elif invalid == "missing_parent":
        selected["tree_notes"][1]["parent_id"] = "missing"
    elif invalid == "duplicate":
        selected["tree_notes"].append(selected["tree_notes"][1].copy())
    else:
        selected["tree_notes"][0]["parent_id"] = selected["tree_notes"][-1]["note_id"]
    with pytest.raises(AssertionError):
        prepare_case(with_selected_note(batch_case(), selected))


def test_steps_and_repetitions_do_not_inherit_outputs():
    fixture = batch_case().model_dump()
    next_step = batch_case().steps[0].model_dump()
    next_step["conversation"].insert(0, {"role": "assistant", "from_step": 0})
    fixture["steps"].append(next_step)
    seen = []

    class Adapter:
        async def infer_structured(self, **kwargs):
            seen.append(kwargs["messages"])
            findings = json.loads(GOOD_FINDINGS)
            findings["findings"][0]["text"] = f"trial {len(seen)}"
            return SimpleNamespace(content=json.dumps(findings))

    asyncio.run(run_case(RegressionCase.model_validate(fixture), adapter=Adapter(), judge=None,
        on_repetition=lambda outcome: None, repetitions=2))
    assert len(seen) == 4
    assert all(m["role"] != "assistant" for m in seen[0] + seen[2])
    for index in (1, 3):
        prior = [m for m in seen[index] if m["role"] == "assistant"]
        assert len(prior) == 1 and json.loads(prior[0]["content"])["findings"][0]["text"] == f"trial {index}"


@pytest.mark.parametrize("status,exit_code", [("incorrect", 1), ("error", 2)])
def test_cli_fails_for_wrong_behavior_and_provider_errors(tmp_path, monkeypatch, status, exit_code):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-key")
    monkeypatch.setattr(cli, "OpenAIInferenceAdapter", lambda **kwargs: object())

    async def fake_run(*args, **kwargs):
        return [{"case_id": args[0][0].id, "counts": {"correct": 0, "incorrect": int(status == "incorrect"),
                "error": int(status == "error")}, "percent_correct": 0}]

    monkeypatch.setattr(cli, "run_cases", fake_run)
    path = tmp_path / "summary-batch.json"
    path.write_text(batch_case().model_dump_json())
    arguments = SimpleNamespace(cases=[path], repetitions=1, concurrency=4,
        judge=None, live=True, output=tmp_path / "report", changed_since=None)
    with pytest.raises(SystemExit) as exc:
        asyncio.run(cli.run(arguments))
    assert exc.value.code == exit_code
    assert (arguments.output / "report.json").exists()


def test_ten_repetitions_keep_errors_in_denominator_and_reset_context(tmp_path):
    seen = []

    class Adapter:
        async def infer_structured(self, **kwargs):
            seen.append(json.loads(json.dumps(kwargs["messages"])))
            kwargs["messages"].clear()  # An adapter cannot contaminate the next repetition.
            if len(seen) == 9:
                raise InferenceProviderError("offline")
            if len(seen) <= 8:
                return SimpleNamespace(content=GOOD_FINDINGS)
            return SimpleNamespace(content=BAD_FINDINGS)

    outcomes = []
    report = asyncio.run(run_case(batch_case(), adapter=Adapter(), judge=None,
        on_repetition=outcomes.append, repetitions=10))
    assert report["counts"] == {"correct": 8, "incorrect": 1, "error": 1}
    assert report["percent_correct"] == 80
    assert len(outcomes) == 10
    assert all(messages == seen[0] for messages in seen)


def test_output_case_generates_and_judges_ten_distinct_outputs(tmp_path):
    judged = []

    class Adapter:
        count = 0

        async def stream_text(self, **kwargs):
            self.count += 1
            yield {"type": "content_delta", "text": f"Answer {self.count}"}
            yield {"type": "done"}

        async def infer_structured(self, **kwargs):
            assert kwargs["response_model"] is OutputJudgment
            payload = json.loads(kwargs["messages"][1]["content"])
            judged.append(payload["candidate_output"])
            return SimpleNamespace(content=json.dumps({"criteria": [
                {"criterion_id": item["id"], "passed": self.count != 10, "reason": "fixture verdict"}
                for item in payload["rubric"]["criteria"]
            ]}))

    judge = JudgeConfig(model="gpt-5.6-luna", thinking_level="off", prompt="Judge criteria")
    report = asyncio.run(run_case(final_case(), adapter=Adapter(), judge=judge,
        on_repetition=lambda outcome: None, repetitions=10))
    assert len(set(judged)) == 10
    assert report["percent_correct"] == 90


def test_action_match_checks_args_extra_list_actions_and_types():
    assert matches({"kind": "summary"}, {"kind": "summary", "reason": "Any wording"})
    assert not matches({"tokens": 250000}, {"tokens": 100000})
    assert not matches({"tokens": 1}, {"tokens": True})
    assert not matches([{"kind": "open"}], [{"kind": "open"}, {"kind": "save"}])


def test_judge_missing_criteria_is_an_error_not_a_pass(tmp_path):
    class Adapter:
        async def stream_text(self, **kwargs):
            yield {"type": "content_delta", "text": "An answer"}
            yield {"type": "done"}

        async def infer_structured(self, **kwargs):
            return SimpleNamespace(content=json.dumps({"criteria": [
                {"criterion_id": "missing-criterion", "passed": True, "reason": "Only one checked"},
            ]}))

    report = asyncio.run(run_case(final_case(), adapter=Adapter(),
        judge=JudgeConfig(model="gpt-5.6-luna", thinking_level="off", prompt="Judge"),
        on_repetition=lambda outcome: None))
    assert report["counts"] == {"correct": 0, "incorrect": 0, "error": 5}
    assert report["percent_correct"] == 0


def test_comparison_rejects_changed_context(tmp_path, capsys):
    before = {"case_id": "case", "case_fingerprint": "same", "judge": {},
              "repetitions": 10, "percent_correct": 60, "counts": {"error": 0}}
    after = {**before, "percent_correct": 80}
    baseline, candidate = tmp_path / "before.json", tmp_path / "after.json"
    baseline.write_text(json.dumps({"cases": [before]}))
    candidate.write_text(json.dumps({"cases": [after]}))
    args = SimpleNamespace(baseline=baseline, candidate=candidate)
    compare(args)
    assert "+20 percentage points" in capsys.readouterr().out
    after["case_fingerprint"] = "different"
    candidate.write_text(json.dumps({"cases": [after]}))
    with pytest.raises(ValueError, match="changed"):
        compare(args)


def test_default_five_repetitions_use_five_as_denominator(tmp_path):
    seen = []

    class Adapter:
        async def infer_structured(self, **kwargs):
            seen.append(kwargs['messages'])
            replies = [GOOD_FINDINGS, GOOD_FINDINGS, GOOD_FINDINGS, GOOD_FINDINGS, BAD_FINDINGS]
            return SimpleNamespace(content=replies[len(seen) - 1])

    report = asyncio.run(run_case(batch_case(), adapter=Adapter(), judge=None,
        on_repetition=lambda outcome: None))
    assert len(seen) == 5
    assert report['repetitions'] == 5
    assert report['percent_correct'] == 80
    assert report['counts'] == dict(correct=4, incorrect=1, error=0)


def test_unreviewed_cases_are_refused_before_any_request():
    draft = batch_case().model_copy(update={"reviewed": False})
    with pytest.raises(ValueError, match="Review"):
        prepare_case(draft)


# Summary requests name notes by short IDs (n1, n2…, 2026-11-08): a regression grades the model's
# answer with them translated back, so the cases' expectations keep the notes' own ids.
def test_answers_are_graded_with_the_cases_note_ids():
    note_ids = {"n1": "note-a", "n2": "note-b"}
    structured = '{"findings": [{"text": "A", "supporting_note_ids": ["n2", "n1"]}]}'
    assert json.loads(with_note_ids(structured, kind="structured", note_ids_by_alias=note_ids)) == {
        "findings": [{"text": "A", "supporting_note_ids": ["note-b", "note-a"]}],
    }
    assert with_note_ids("Themes [[n1]] and [[n2]].", kind="text", note_ids_by_alias=note_ids) == (
        "Themes [[note-a]] and [[note-b]]."
    )
