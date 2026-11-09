from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import replace
from types import MappingProxyType

import pytest

from app.services.agent.investigation import InvestigationState
from app.services.agent.staged_summary import ModelTiming
from app.services.ai_catalog import AI_CATALOG
from app.services.agent.context import AgentContextBuilder
from app.services.agent.inference import InferenceAttempt
from app.services.agent.inference import InferenceContextWindow
from app.services.agent.inference import InferenceResponse
from app.services.agent.inference import StructuredInferenceError
from app.services.agent.inference import StructuredInferenceProgress
from app.services.agent.model_policy import SingleModelPolicy
from app.services.agent.prompt_settings import DEFAULT_AGENT_PROMPTS
from app.services.agent.retrieval_settings import AgentRetrievalSettings
from app.services.agent import provider_limits
from app.services.agent import runtime as runtime_module
from app.services.agent.runtime import AgentExecutionError
from app.services.agent.runtime import AgentRuntime
from app.services.agent.scope import AgentScopeDescriptor, NO_SELECTED_NOTE
from app.services.agent.scope import FrozenScopedNote
from app.services.agent.scope import NoteText
from app.services.agent.scope import FrozenScopedTreeNode
from app.services.agent.scope import ScopedSearchSnapshot
from app.services.agent.scope import TextExtractionMeter
from app.services.agent.scope import SelectedNoteContext, SelectedTreeNote
from app.services.agent.skill_settings import DEFAULT_AGENT_SKILLS
from app.services.agent.web_settings import DEFAULT_AGENT_WEB_SETTINGS
from app.services.agent.web_settings import AgentWebSettings
from app.services.agent.web_evidence import web_evidence_store
from app.services.agent.summary_batch_store import summary_batch_store
from app.services.agent.web_fetch import WebPageFetchResult
from app.services.agent.trace import AgentTraceStore
from app.services.agent.note_aliases import ALIAS_RE, NoteAliases
from app.services.bulk_operation import bulk_operation_guard

def _descriptor() -> AgentScopeDescriptor:
    return AgentScopeDescriptor(
        scope_kind="search",
        active_tab_id="tab-1",
        scope_tab_id="tab-1",
        search_query="testosterone",
        sort_mode="normal",
        reference_root_ids=[],
        label="testosterone",
    )


def _note(
    note_id: str,
    root_note_id: str,
    parent_id: str,
    content: str,
    index: int,
) -> FrozenScopedNote:
    return FrozenScopedNote(
        note_id=note_id,
        parent_id=parent_id,
        root_note_id=root_note_id,
        note_text=NoteText.from_text(content),
        explicit_tags_text="testosterone",
        explicit_tag_terms=("testosterone",),
        proposed_tags_text="",
        proposed_tag_terms=(),
        created_at="2026-08-29T00:00:00+00:00",
        updated_at="2026-08-29T00:00:00+00:00",
        order_index=index,
    )


def _snapshot(*, large_tail: bool) -> ScopedSearchSnapshot:
    tail = "TAIL"
    if large_tail:
        tail = "TAIL " * 10_000
    notes = {
        "root-a": _note("root-a", "root-a", "", "ROOT_ALPHA", 0),
        "child-a": _note("child-a", "root-a", "root-a", "CHILD_ALPHA", 1),
        "root-b": _note("root-b", "root-b", "", tail, 2),
    }
    nodes = {
        "root-a": FrozenScopedTreeNode(
            note_id="root-a",
            parent_id="",
            root_note_id="root-a",
            child_ids=("child-a",),
        ),
        "child-a": FrozenScopedTreeNode(
            note_id="child-a",
            parent_id="root-a",
            root_note_id="root-a",
            child_ids=(),
        ),
        "root-b": FrozenScopedTreeNode(
            note_id="root-b",
            parent_id="",
            root_note_id="root-b",
            child_ids=(),
        ),
    }
    return ScopedSearchSnapshot(
        run_id="scope-run",
        session_key="session-1",
        descriptor=_descriptor(),
        created_at="2026-08-29T00:00:00+00:00",
        ordered_root_ids=("root-a", "root-b"),
        ordered_note_ids=("root-a", "child-a", "root-b"),
        notes_by_id=MappingProxyType(notes),
        tree_nodes_by_id=MappingProxyType(nodes),
        note_records_at_send=MappingProxyType({}),
        disclosable_search_query=_descriptor().search_query,
        date_filter=None, file_filter=None,
        preparation_ms=0.0, text_extraction=TextExtractionMeter.start(),
        selected_note=NO_SELECTED_NOTE,
    )


class _FakeInference:
    """Plays an agent that asks to summarize the view, then the summary model calls."""

    provider_label = "OpenAI"

    def __init__(self) -> None:
        self.large_summary_results = False
        self.failed_summary_root_id = ""
        self.omit_summary_coverage = False
        self.summary_batch_citation_note_id = ""
        # A note ID cited beside the real one in every round, as a model that garbles an ID does;
        # in the batch of summary_ghost_only_root_id it is the only one cited.
        self.summary_batch_extra_citation_note_id = ""
        # Each batch request as the model saw it, and the run's note ids by the short IDs it saw
        # (set by _collect_summary_events), so the recorded root ids stay the snapshot's.
        self.summary_batch_payloads: list[dict[str, object]] = []
        self.note_ids_by_alias: dict[str, str] = {}
        # The final answer cites the first note of its reference catalog, as a model does.
        self.final_cites_first_reference = False
        self.summary_ghost_only_root_id = ""
        self.summary_delay_seconds_by_root_id: dict[str, float] = {}
        self.summary_citation_corrections = 0
        self.summary_instructions: list[str] = []
        self.summary_requests: list[str] = []
        self.summary_tool_arguments = '{"continues_failed_summary":false}'
        self.failed_summary_as_agent_error = False
        self.ignore_summary_citation_corrections = False
        self.final_messages: list[dict[str, str]] = []
        self.agent_messages: list[dict[str, object]] = []
        self.summary_batch_calls: list[tuple[str, ...]] = []
        self.active_summary_calls = 0
        self.summary_completion_order: list[str] = []
        self.maximum_parallel_summary_calls = 0
        self.summary_reduction_calls = 0

    async def inspect_context_window(
        self,
        *,
        base_url: str,
        model: str,
    ) -> InferenceContextWindow:
        del base_url
        return InferenceContextWindow(
            model=model,
            maximum_tokens=32_768,
            loaded_tokens=32_768,
            required_tokens=32_768,
        )

    async def infer_structured(
        self,
        *,
        base_url,
        model,
        thinking_level,
        messages,
        response_model,
        on_progress,
    ) -> InferenceResponse:
        del thinking_level
        if response_model.__name__ in {"SummaryBatchResult", "SummaryFindingsResult"}:
            request_message = next(
                message["content"] for message in reversed(messages)
                if message["content"].startswith((
                    "STAGED_SUMMARY_BATCH_REQUEST\n",
                    "STAGED_SUMMARY_REDUCTION_REQUEST\n",
                ))
            )
            request = json.loads(request_message.split("\n", 1)[1])
            self.summary_instructions.append(request["instruction"])
            self.summary_requests.append(request["current_user_request"])
            is_correction = messages[-1]["content"].startswith(
                "STAGED_SUMMARY_CITATION_CORRECTION\n"
            )
            if is_correction:
                self.summary_citation_corrections += 1
            is_reduction = "reduction" in request
            if is_reduction:
                expected_root_ids = tuple(
                    self.note_ids_by_alias.get(root_id, root_id)
                    for root_id in request["reduction"]["expected_root_ids"]
                )
                supporting_note_id = request["reduction"][
                    "verified_findings"
                ][0]["findings"][0]["supporting_note_ids"][0]
                self.summary_reduction_calls += 1
            else:
                # The model sees short note IDs; the fixture keys its behaviour by the snapshot's ids.
                expected_root_ids = tuple(
                    self.note_ids_by_alias.get(root_id, root_id) for root_id in request["batch"]["expected_root_ids"]
                )
                self.summary_batch_payloads.append(request["batch"])
                first_tree = request["batch"]["result_trees"][0]
                # Deliberately naive: cite the first tree node, which may be a
                # structural placeholder, until asked to correct the citation.
                supporting_note_id = first_tree["note_id"]
                if is_correction and not self.ignore_summary_citation_corrections:
                    supporting_note_id = _first_evidence_note_id(first_tree)
                if self.summary_batch_citation_note_id != "":
                    # Cited as the model sees it: by its short ID when it was sent one.
                    alias_by_note_id = {note_id: alias for alias, note_id in self.note_ids_by_alias.items()}
                    supporting_note_id = alias_by_note_id.get(
                        self.summary_batch_citation_note_id, self.summary_batch_citation_note_id)
            self.summary_batch_calls.append(expected_root_ids)
            self.active_summary_calls += 1
            self.maximum_parallel_summary_calls = max(
                self.maximum_parallel_summary_calls,
                self.active_summary_calls,
            )
            try:
                await asyncio.sleep(
                    self.summary_delay_seconds_by_root_id.get(
                        expected_root_ids[0],
                        0.01,
                    )
                )
            finally:
                self.active_summary_calls -= 1
            self.summary_completion_order.append(expected_root_ids[0])
            if self.failed_summary_root_id in expected_root_ids and self.failed_summary_as_agent_error:
                raise AgentExecutionError(f"Fixture summary failure for {self.failed_summary_root_id}")
            if self.failed_summary_root_id in expected_root_ids:
                raise RuntimeError(
                    f"Fixture summary failure for {self.failed_summary_root_id}"
                )
            finding_text = f"Finding for {expected_root_ids[0]}"
            if self.large_summary_results and not is_reduction:
                finding_text = (finding_text + " detail") * 60
            supporting_note_ids = [supporting_note_id]
            if self.summary_batch_extra_citation_note_id != "" and not is_reduction:
                supporting_note_ids.append(self.summary_batch_extra_citation_note_id)
                if self.summary_ghost_only_root_id in expected_root_ids:
                    supporting_note_ids = [self.summary_batch_extra_citation_note_id]
            payload = {
                "findings": [{
                    "text": finding_text,
                    "supporting_note_ids": supporting_note_ids,
                }],
            }
            if response_model.__name__ == "SummaryBatchResult" and not self.omit_summary_coverage:
                payload["covered_root_ids"] = list(expected_root_ids)
            content = json.dumps(payload)
            response_model.model_validate_json(content)
            for streamed_text in (finding_text[: len(finding_text) // 2], finding_text):
                on_progress(
                    StructuredInferenceProgress(
                        phase="output_progress",
                        attempt=1,
                        max_attempts=2,
                        failure_kind="",
                        error_type="",
                        error_message="",
                        duration_ms=1.0,
                        wire_request={
                            "method": "POST",
                            "url": f"{base_url}/v1/chat/completions",
                            "body": {"model": model, "messages": messages},
                        },
                        output_tokens_received=len(streamed_text),
                        partial_output={"findings": [{"text": streamed_text}]},
                    )
                )
            return InferenceResponse(content=content, thinking="", usage={}, attempts=[])
        raise AssertionError(f"Unexpected structured request: {response_model.__name__}")

    async def stream_tool_turn(self, *, base_url, model, thinking_level, messages, tools,
                               on_request):
        del base_url, model, thinking_level
        assert self.agent_messages == [], "The summary operation ends the agent's turn"
        assert "summarize_view" in {tool.name for tool in tools}
        self.agent_messages = [dict(message) for message in messages]
        on_request({"messages": len(messages)})
        yield {"type": "tool_call", "id": "call-summary", "name": "summarize_view",
               "arguments": self.summary_tool_arguments}
        yield {"type": "done", "finish_reason": "tool_calls", "usage": {"prompt_tokens": 10_000}}

    async def stream_text(self, **arguments):
        self.final_messages = arguments["messages"]
        arguments["on_request"]({
            "method": "POST",
            "url": f'{arguments["base_url"]}/api/chat',
            "body": {
                "model": arguments["model"],
                "messages": arguments["messages"],
            },
        })
        text = "Answer [[child-a]]"
        final_request = arguments["messages"][-1]["content"]
        if self.final_cites_first_reference and final_request.startswith("FINAL_RESPONSE_REQUEST\n"):
            catalog = json.loads(final_request.split("\n", 1)[1])["reference_catalog"]
            # Split inside the token, as a stream does.
            token = catalog[0]["citation_token"]
            yield {"type": "content_delta", "text": "Answer " + token[:3]}
            yield {"type": "content_delta", "text": token[3:]}
            yield {"type": "done"}
            return
        yield {"type": "content_delta", "text": text}
        yield {"type": "done"}


def _runtime(inference: _FakeInference) -> AgentRuntime:
    return AgentRuntime(
        context_builder=AgentContextBuilder(),
        inference=inference,
        model_policy=SingleModelPolicy(),
        trace_store=AgentTraceStore(),
        # As in production (app/api/routes/ai.py, _agent_runtime): the adapter's own name.
        provider_label=inference.provider_label,
    )


def _first_evidence_note_id(tree: dict[str, object]) -> str:
    pending = [tree]
    while pending:
        node = pending.pop(0)
        if "content_text" in node:
            return node["note_id"]
        pending.extend(node["children"])
    raise AssertionError("Fixture tree has no evidence note")


def _summary_events(
    *,
    inference: _FakeInference,
    snapshot: ScopedSearchSnapshot,
    message: str,
    token_limit: int,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    _collect_summary_events(
        inference=inference, snapshot=snapshot, message=message, token_limit=token_limit, events=events,
    )
    return events


def _collect_summary_events(
    *,
    inference: _FakeInference,
    snapshot: ScopedSearchSnapshot,
    message: str,
    token_limit: int,
    events: list[dict[str, object]],
) -> None:
    """Append streamed events to ``events`` so callers can inspect them after a failure."""
    inference.note_ids_by_alias = NoteAliases.from_snapshot(snapshot).id_by_alias()

    async def collect() -> None:
        async for event in _runtime(inference).stream_agent(earlier_actions=[], 
            tagging_run=None,
            session_key="session-1",
            base_url="https://api.openai.com/v1",
            selected_model="gpt-5.6-sol",
            thinking_level="off",
            canonical_messages=[{"role": "user", "content": message}],
            prompts=DEFAULT_AGENT_PROMPTS,
            skills=DEFAULT_AGENT_SKILLS,
            retrieval_settings=AgentRetrievalSettings(
                max_page_approximate_tokens=token_limit,
            ),
            web_settings=DEFAULT_AGENT_WEB_SETTINGS,
            frozen_scope=snapshot,
        ):
            events.append(event)

    asyncio.run(collect())


def _final_payload(inference: _FakeInference) -> dict[str, object]:
    """The final request's payload with the short note IDs the model saw translated back."""
    payload = json.loads(inference.final_messages[-1]["content"].split("\n", 1)[1])
    aliases = NoteAliases(tuple(inference.note_ids_by_alias.values()))
    assert aliases.id_by_alias() == inference.note_ids_by_alias
    return aliases.unaliased(payload)


def _summary_progress(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [event for event in events if "operation" in event and event["operation"] == "summary"]


def _summary_snapshot(root_count: int) -> ScopedSearchSnapshot:
    roots = tuple(f"root-{index}" for index in range(root_count))
    notes = {
        root_id: _note(
            root_id,
            root_id,
            "",
            f"EVIDENCE_{index} " * 150,
            index,
        )
        for index, root_id in enumerate(roots)
    }
    nodes = {
        root_id: FrozenScopedTreeNode(
            note_id=root_id,
            parent_id="",
            root_note_id=root_id,
            child_ids=(),
        )
        for root_id in roots
    }
    return ScopedSearchSnapshot(
        run_id="summary-scope",
        session_key="session-1",
        descriptor=_descriptor(),
        created_at="2026-08-29T00:00:00+00:00",
        ordered_root_ids=roots,
        ordered_note_ids=roots,
        notes_by_id=MappingProxyType(notes),
        tree_nodes_by_id=MappingProxyType(nodes),
        note_records_at_send=MappingProxyType({}),
        disclosable_search_query=_descriptor().search_query,
        date_filter=None, file_filter=None,
        preparation_ms=0.0, text_extraction=TextExtractionMeter.start(),
        selected_note=NO_SELECTED_NOTE,
    )


def _multi_batch_summary_snapshot() -> ScopedSearchSnapshot:
    return _summary_snapshot(5)


# The summary goes straight to its batches (the maintainer, 2026-11-08: "skip this intermediate
# part and simply do the summary"): no question about scope, whatever it costs.
def test_a_many_batch_summary_goes_straight_to_its_batches_in_parallel() -> None:
    inference = _FakeInference()

    events = _summary_events(
        inference=inference,
        snapshot=_multi_batch_summary_snapshot(),
        message="Summarize all of these notes.",
        token_limit=900,
    )

    assert not any(event["type"] == "bulk_question" for event in events)
    assert len(inference.summary_batch_calls) == 5
    assert inference.summary_batch_calls[0] == ("root-0",)
    assert inference.maximum_parallel_summary_calls >= 2
    final_payload = _final_payload(inference)
    assert final_payload["evidence_coverage"]["omitted_result_tree_count"] == 0
    assert tuple(
        root_id
        for summary in final_payload["authoritative_batch_findings"]
        for root_id in summary["covered_root_ids"]
    ) == _multi_batch_summary_snapshot().ordered_root_ids


# Every provider MetaList offers reaches the final answer: a summary once failed under
# Claude because the final answer's length limit was looked up by the name "OpenAI".
@pytest.mark.parametrize("provider_label", [entry.label for entry in AI_CATALOG.values()])
def test_a_summary_reaches_its_final_answer_with_every_provider(provider_label: str) -> None:
    inference = _FakeInference()
    inference.provider_label = provider_label
    events = _summary_events(
        inference=inference,
        snapshot=_multi_batch_summary_snapshot(),
        message="Summarize all of these notes.",
        token_limit=900,
    )
    assert [event for event in events if event["type"] == "error"] == []
    assert inference.final_messages, "the final answer was asked for"


def test_summary_progress_is_a_percentage_starting_above_zero() -> None:
    inference = _FakeInference()

    events = _summary_events(
        inference=inference,
        snapshot=_summary_snapshot(11),
        message="Summarize every note in this scope.",
        token_limit=900,
    )

    summarizing = [event for event in _summary_progress(events) if event["label"].startswith("Summarizing")]
    percents = [event["percent"] for event in summarizing]
    assert percents[0] == 5
    assert percents == sorted(percents)
    assert percents[-1] == 100
    assert [event["label"] for event in summarizing] == [f"Summarizing · {int(percent)}%" for percent in percents]
    # Started, first response, finished: the fixture streams twice, and counts once.
    assert len(summarizing) == 33
    assert inference.maximum_parallel_summary_calls == 4
    for event in _summary_progress(events):
        assert "batch" not in event["label"].replace("batch summaries for final", "")
        assert "summary_batch_preview" not in event


_SUMMARY_MODEL_KEY = ("https://api.openai.com/v1", "gpt-5.6-sol")


def _timing_plan(root_count: int, limit: int, *, with_timing_probes: bool):
    state = InvestigationState.start(
        snapshot=_summary_snapshot(root_count),
        settings=AgentRetrievalSettings(max_page_approximate_tokens=limit),
    )
    return state.plan_complete_root_batches(reserved_approximate_tokens=0, with_timing_probes=with_timing_probes)


def test_timing_probes_are_a_tenth_and_a_fifth_of_a_batch_and_every_root_stays_in_order() -> None:
    plain = _timing_plan(120, 40_000, with_timing_probes=False)
    plan = _timing_plan(120, 40_000, with_timing_probes=True)

    sizes = [batch.returned_approximate_token_count for batch in plan.batches]
    assert 0 < sizes[0] <= 4_000
    assert 4_000 < sizes[1] <= 8_000
    assert sizes[1] > sizes[0] * 1.5
    assert all(size <= 40_000 for size in sizes[2:])
    assert max(sizes[2:]) > 8_000
    assert len(plan.batches) > len(plain.batches)
    assert tuple(root for batch in plan.batches for root in batch.result_tree_ids) == tuple(
        root for batch in plain.batches for root in batch.result_tree_ids)


def test_a_view_that_fits_one_batch_gets_no_timing_probes() -> None:
    assert len(_timing_plan(3, 40_000, with_timing_probes=True).batches) == 1


def test_a_root_larger_than_a_timing_probe_stands_alone_instead_of_failing() -> None:
    plan = _timing_plan(5, 900, with_timing_probes=True)
    assert [batch.result_tree_ids for batch in plan.batches] == [(f"root-{index}",) for index in range(5)]


def test_a_model_with_no_saved_timing_starts_with_two_small_real_batches(saved_model_timings) -> None:
    inference = _FakeInference()

    _summary_events(
        inference=inference,
        snapshot=_summary_snapshot(120),
        message="Summarize every note in this scope.",
        token_limit=40_000,
    )

    assert len(saved_model_timings.saves) == 1
    final_payload = _final_payload(inference)
    roots = [len(summary["covered_root_ids"]) for summary in final_payload["authoritative_batch_findings"]]
    assert roots[0] < roots[1] < roots[2]
    assert sum(roots) == 120


def test_a_model_with_saved_timing_splits_normally_and_saves_the_new_timing(saved_model_timings) -> None:
    earlier = ModelTiming(startup_seconds=1.0, seconds_per_million_tokens=1.0)
    saved_model_timings.saved[_SUMMARY_MODEL_KEY] = earlier
    inference = _FakeInference()

    _summary_events(
        inference=inference,
        snapshot=_summary_snapshot(120),
        message="Summarize every note in this scope.",
        token_limit=40_000,
    )

    final_payload = _final_payload(inference)
    roots = [len(summary["covered_root_ids"]) for summary in final_payload["authoritative_batch_findings"]]
    assert roots[0] == roots[1]
    assert saved_model_timings.saved[_SUMMARY_MODEL_KEY] != earlier


def test_a_failed_summary_saves_no_timing(saved_model_timings) -> None:
    inference = _FakeInference()
    inference.failed_summary_root_id = "root-0"

    with pytest.raises(RuntimeError, match="Fixture summary failure for root-0"):
        _collect_summary_events(
            inference=inference,
            snapshot=_multi_batch_summary_snapshot(),
            message="Summarize all of these notes.",
            token_limit=900,
            events=[],
        )

    assert saved_model_timings.saves == []


def test_with_saved_timing_the_bar_moves_while_batches_are_still_reading(saved_model_timings, monkeypatch) -> None:
    monkeypatch.setattr(runtime_module, "_SUMMARY_PROGRESS_TICK_SECONDS", 0.005)
    saved_model_timings.saved[_SUMMARY_MODEL_KEY] = ModelTiming(startup_seconds=0.1, seconds_per_million_tokens=1.0)
    inference = _FakeInference()
    inference.summary_delay_seconds_by_root_id = {f"root-{index}": 0.06 for index in range(11)}

    events = _summary_events(
        inference=inference,
        snapshot=_summary_snapshot(11),
        message="Summarize every note in this scope.",
        token_limit=900,
    )

    summarizing = [event for event in _summary_progress(events) if event["label"].startswith("Summarizing")]
    percents = [event["percent"] for event in summarizing]
    # Three events per batch are the batch's own; the rest are the clock moving the bar.
    assert len(summarizing) > 33
    assert percents == sorted(percents)
    assert percents[-1] == 100


def test_with_no_timing_at_all_the_bar_still_moves_before_any_batch_answers(monkeypatch) -> None:
    monkeypatch.setattr(runtime_module, "_SUMMARY_PROGRESS_TICK_SECONDS", 0.005)
    inference = _FakeInference()
    inference.summary_delay_seconds_by_root_id = {f"root-{index}": 0.06 for index in range(5)}

    events = _summary_events(
        inference=inference,
        snapshot=_multi_batch_summary_snapshot(),
        message="Summarize every note in this scope.",
        token_limit=900,
    )

    summarizing = [event for event in _summary_progress(events) if event["label"].startswith("Summarizing")]
    # Three events per batch are the batch's own; the rest are the bar creeping.
    assert len(summarizing) > 15


def test_a_streamed_answer_does_not_recount_its_whole_request(monkeypatch) -> None:
    # The maintainer, 2026-11-08: the bar froze for 20 seconds. Counting a 500,000-token request
    # for every few words streamed held the event loop, and with it every progress event.
    counted: list[object] = []
    monkeypatch.setattr(
        runtime_module.AgentRuntime, "_wire_request_input_tokens",
        staticmethod(lambda wire_request: counted.append(wire_request) or 1),
    )

    _summary_events(
        inference=_FakeInference(),
        snapshot=_multi_batch_summary_snapshot(),
        message="Summarize all of these notes.",
        token_limit=900,
    )

    assert counted == []


def test_batches_finishing_out_of_order_are_synthesized_in_canonical_order() -> None:
    inference = _FakeInference()
    snapshot = _multi_batch_summary_snapshot()
    inference.summary_delay_seconds_by_root_id = {
        "root-1": 0.08,
        "root-2": 0.06,
        "root-3": 0.04,
        "root-4": 0.01,
    }

    events = _summary_events(
        inference=inference,
        snapshot=snapshot,
        message="Summarize every note in this scope.",
        token_limit=900,
    )

    assert inference.summary_completion_order == ["root-0", "root-4", "root-3", "root-2", "root-1"]
    final_payload = _final_payload(inference)
    assert tuple(
        root_id
        for summary in final_payload["authoritative_batch_findings"]
        for root_id in summary["covered_root_ids"]
    ) == snapshot.ordered_root_ids


def test_closing_staged_summary_stream_cancels_running_batch_workers() -> None:
    inference = _FakeInference()
    inference.summary_delay_seconds_by_root_id = {
        root_id: 5.0 for root_id in ("root-1", "root-2", "root-3", "root-4")
    }

    async def run() -> None:
        stream = _runtime(inference).stream_agent(earlier_actions=[], 
            tagging_run=None,
            session_key="session-1",
            base_url="https://api.openai.com/v1",
            selected_model="gpt-5.6-sol",
            thinking_level="off",
            canonical_messages=[{"role": "user", "content": "Summarize all notes."}],
            prompts=DEFAULT_AGENT_PROMPTS,
            skills=DEFAULT_AGENT_SKILLS,
            retrieval_settings=AgentRetrievalSettings(max_page_approximate_tokens=900),
            web_settings=DEFAULT_AGENT_WEB_SETTINGS,
            frozen_scope=_multi_batch_summary_snapshot(),
        )
        progress_events = 0
        async for event in stream:
            progress_events += "operation" in event and event["operation"] == "summary"
            if progress_events == 2:
                break
        await stream.aclose()
        await asyncio.sleep(0)
        assert inference.active_summary_calls == 0

    asyncio.run(asyncio.wait_for(run(), timeout=2.0))
    assert inference.final_messages == []


def test_when_a_summary_batch_fails_later_batches_do_not_start() -> None:
    inference = _FakeInference()
    inference.failed_summary_root_id = "root-0"
    events: list[dict[str, object]] = []

    with pytest.raises(RuntimeError, match="Fixture summary failure for root-0"):
        _collect_summary_events(
            inference=inference,
            snapshot=_multi_batch_summary_snapshot(),
            message="Summarize all of these notes.",
            token_limit=900,
            events=events,
        )

    # Batches 1-4 started together; batch 1 failed, the others finished, batch 5 never started.
    assert sorted(inference.summary_batch_calls) == [(f"root-{index}",) for index in range(4)]
    assert inference.final_messages == []


def test_with_room_in_the_provider_limits_every_later_summary_batch_goes_at_once(monkeypatch) -> None:
    # Until 2026-11-07 a summary sent at most four batches at a time, whatever the account allowed.
    monkeypatch.setattr(provider_limits, "_GATES", {})
    provider_limits.gate_for(base_url="https://api.openai.com/v1", model="gpt-5.6-sol").record(
        provider_limits.ProviderLimits(
            request_limit=30_000, remaining_requests=30_000, requests_reset_at=time.monotonic() + 60,
            token_limit=180_000_000, remaining_tokens=180_000_000, tokens_reset_at=time.monotonic() + 60))
    inference = _FakeInference()

    _summary_events(
        inference=inference,
        snapshot=_summary_snapshot(11),
        message="Summarize every note in this scope.",
        token_limit=900,
    )

    assert len(inference.summary_batch_calls) == 11
    # Every batch together from the start. Until 2026-11-08 batch 1 ran alone first, to seed the
    # provider's prompt cache: the shared prefix is a small share of each batch, and the wait was
    # a whole batch (the maintainer: "why are we not simply doing all of the batches in parallel").
    assert inference.maximum_parallel_summary_calls == 11


def test_complete_scope_summary_has_no_total_batch_cap_and_runs_four_at_once_until_the_limits_are_known() -> None:
    inference = _FakeInference()
    snapshot = _summary_snapshot(11)

    events = _summary_events(
        inference=inference,
        snapshot=snapshot,
        message="Summarize every note in this scope.",
        token_limit=900,
    )

    assert len(inference.summary_batch_calls) == 11
    assert inference.maximum_parallel_summary_calls == 4
    final_payload = _final_payload(inference)
    assert tuple(
        root_id
        for summary in final_payload["authoritative_batch_findings"]
        for root_id in summary["covered_root_ids"]
    ) == snapshot.ordered_root_ids


def test_summary_coverage_is_attached_by_application_instead_of_echoed_by_model() -> None:
    inference = _FakeInference()
    inference.omit_summary_coverage = True
    snapshot = _multi_batch_summary_snapshot()

    _summary_events(
        inference=inference,
        snapshot=snapshot,
        message="Summarize every note in this scope.",
        token_limit=900,
    )

    final_payload = _final_payload(inference)
    assert tuple(
        root_id
        for summary in final_payload["authoritative_batch_findings"]
        for root_id in summary["covered_root_ids"]
    ) == snapshot.ordered_root_ids


def test_summary_batches_and_consolidation_keep_note_ids_out_of_the_finding_text() -> None:
    # The system prompt asks for [[note_id]] citations in answers; a batch
    # finding once followed that and left out its required supporting_note_ids.
    inference = _FakeInference()
    _summary_events(
        inference=inference,
        snapshot=_multi_batch_summary_snapshot(),
        message="Summarize every note in this scope.",
        token_limit=900,
    )
    assert inference.summary_instructions != []
    for instruction in inference.summary_instructions:
        assert "Put note IDs only in supporting_note_ids" in instruction
        assert "must not contain [[note_id]] citations" in instruction


def test_single_payload_scope_summary_starts_without_a_question() -> None:
    # One payload is one ordinary model call: nothing to choose, so no dialog.
    inference = _FakeInference()

    events = _summary_events(
        inference=inference,
        snapshot=_snapshot(large_tail=False),
        message="Summarize all of these notes.",
        token_limit=24_000,
    )

    assert not any(event["type"] in {"bulk_question", "bulk_complete"} for event in events)
    assert inference.summary_batch_calls == []
    assert inference.final_messages
    assert any(event["type"] == "done" for event in events)


def test_staged_summary_recursively_reduces_large_intermediate_findings() -> None:
    inference = _FakeInference()
    inference.large_summary_results = True

    events = _summary_events(
        inference=inference,
        snapshot=_multi_batch_summary_snapshot(),
        message="Summarize all of these notes.",
        token_limit=900,
    )

    assert inference.summary_reduction_calls > 0
    assert any(
        event["label"] == "Condensing batch summaries for final synthesis"
        for event in events if "label" in event
    )
    final_payload = _final_payload(inference)
    assert final_payload["evidence_coverage"]["omitted_result_tree_count"] == 0


def test_staged_summary_failure_cancels_remaining_work_and_never_synthesizes() -> None:
    inference = _FakeInference()
    inference.failed_summary_root_id = "root-1"

    with pytest.raises(RuntimeError, match="Fixture summary failure for root-1"):
        _summary_events(
            inference=inference,
            snapshot=_multi_batch_summary_snapshot(),
            message="Summarize all of these notes.",
            token_limit=900,
        )

    assert inference.active_summary_calls == 0
    assert inference.final_messages == []


def _selected_note_outside_summary_scope() -> SelectedNoteContext:
    return SelectedNoteContext(
        "available",
        "selected-child",
        (
            SelectedTreeNote("selected-root", "", "SELECTED_ROOT_CONTEXT", ""),
            SelectedTreeNote(
                "selected-child",
                "selected-root",
                "SELECTED_CHILD_CONTEXT",
                "",
            ),
        ),
        unavailable_reason="",
    )


def test_staged_summary_batch_may_cite_permitted_selected_note_context() -> None:
    inference = _FakeInference()
    inference.summary_batch_citation_note_id = "selected-child"
    snapshot = replace(
        _multi_batch_summary_snapshot(),
        selected_note=_selected_note_outside_summary_scope(),
    )
    assert "selected-child" not in snapshot.ordered_note_ids

    events = _summary_events(
        inference=inference,
        snapshot=snapshot,
        message="Summarize all of these notes.",
        token_limit=900,
    )

    assert len(inference.summary_batch_calls) > 1
    final_payload = _final_payload(inference)
    assert "selected-child" in [
        entry["note_id"] for entry in final_payload["reference_catalog"]
    ]
    assert any(event["type"] == "done" for event in events)


def test_staged_summary_final_catalog_includes_permitted_selected_note_tree() -> None:
    inference = _FakeInference()
    snapshot = replace(
        _multi_batch_summary_snapshot(),
        selected_note=_selected_note_outside_summary_scope(),
    )

    _summary_events(
        inference=inference,
        snapshot=snapshot,
        message="Summarize all of these notes.",
        token_limit=900,
    )

    final_payload = _final_payload(inference)
    catalog_ids = [entry["note_id"] for entry in final_payload["reference_catalog"]]
    assert {"selected-root", "selected-child"} <= set(catalog_ids)
    assert catalog_ids.index("root-0") < catalog_ids.index("selected-root")


def _structural_root_summary_snapshot(root_count: int) -> ScopedSearchSnapshot:
    """Search matches only children; each root is structure without disclosed content."""
    roots = tuple(f"heading-{index}" for index in range(root_count))
    matches = tuple(f"match-{index}" for index in range(root_count))
    notes = {
        match_id: _note(match_id, root_id, root_id, f"EVIDENCE_{index} " * 150, index)
        for index, (root_id, match_id) in enumerate(zip(roots, matches))
    }
    nodes: dict[str, FrozenScopedTreeNode] = {}
    for root_id, match_id in zip(roots, matches):
        nodes[root_id] = FrozenScopedTreeNode(
            note_id=root_id,
            parent_id="",
            root_note_id=root_id,
            child_ids=(match_id,),
        )
        nodes[match_id] = FrozenScopedTreeNode(
            note_id=match_id,
            parent_id=root_id,
            root_note_id=root_id,
            child_ids=(),
        )
    return ScopedSearchSnapshot(
        run_id="structural-summary-scope",
        session_key="session-1",
        descriptor=_descriptor(),
        created_at="2026-08-29T00:00:00+00:00",
        ordered_root_ids=roots,
        ordered_note_ids=matches,
        notes_by_id=MappingProxyType(notes),
        tree_nodes_by_id=MappingProxyType(nodes),
        note_records_at_send=MappingProxyType({}),
        disclosable_search_query=_descriptor().search_query,
        date_filter=None, file_filter=None,
        preparation_ms=0.0, text_extraction=TextExtractionMeter.start(),
        selected_note=NO_SELECTED_NOTE,
    )


def test_staged_summary_asks_once_to_correct_structural_placeholder_citations() -> None:
    inference = _FakeInference()
    snapshot = _structural_root_summary_snapshot(5)

    events = _summary_events(
        inference=inference,
        snapshot=snapshot,
        message="Summarize all of these notes.",
        token_limit=900,
    )

    batch_count = len(set(inference.summary_batch_calls))
    assert batch_count > 1
    assert inference.summary_citation_corrections == batch_count
    final_payload = _final_payload(inference)
    catalog_ids = {entry["note_id"] for entry in final_payload["reference_catalog"]}
    assert catalog_ids == set(snapshot.ordered_note_ids)
    assert not catalog_ids & set(snapshot.ordered_root_ids)
    assert any(event["type"] == "done" for event in events)


def test_staged_summary_reports_structural_citation_after_failed_correction() -> None:
    inference = _FakeInference()
    inference.ignore_summary_citation_corrections = True

    with pytest.raises(
        AgentExecutionError,
        match=(
            "Summary batch 1 returned invalid findings: .*even after a correction "
            "request: heading-0 \\(structural placeholder without disclosed content\\)"
        ),
    ):
        _summary_events(
            inference=inference,
            snapshot=_structural_root_summary_snapshot(5),
            message="Summarize all of these notes.",
            token_limit=900,
        )

    # One correction each for the four batches started together; the fifth never started.
    assert inference.summary_citation_corrections == 4
    assert inference.final_messages == []


class _RecordedTraceStore(AgentTraceStore):
    """The trace the diagnostics show, with every event kept for the test to read."""

    events: list[dict[str, object]] = []

    def append_event(self, **event: object) -> None:
        _RecordedTraceStore.events.append(event)
        super().append_event(**event)


# A private or unavailable selected note is never sent, so a citation to it is a citation to a
# note the batch never saw: dropped after the correction (2026-11-08; until then it stopped the
# summary, because the correction request quoted the ID back). Either way it is never cited.
@pytest.mark.parametrize(
    "unavailable_reason",
    ["blacklisted", "search_redacted", "password_protected", "username_protected", "not_whitelisted"],
)
def test_staged_summary_never_cites_unavailable_selected_notes(
    unavailable_reason: str, monkeypatch,
) -> None:
    _RecordedTraceStore.events = []
    monkeypatch.setattr(sys.modules[__name__], "AgentTraceStore", _RecordedTraceStore)
    inference = _FakeInference()
    inference.summary_batch_citation_note_id = "selected-child"
    snapshot = replace(
        _multi_batch_summary_snapshot(),
        selected_note=SelectedNoteContext(
            "unavailable",
            "",
            (),
            unavailable_reason,
        ),
    )

    events = _summary_events(
        inference=inference,
        snapshot=snapshot,
        message="Summarize all of these notes.",
        token_limit=900,
    )

    assert "SELECTED_CHILD_CONTEXT" not in json.dumps(inference.agent_messages)
    assert events[-1]["type"] == "done"
    assert "selected-child" not in json.dumps(inference.final_messages)
    dropped = [event for event in _RecordedTraceStore.events if event["event_type"] == "SUMMARY_CITATIONS_DROPPED"]
    assert dropped and all(event["detail"]["dropped_note_ids"] == ["selected-child"] for event in dropped)


def _active_skill_ids(messages: list[dict[str, str]]) -> list[str]:
    return [
        message["content"].split("\n", 1)[0].removeprefix("ACTIVE_SKILL ")
        for message in messages
        if message["role"] == "system" and message["content"].startswith("ACTIVE_SKILL ")
    ]


def test_a_single_payload_summary_sends_the_summary_skill() -> None:
    inference = _FakeInference()

    _summary_events(
        inference=inference,
        snapshot=_snapshot(large_tail=False),
        message="Summarize all of these notes.",
        token_limit=24_000,
    )

    assert inference.summary_batch_calls == []
    assert _active_skill_ids(inference.final_messages) == ["staged_summary_v1"]


def test_a_summary_never_blocks_other_changes() -> None:
    # A summary only reads notes: while its batches run, editing notes (or
    # anything else) stays allowed.
    inference = _FakeInference()
    blocked_while_running: list[str] = []

    async def collect() -> None:
        async for event in _runtime(inference).stream_agent(earlier_actions=[], 
            tagging_run=None,
            session_key="session-1",
            base_url="https://api.openai.com/v1",
            selected_model="gpt-5.6-sol",
            thinking_level="off",
            canonical_messages=[{"role": "user", "content": "Summarize all of these notes."}],
            prompts=DEFAULT_AGENT_PROMPTS,
            skills=DEFAULT_AGENT_SKILLS,
            retrieval_settings=AgentRetrievalSettings(max_page_approximate_tokens=900),
            web_settings=DEFAULT_AGENT_WEB_SETTINGS,
            frozen_scope=_multi_batch_summary_snapshot(),
        ):
            if bulk_operation_guard.operation_id:
                blocked_while_running.append(str(event["type"]))

    asyncio.run(collect())
    assert blocked_while_running == []
    assert inference.summary_batch_calls



# Resumable whole-view summaries (summary_batch_store.py): a failed summary keeps
# its finished batches, and continuing it runs only the rest.

@pytest.fixture(autouse=True)
def _clear_kept_summary_batches():
    summary_batch_store.reset()
    yield
    summary_batch_store.reset()


_ORIGINAL_SUMMARY_REQUEST = "What is a high-level summary of all my notes?"


def _summary_run(
    *, inference: _FakeInference, snapshot: ScopedSearchSnapshot, message: str, selected_model: str,
    events: list[dict[str, object]],
) -> None:
    inference.note_ids_by_alias = NoteAliases.from_snapshot(snapshot).id_by_alias()

    async def collect() -> None:
        async for event in _runtime(inference).stream_agent(
            earlier_actions=[], tagging_run=None, session_key="session-1",
            base_url="https://api.openai.com/v1", selected_model=selected_model, thinking_level="off",
            canonical_messages=[{"role": "user", "content": message}],
            prompts=DEFAULT_AGENT_PROMPTS, skills=DEFAULT_AGENT_SKILLS,
            retrieval_settings=AgentRetrievalSettings(max_page_approximate_tokens=900),
            web_settings=DEFAULT_AGENT_WEB_SETTINGS, frozen_scope=snapshot,
        ):
            events.append(event)

    asyncio.run(collect())


def _failed_summary_of_seven_roots() -> _FakeInference:
    """Roots 0-3 at once (four until the limits are known): root-2 fails first while 0, 1 and 3 finish."""
    inference = _FakeInference()
    inference.failed_summary_root_id = "root-2"
    inference.failed_summary_as_agent_error = True
    inference.summary_delay_seconds_by_root_id = {"root-0": 0.2, "root-1": 0.2, "root-3": 0.2}
    events: list[dict[str, object]] = []
    with pytest.raises(AgentExecutionError) as failure:
        _summary_run(inference=inference, snapshot=_summary_snapshot(7), message=_ORIGINAL_SUMMARY_REQUEST,
                     selected_model="gpt-5.6-sol", events=events)
    inference.failure_message = str(failure.value)
    return inference


def _continuing(snapshot: ScopedSearchSnapshot, selected_model: str, continues: bool) -> tuple[_FakeInference, list[dict[str, object]]]:
    inference = _FakeInference()
    inference.summary_tool_arguments = json.dumps({"continues_failed_summary": continues})
    events: list[dict[str, object]] = []
    _summary_run(inference=inference, snapshot=snapshot, message="try that again",
                 selected_model=selected_model, events=events)
    return inference, events


def test_a_failed_batch_keeps_the_finished_ones_and_starts_no_more() -> None:
    inference = _failed_summary_of_seven_roots()

    # The batches already running finished; the two still queued never started.
    assert sorted(inference.summary_batch_calls) == [("root-0",), ("root-1",), ("root-2",), ("root-3",)]
    kept = summary_batch_store.kept(session_key="session-1")
    assert kept is not None
    assert kept.request == _ORIGINAL_SUMMARY_REQUEST
    assert len(kept.results) == 3
    assert "3 of 7 batches finished and were kept" in inference.failure_message


def test_continuing_reuses_the_kept_batches_and_runs_only_the_rest_with_the_original_question() -> None:
    _failed_summary_of_seven_roots()

    inference, events = _continuing(_summary_snapshot(7), "gpt-5.6-sol", True)

    assert sorted(inference.summary_batch_calls) == [("root-2",), ("root-4",), ("root-5",), ("root-6",)]
    assert set(inference.summary_requests) == {_ORIGINAL_SUMMARY_REQUEST}
    assert not any(event["type"] == "bulk_question" for event in events)
    assert any("label" in event and event["label"] == "Reusing your earlier attempt" for event in events)
    final_payload = _final_payload(inference)
    assert [root for summary in final_payload["authoritative_batch_findings"] for root in summary["covered_root_ids"]] == [
        f"root-{index}" for index in range(7)
    ]
    assert events[-1]["type"] == "done"
    # A successful summary drops what was kept.
    assert summary_batch_store.kept(session_key="session-1") is None


def test_a_new_summary_question_does_not_reuse_kept_batches() -> None:
    _failed_summary_of_seven_roots()

    inference, _events = _continuing(_summary_snapshot(7), "gpt-5.6-sol", False)

    assert sorted(inference.summary_batch_calls) == [(f"root-{index}",) for index in range(7)]
    assert set(inference.summary_requests) == {"try that again"}


def test_an_edited_note_reruns_its_batch_when_continuing() -> None:
    _failed_summary_of_seven_roots()
    snapshot = _summary_snapshot(7)
    edited = replace(snapshot.notes_by_id["root-3"], note_text=NoteText.from_text("EDITED " * 150))
    snapshot = replace(snapshot, notes_by_id=MappingProxyType({**snapshot.notes_by_id, "root-3": edited}))

    inference, _events = _continuing(snapshot, "gpt-5.6-sol", True)

    assert sorted(inference.summary_batch_calls) == [("root-2",), ("root-3",), ("root-4",), ("root-5",), ("root-6",)]


def test_a_different_model_reruns_every_batch_when_continuing() -> None:
    _failed_summary_of_seven_roots()

    inference, _events = _continuing(_summary_snapshot(7), "gpt-5.6-luna", True)

    assert sorted(inference.summary_batch_calls) == [(f"root-{index}",) for index in range(7)]


# BUG (2026-11-08): a summary of 10,087 notes failed at batch 3 of 17 because the model cited a
# note ID it was never sent ("does not appear anywhere in the request"), and again after the
# correction. Such a citation can link to nothing: it is dropped, with the finding if it was its
# only one, listed in the diagnostics, and the summary goes on.
def test_citations_to_notes_a_batch_was_never_sent_are_dropped_after_the_correction(monkeypatch) -> None:
    _RecordedTraceStore.events = []
    monkeypatch.setattr(sys.modules[__name__], "AgentTraceStore", _RecordedTraceStore)
    inference = _FakeInference()
    inference.summary_batch_extra_citation_note_id = "ghost-note"
    inference.summary_ghost_only_root_id = "root-1"
    snapshot = _multi_batch_summary_snapshot()

    events = _summary_events(
        inference=inference, snapshot=snapshot, message="Summarize all of these notes.",
        token_limit=900,
    )

    assert [event for event in events if event["type"] == "error"] == []
    assert events[-1]["type"] == "done"
    batch_count = len(snapshot.ordered_root_ids)
    # The correction was still asked for first, once per batch.
    assert inference.summary_citation_corrections == batch_count
    final_payload = _final_payload(inference)
    batches = final_payload["authoritative_batch_findings"]
    cited = [note_id for batch in batches for finding in batch["findings"] for note_id in finding["supporting_note_ids"]]
    assert "ghost-note" not in cited
    findings_by_root = {batch["covered_root_ids"][0]: batch["findings"] for batch in batches}
    assert findings_by_root["root-1"] == [], "a finding that cited only the unknown note is dropped"
    assert all(len(findings) == 1 for root_id, findings in findings_by_root.items() if root_id != "root-1")
    dropped = [event for event in _RecordedTraceStore.events if event["event_type"] == "SUMMARY_CITATIONS_DROPPED"]
    assert len(dropped) == batch_count
    assert all(event["detail"]["dropped_note_ids"] == ["ghost-note"] for event in dropped)
    assert sorted(event["detail"]["dropped_finding_count"] for event in dropped) == [0] * (batch_count - 1) + [1]


# The model miscopies 36-character note ids now and then (a summary of 10,087 notes failed on
# one, 2026-11-08): summary batches, reductions and the final answer see the chat's short note
# IDs (n1, n2…), and the answer the user gets cites the real notes.
def test_summary_requests_carry_short_note_ids_and_the_answer_cites_real_notes() -> None:
    inference = _FakeInference()
    inference.final_cites_first_reference = True
    snapshot = _multi_batch_summary_snapshot()
    aliases = NoteAliases.from_snapshot(snapshot)

    events = _summary_events(
        inference=inference, snapshot=snapshot, message="Summarize all of these notes.",
        token_limit=900,
    )

    assert events[-1]["type"] == "done"
    assert len(inference.summary_batch_payloads) == len(snapshot.ordered_root_ids)
    for batch in inference.summary_batch_payloads:
        assert all(ALIAS_RE.match(root_id) for root_id in batch["expected_root_ids"])
        tree_ids = [node["note_id"] for tree in batch["result_trees"] for node in _tree_nodes(tree)]
        assert tree_ids and all(ALIAS_RE.match(note_id) for note_id in tree_ids)
    final_payload = json.loads(inference.final_messages[-1]["content"].split("\n", 1)[1])
    catalog = final_payload["reference_catalog"]
    assert all(ALIAS_RE.match(entry["note_id"]) and entry["citation_token"] == f"[[{entry['note_id']}]]" for entry in catalog)
    assert all(ALIAS_RE.match(note_id) for batch in final_payload["authoritative_batch_findings"]
               for finding in batch["findings"] for note_id in finding["supporting_note_ids"])
    first_note_id = aliases.note_id(catalog[0]["note_id"])
    answer = "".join(event["text"] for event in events if event["type"] == "content_delta")
    assert f"[[{first_note_id}]]" in answer
    assert "[[n" not in answer


def _tree_nodes(tree: dict[str, object]) -> list[dict[str, object]]:
    nodes = [tree]
    for child in tree.get("children", []):
        nodes.extend(_tree_nodes(child))
    return nodes
