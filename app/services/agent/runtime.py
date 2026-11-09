"""Explicit application-owned execution loop for read-only PKMS agents."""

from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
import math
import time
from collections.abc import AsyncIterator
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from pydantic import BaseModel

from app.services.agent.failure_explanations import FailureSetup, explain_structured_failure
from app.services.agent.context import AgentContextBuilder
from app.services.agent.context import serialize_investigation_evidence_payload
from app.services.agent.inference import InferenceAdapter
from app.services.agent.inference import InferenceAttempt
from app.services.agent.inference import InferenceContextWindow
from app.services.agent.inference import InferenceProviderError
from app.services.agent.inference import InferenceResponse
from app.services.agent.inference import StructuredInferenceProgress
from app.services.agent.inference import StructuredInferenceError
from app.services.agent.investigation import InvestigationEvidencePayload
from app.services.agent.agent_loop import AgentLoopMixin
from app.services.agent.execution_errors import AgentExecutionError
from app.services.agent.investigation import InvestigationState
from app.services.agent.investigation import CompleteRootBatchPlan
from app.services.agent.model_policy import InferencePurpose
from app.services.agent.model_policy import SingleModelPolicy
from app.services.agent.note_aliases import NoteAliases
from app.services.agent.staged_summary import SummaryBatchResult
from app.services.agent.staged_summary import SummaryFindingsResult
from app.services.agent.summary_batch_store import summary_batch_key
from app.services.agent.summary_batch_store import summary_batch_store
from app.services.agent.staged_summary import attach_summary_coverage
from app.services.agent.staged_summary import UNCITABLE_ABSENT_FROM_REQUEST
from app.services.agent.staged_summary import classify_uncitable_note_ids
from app.services.agent.staged_summary import drop_citations
from app.services.agent.staged_summary import estimate_summary_results_tokens
from app.services.agent.staged_summary import partition_summary_results
from app.services.agent.staged_summary import structural_placeholder_note_ids
from app.services.agent.staged_summary import summary_reference_note_ids
from app.services.agent.saved_rate_limits import DatabaseSavedTimings
from app.services.agent.staged_summary import ModelTiming
from app.services.agent.staged_summary import advanced_progress_percent
from app.services.agent.staged_summary import SUMMARY_PROGRESS_COMPLETE_PERCENT
from app.services.agent.staged_summary import fit_model_timing
from app.services.agent.staged_summary import summary_progress_percent
from app.services.agent.prompt_settings import AgentPromptSet
from app.services.agent.retrieval_settings import AgentRetrievalSettings
from app.services.agent.skill_settings import AgentSkill
from app.services.agent.skill_settings import AgentSkillSet
from app.services.agent.scope import ScopedSearchSnapshot
from app.services.agent.scope import describe_text_extraction
from app.services.agent.scope import read_notes_off_request_loop
from app.services.agent.provider_limits import gate_for
from app.services.agent.structured_inference import structured_max_output_tokens
from app.services.agent.token_estimation import estimate_input_tokens
from app.services.agent.token_estimation import estimate_message_tokens
from app.services.agent.token_estimation import estimate_text_tokens
from app.services.agent.trace import AgentTraceStore
from app.services.agent.web_settings import AgentWebSettings
from app.services.agent.web_capabilities import build_web_url_capabilities
from app.services.agent.web_evidence import WebPageEvidence
from app.services.agent.web_evidence import citation_references_for_pages
from app.services.agent.web_evidence import web_evidence_store
from app.services.agent.history import record_history
from app.services.agent.ai_send import send_structured
from app.services.agent.ai_send import send_text_stream
from app.utils.time_units import MS_PER_SECOND


_MAX_STAGED_SUMMARY_REDUCTION_LEVELS = 8
# One batch is a plain summary; staging starts at two.
_MIN_STAGED_SUMMARY_BATCHES = 2
# The final response is retried once after a provider failure that produced no output.
_FINAL_RESPONSE_MAX_ATTEMPTS = 2
# One corrective request when a summary cites IDs that were not disclosed as evidence.
_SUMMARY_CITATION_CORRECTIONS = 1
# Streamed batch previews are throttled per batch and trimmed to a compact tail.
# While the final response streams, its output-token count is reported again
# after at least this many more tokens.
_OUTPUT_PROGRESS_REPORT_TOKENS = 8



# How often a running summary's bar is moved by the clock.
_SUMMARY_PROGRESS_TICK_SECONDS = 0.5
# The bar's value is sent to a tenth of a percent: it moves in small steps.
_SUMMARY_PROGRESS_DECIMALS = 1
_SAVED_TIMINGS = DatabaseSavedTimings()


@dataclass(frozen=True, slots=True)
class _SummaryBatchStarted:
    batch_index: int
    started_at: float


@dataclass(frozen=True, slots=True)
class _SummaryBatchResponding:
    batch_index: int


@dataclass(frozen=True, slots=True)
class _SummaryBatchCompleted:
    batch_index: int
    summary: SummaryBatchResult
    finished_at: float


_SummaryBatchTransition = (
    _SummaryBatchStarted | _SummaryBatchResponding | _SummaryBatchCompleted
)


@dataclass(frozen=True, slots=True)
class _RunContext:
    session_key: str
    run_id: str
    base_url: str
    selected_model: str
    thinking_level: str
    current_user_request: str
    prompts: AgentPromptSet
    skills: AgentSkillSet
    retrieval_settings: AgentRetrievalSettings
    web_settings: AgentWebSettings


@dataclass(slots=True)
class _FinalStreamState:
    thinking: str
    content: str
    usage: dict[str, int]
    did_finish: bool


class AgentRuntime(AgentLoopMixin):
    def __init__(
        self,
        *,
        context_builder: AgentContextBuilder,
        inference: InferenceAdapter,
        model_policy: SingleModelPolicy,
        trace_store: AgentTraceStore,
        provider_label: str,
    ) -> None:
        if not isinstance(provider_label, str) or provider_label == "":
            raise ValueError("Agent runtime provider label must be non-empty")
        self._context_builder = context_builder
        self._inference = inference
        self._model_policy = model_policy
        self._trace_store = trace_store
        self._provider_label = provider_label

    async def stream_agent(
        self,
        *,
        session_key: str,
        base_url: str,
        selected_model: str,
        thinking_level: str,
        canonical_messages: list[dict[str, str]],
        prompts: AgentPromptSet,
        skills: AgentSkillSet,
        retrieval_settings: AgentRetrievalSettings,
        web_settings: AgentWebSettings,
        frozen_scope: ScopedSearchSnapshot,
        tagging_run,
        earlier_actions: list[dict[str, object]],
    ) -> AsyncIterator[dict[str, object]]:
        """Answer with the tool-using agent loop (see agent_loop.py).

        `earlier_actions` is the agent's own record of what each earlier answer in
        the history did (AiChatSessionStore.earlier_actions, action_log.py)."""
        run, _initial_messages = self._start_run(
            session_key=session_key, base_url=base_url, selected_model=selected_model,
            thinking_level=thinking_level, canonical_messages=canonical_messages, prompts=prompts,
            skills=skills, retrieval_settings=retrieval_settings, web_settings=web_settings,
        )
        with record_history(self._trace_store, session_key=session_key, run_id=run.run_id):
            # lint: allow-PY001 rationale="record every agent run failure before immediately re-raising"
            try:
                async with aclosing(self._run_agent_loop(  # shockharness: ignore[EXC003] reason="the agent loop's events are pulled and recorded one by one; the handler records the run's failure"
                    run=run, canonical_messages=canonical_messages, frozen_scope=frozen_scope,
                    tagging_run=tagging_run, earlier_actions=earlier_actions,
                )) as steps:
                    async for event in steps:
                        self._trace_store.append_event(
                            session_key=run.session_key, run_id=run.run_id,
                            event_type="APPLICATION_EVENT", label="Application outcome",
                            detail=event, duration_ms=0.0,
                        )
                        yield event
            # lint: allow-PY001 rationale="record interrupted external inference before preserving cancellation"
            except asyncio.CancelledError:
                self._record_failure(session_key=session_key, run_id=run.run_id, error="Agent run interrupted")
                raise
            # lint: allow-PY001 rationale="record internal failure details and immediately re-raise"
            except Exception as exc:
                self._record_failure(session_key=session_key, run_id=run.run_id,
                                     error=f"{type(exc).__name__}: {exc}")
                raise

    async def _stream_view_summary(
        self,
        *,
        run: _RunContext,
        canonical_messages: list[dict[str, str]],
        snapshot: ScopedSearchSnapshot,
        state: InvestigationState,
        selected_note_tokens: int,
        route_tokens: int,
        continues_failed_summary: bool,
    ) -> AsyncIterator[dict[str, object]]:
        """Summarize the whole frozen view (the agent's summarize_view).

        When the agent says this continues a failed summary, batches kept from it
        (summary_batch_store.py) that match exactly are reused, the rest run with the
        original question, and the scope question is not asked again: the user chose
        to summarize everything when the kept batches ran."""
        if not isinstance(continues_failed_summary, bool):
            raise TypeError("continues_failed_summary must be a bool")
        skill = run.skills.for_action("summarize_current_scope")
        self._record_skill_activation(run=run, skill=skill)
        yield self._status_event(
            "skill",
            "completed",
            f"Activated skill · {skill.title}",
            approx_input_tokens=route_tokens,
        )
        extraction_before = snapshot.text_extraction.reading()
        saved_timing = await asyncio.to_thread(_SAVED_TIMINGS.load, base_url=run.base_url, model=run.selected_model)
        plan_batches = partial(
            state.plan_complete_root_batches, reserved_approximate_tokens=selected_note_tokens,
            with_timing_probes=saved_timing is None,
        )
        # lint: allow-PY001 rationale="translate a user-configured evidence budget overflow into a concise operation failure"
        try:
            batch_plan = await read_notes_off_request_loop(snapshot=snapshot, read_notes=plan_batches)
        # lint: allow-PY001 rationale="an atomic root can legitimately exceed the user-configured summary batch limit"
        except ValueError as exc:
            raise AgentExecutionError(str(exc)) from exc
        # Planning measures every note, so it is where their text is extracted.
        yield self._status_event(
            "investigation_evidence",
            "completed",
            f"Planned {len(batch_plan.batches)} evidence batches for {batch_plan.result_tree_count} root notes"
            + describe_text_extraction(before=extraction_before, after=snapshot.text_extraction.reading()),
            approx_input_tokens=route_tokens,
        )
        # A summary covers the whole view, in as many batches as it takes, with no question about
        # scope (the maintainer, 2026-11-08). One evidence payload is one ordinary model call.
        if len(batch_plan.batches) > 1:
            batch_keys = self._summary_batch_keys(run=run, skill=skill, snapshot=snapshot, plan=batch_plan)
            kept = None
            if continues_failed_summary:
                kept = summary_batch_store.kept(session_key=run.session_key)
            if kept is not None:
                reused = {
                    index: kept.results[key] for index, key in enumerate(batch_keys) if key in kept.results
                }
                if reused:
                    async with aclosing(self._stream_staged_scope_summary(
                        run=run,
                        canonical_messages=canonical_messages,
                        summary_request=kept.request,
                        state=state,
                        skill=skill,
                        plan=batch_plan,
                        batch_keys=batch_keys,
                        reused=reused,
                        saved_timing=saved_timing,
                    )) as staged_events:
                        async for event in staged_events:
                            yield event
                    return
            async with aclosing(self._stream_staged_scope_summary(
                run=run,
                canonical_messages=canonical_messages,
                summary_request=canonical_messages[-1]["content"],
                state=state,
                skill=skill,
                plan=batch_plan,
                batch_keys=batch_keys,
                reused={},
                saved_timing=saved_timing,
            )) as staged_events:
                async for event in staged_events:
                    yield event
            return
        retention = await read_notes_off_request_loop(snapshot=snapshot, read_notes=partial(
            state.retain_root_prefix_within_token_budget,
            reserved_approximate_tokens=selected_note_tokens,
        ))
        dropped_root_count = len(retention.dropped_root_ids)
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="EVIDENCE_ROOT_PREFIX_RETAINED",
            label="Retained ordered root trees within the evidence token budget",
            detail={
                "original_note_count": retention.original_note_count,
                "original_result_tree_count": retention.original_result_tree_count,
                "retained_note_count": retention.retained_note_count,
                "retained_result_tree_count": retention.retained_result_tree_count,
                "retained_approximate_token_count": (
                    retention.retained_approximate_token_count
                ),
                "target_approximate_token_count": (
                    run.retrieval_settings.max_page_approximate_tokens
                ),
                "retained_root_ids": list(retention.retained_root_ids),
                "dropped_root_ids": list(retention.dropped_root_ids),
            },
            duration_ms=0.0,
        )
        basis = "the complete frozen evidence scope"
        if dropped_root_count:
            yield self._status_event(
                "evidence_root_prefix",
                "completed",
                (
                    "Only using "
                    f"{retention.retained_result_tree_count} of "
                    f"{retention.original_result_tree_count} root notes for answer"
                ),
                approx_input_tokens=route_tokens,
            )
            basis = (
                "the leading ordered complete-root subset retained within the "
                "single evidence token budget; later frozen-scope roots were "
                "omitted, so do not claim exhaustive scope coverage"
            )
        evidence_payload = state.current_scope_payload()
        yield self._status_event(
            "investigation_evidence",
            "completed",
            self._evidence_payload_status_label(evidence_payload),
            approx_input_tokens=(
                evidence_payload.returned_approximate_token_count
            ),
        )
        self._record_evidence_payload(
            run=run,
            evidence_payload=evidence_payload,
        )
        final_messages, reference_note_ids = (
            self._context_builder.build_scoped_final_messages(
                canonical_messages=canonical_messages,
                prompts=run.prompts,
                skill=skill,
                state=state,
                evidence_payload=evidence_payload,
                basis=basis,
            )
        )
        final_tokens = estimate_message_tokens(final_messages)
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="FINAL_EVIDENCE",
            label="Single authoritative evidence payload",
            detail={
                "source_ids": list(reference_note_ids),
                "result_tree_ids": list(evidence_payload.result_tree_ids),
            },
            duration_ms=0.0,
        )
        yield self._status_event(
            "investigation_sources",
            "completed",
            (
                "Evidence ready · generating response from "
                f"{len(evidence_payload.evidence_note_ids)} notes in "
                f"{len(evidence_payload.result_tree_ids)} result trees"
            ),
            approx_input_tokens=final_tokens,
        )
        final_request = final_messages[-1]
        capabilities = build_web_url_capabilities(
            canonical_messages=canonical_messages,
            selected_note=snapshot.selected_note,
            investigation_evidence=evidence_payload,
            retained_web_urls=web_evidence_store.retained_urls(
                session_key=run.session_key
            ),
        )
        final_messages = self._context_builder.append_web_access_context(
            messages=final_messages[:-1],
            settings=run.web_settings,
            available_urls=capabilities.normalized_urls,
        )
        final_messages.append(final_request)
        async for event in self._stream_prebuilt_final_response(
            run=run,
            final_messages=final_messages,
            reference_note_ids=reference_note_ids,
            reference_web_evidence=(),
        ):
            yield event

    def _summary_batch_keys(
        self, *, run: _RunContext, skill: AgentSkill, snapshot: ScopedSearchSnapshot, plan: CompleteRootBatchPlan,
    ) -> tuple[str, ...]:
        """What identifies each batch's findings, for reuse when continuing a failed summary."""
        model = self._model_policy.for_stage(purpose=InferencePurpose.SUMMARY_BATCH, selected_model=run.selected_model)
        selected_note_payload = snapshot.selected_note.as_payload()
        return tuple(
            summary_batch_key(
                model=model, thinking_level=run.thinking_level, prompts=run.prompts, skill=skill,
                selected_note_payload=selected_note_payload, evidence_payload=batch,
            )
            for batch in plan.batches
        )

    async def _stream_staged_scope_summary(
        self,
        *,
        run: _RunContext,
        canonical_messages: list[dict[str, str]],
        summary_request: str,
        state: InvestigationState,
        skill: AgentSkill,
        plan: CompleteRootBatchPlan,
        batch_keys: tuple[str, ...],
        reused: dict[int, SummaryBatchResult],
        saved_timing: ModelTiming | None,
    ) -> AsyncIterator[dict[str, object]]:
        """Batches, condensing and the final answer. If anything fails or the run
        stops, the finished batches are kept (summary_batch_store.py) so the summary
        can be continued; a successful summary drops them."""
        assert len(batch_keys) == len(plan.batches)
        summaries: list[SummaryBatchResult | None] = [None] * len(plan.batches)
        for index, summary in reused.items():
            summaries[index] = summary
        has_succeeded = False
        # lint: allow-PY001 rationale="keep a failed summary's finished batches, then re-raise with how many were kept"
        try:
            if len(plan.batches) < _MIN_STAGED_SUMMARY_BATCHES:
                raise ValueError("Staged scope summary requires at least two batches")
            # aclosing guarantees worker cancellation when the client abandons the stream.
            async with aclosing(self._stream_staged_summary_batches(  # shockharness: ignore[EXC003] reason="the staged summary (batches, reduction, final answer) is the operation whose failure says how many batches were kept"
                run=run,
                canonical_messages=canonical_messages,
                summary_request=summary_request,
                state=state,
                skill=skill,
                plan=plan,
                summaries=summaries,
                saved_timing=saved_timing,
            )) as batch_events:
                async for event in batch_events:
                    yield event
            if any(summary is None for summary in summaries):
                raise RuntimeError("Staged summary completed with missing batch results")
            ordered_summaries = tuple(
                summary for summary in summaries if summary is not None
            )
            summary_token_limit = run.retrieval_settings.max_page_approximate_tokens
            if state.snapshot.selected_note.status == "available":
                summary_token_limit -= estimate_input_tokens(
                    state.snapshot.selected_note.as_payload()
                )
            if summary_token_limit < 1:
                raise AgentExecutionError(
                    "Selected-note context leaves no room for staged summary evidence"
                )
            if estimate_summary_results_tokens(ordered_summaries) > (
                summary_token_limit
            ):
                yield {
                    "type": "bulk_progress",
                    "operation": "summary",
                    "committing": False,
                    "label": "Condensing batch summaries for final synthesis",
                    "percent": SUMMARY_PROGRESS_COMPLETE_PERCENT,
                }
                ordered_summaries = await self._reduce_staged_summaries(
                    run=run,
                    canonical_messages=canonical_messages,
                    summary_request=summary_request,
                    state=state,
                    skill=skill,
                    summaries=ordered_summaries,
                )
            yield {
                "type": "bulk_progress",
                "operation": "summary",
                "committing": False,
                "label": "Writing the final answer",
                "percent": SUMMARY_PROGRESS_COMPLETE_PERCENT,
            }
            final_messages, reference_note_ids = (
                self._context_builder.build_staged_summary_final_messages(
                    canonical_messages=canonical_messages,
                    summary_request=summary_request,
                    prompts=run.prompts,
                    skill=skill,
                    snapshot=state.snapshot,
                    summaries=ordered_summaries,
                    note_aliases=state.note_aliases,
                )
            )
            yield {"type": "bulk_complete", "changed": False}
            async for event in self._stream_prebuilt_final_response(
                run=run,
                final_messages=final_messages,
                reference_note_ids=reference_note_ids,
                reference_web_evidence=(),
            ):
                yield event
            has_succeeded = True
        # lint: allow-PY001 rationale="an explained summary failure says how many finished batches were kept, then re-raises"
        except AgentExecutionError as exc:
            finished_count = sum(1 for summary in summaries if summary is not None)
            if finished_count == 0:
                raise
            raise AgentExecutionError(
                f"{exc}\n{finished_count} of {len(summaries)} batches finished and were kept; "
                "ask again (for example \"try that again\") to finish the rest."
            ) from exc
        finally:
            finished = {
                batch_keys[index]: summary
                for index, summary in enumerate(summaries) if summary is not None
            }
            if has_succeeded or not finished:
                summary_batch_store.clear_session(session_key=run.session_key)
            else:
                summary_batch_store.keep(session_key=run.session_key, request=summary_request, results=finished)

    async def _stream_staged_summary_batches(
        self,
        *,
        run: _RunContext,
        canonical_messages: list[dict[str, str]],
        summary_request: str,
        state: InvestigationState,
        skill: AgentSkill,
        plan: CompleteRootBatchPlan,
        summaries: list[SummaryBatchResult | None],
        saved_timing: ModelTiming | None,
    ) -> AsyncIterator[dict[str, object]]:
        """Run every batch through a worker pool the provider's limits bound (provider_limits.py).

        ``summaries`` arrives with any batches reused from a failed attempt already
        filled in; the others are filled in canonical batch order, with one progress
        event each time a batch starts, starts responding and finishes, and the clock moves the
        bar between them against the model's timing. When a batch fails, batches not started yet do not start, the ones
        running finish (their results stay in ``summaries`` to be kept), and the first
        failure then propagates, so no final synthesis runs on partial results.
        """
        batch_count = len(plan.batches)
        assert batch_count >= _MIN_STAGED_SUMMARY_BATCHES
        assert len(summaries) == batch_count
        batch_states = ["complete" if summary is not None else "queued" for summary in summaries]
        batch_sizes = tuple(batch.returned_approximate_token_count for batch in plan.batches)

        batch_started_at = [0.0] * batch_count
        timed_batches: list[tuple[int, float]] = []
        def timing_in_use() -> ModelTiming | None:
            """This run's own batches once two have finished; until then what was saved, if anything."""
            fitted = fit_model_timing(tuple(timed_batches))
            if fitted is not None:
                return fitted
            return saved_timing

        def estimated_percent() -> int:
            now = time.monotonic()
            return summary_progress_percent(
                batch_tokens=batch_sizes,
                batch_states=tuple(batch_states),
                batch_elapsed_seconds=tuple(
                    now - started_at if state in ("writing", "responding") else 0.0
                    for state, started_at in zip(batch_states, batch_started_at)
                ),
                timing=timing_in_use(),
            )

        shown_percent = float(estimated_percent())
        shown_at = time.monotonic()

        def percent_done() -> float:
            nonlocal shown_percent, shown_at
            now = time.monotonic()
            shown_percent = advanced_progress_percent(
                shown=shown_percent, target=estimated_percent(), seconds=now - shown_at,
            )
            shown_at = now
            return round(shown_percent, _SUMMARY_PROGRESS_DECIMALS)

        def summarizing_event(percent: float) -> dict[str, object]:
            return {
                "type": "bulk_progress",
                "operation": "summary",
                "committing": False,
                "label": f"Summarizing · {int(percent)}%",
                "percent": percent,
            }

        if "complete" in batch_states:
            yield {
                "type": "bulk_progress",
                "operation": "summary",
                "committing": False,
                "label": "Reusing your earlier attempt",
                "percent": percent_done(),
            }
        transitions: asyncio.Queue[_SummaryBatchTransition] = asyncio.Queue()

        def apply_transition(transition: _SummaryBatchTransition) -> dict[str, object]:
            index = transition.batch_index
            if not 0 <= index < batch_count:
                raise RuntimeError(f"Summary batch index {index} is outside the plan")
            batch_state = batch_states[index]
            if isinstance(transition, _SummaryBatchStarted):
                if batch_state != "queued":
                    raise RuntimeError(f"Summary batch {index + 1} started more than once")
                batch_states[index] = "writing"
                batch_started_at[index] = transition.started_at
            elif isinstance(transition, _SummaryBatchResponding):
                if batch_state != "writing":
                    raise RuntimeError(f"Summary batch {index + 1} responded outside its request")
                batch_states[index] = "responding"
            else:
                assert isinstance(transition, _SummaryBatchCompleted)
                if batch_state == "complete":
                    raise RuntimeError(f"Summary batch {index + 1} completed more than once")
                if batch_state not in ("writing", "responding"):
                    raise RuntimeError(f"Summary batch {index + 1} completed before it started")
                batch_states[index] = "complete"
                summaries[index] = transition.summary
                timed_batches.append((batch_sizes[index], transition.finished_at - batch_started_at[index]))
            return summarizing_event(percent_done())

        def first_response_reporter(index: int) -> Callable[[StructuredInferenceProgress], None]:
            has_reported = False

            def report(progress: StructuredInferenceProgress) -> None:
                nonlocal has_reported
                if progress.phase != "output_progress" or has_reported:
                    return
                has_reported = True
                transitions.put_nowait(_SummaryBatchResponding(batch_index=index))

            return report

        async def summarize_batch(index: int) -> None:
            transitions.put_nowait(_SummaryBatchStarted(batch_index=index, started_at=time.monotonic()))
            summary = await self._infer_staged_summary_batch(
                run=run,
                canonical_messages=canonical_messages,
                summary_request=summary_request,
                state=state,
                skill=skill,
                evidence_payload=plan.batches[index],
                batch_index=index,
                batch_count=batch_count,
                on_stream=first_response_reporter(index),
            )
            transitions.put_nowait(
                _SummaryBatchCompleted(batch_index=index, summary=summary, finished_at=time.monotonic())
            )

        gate = gate_for(base_url=run.base_url, model=run.selected_model)

        def batch_tokens(index: int) -> int:
            return (plan.batches[index].returned_approximate_token_count
                    + structured_max_output_tokens(SummaryBatchResult))

        async def drain(indexes: tuple[int, ...]) -> AsyncIterator[dict[str, object]]:
            """Every batch waits for room in the provider's limits (provider_limits), then
            starts, unless one has failed meanwhile: batches not started yet never start."""
            assert indexes
            has_failed = False

            async def summarize_when_admitted(index: int) -> None:
                nonlocal has_failed
                async with gate.slot(batch_tokens(index)):
                    if has_failed:
                        return
                    is_finished = False
                    try:
                        await summarize_batch(index)
                        is_finished = True
                    finally:
                        # Said before this batch's room is given to a waiting one, so that one
                        # sees it and does not start.
                        if not is_finished:
                            has_failed = True

            workers = [asyncio.create_task(summarize_when_admitted(index)) for index in indexes]
            index_of_worker = dict(zip(workers, indexes))
            running_workers = set(workers)
            # By batch: with every batch at once, several can fail together; the lowest-numbered
            # is the one reported, whichever finished first.
            failures: dict[int, BaseException] = {}
            try:
                while running_workers or not transitions.empty():
                    next_transition = asyncio.create_task(transitions.get())
                    try:
                        done, _pending = await asyncio.wait(
                            {next_transition, *running_workers},
                            timeout=_SUMMARY_PROGRESS_TICK_SECONDS,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    finally:
                        if not next_transition.done():
                            next_transition.cancel()
                    for worker in running_workers.intersection(done):
                        running_workers.remove(worker)
                        failure = worker.exception()
                        if failure is not None:
                            # Batches not started yet do not start; running ones finish and are kept.
                            failures[index_of_worker[worker]] = failure
                            has_failed = True
                    if next_transition in done:
                        yield apply_transition(next_transition.result())
                    else:
                        percent_before_tick = round(shown_percent, _SUMMARY_PROGRESS_DECIMALS)
                        percent = percent_done()
                        if percent > percent_before_tick:
                            yield summarizing_event(percent)
                if failures:
                    raise failures[min(failures)]
            finally:
                for worker in workers:
                    if not worker.done():
                        worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)

        to_run = tuple(index for index in range(batch_count) if batch_states[index] == "queued")
        if to_run:
            # Every batch at once, as many as the provider's limits allow (the gate: four until a
            # first answer's headers tell them). Until 2026-11-08 batch 1 ran alone first to seed
            # the provider's prompt cache, a whole batch's wait for a small share of each batch.
            async with aclosing(drain(to_run)) as batch_events:
                async for event in batch_events:
                    yield event
        if batch_states != ["complete"] * batch_count:
            raise RuntimeError("Staged summary workers stopped before every batch completed")
        timing = fit_model_timing(tuple(timed_batches))
        if timing is not None:
            await asyncio.to_thread(_SAVED_TIMINGS.save, base_url=run.base_url, model=run.selected_model, timing=timing)

    async def _infer_staged_summary_batch(
        self,
        *,
        run: _RunContext,
        canonical_messages: list[dict[str, str]],
        summary_request: str,
        state: InvestigationState,
        skill: AgentSkill,
        evidence_payload: InvestigationEvidencePayload,
        batch_index: int,
        batch_count: int,
        on_stream: Callable[[StructuredInferenceProgress], None],
    ) -> SummaryBatchResult:
        messages = self._context_builder.build_staged_summary_batch_messages(
            canonical_messages=canonical_messages,
            summary_request=summary_request,
            prompts=run.prompts,
            skill=skill,
            snapshot=state.snapshot,
            evidence_payload=evidence_payload,
            batch_index=batch_index,
            batch_count=batch_count,
            note_aliases=state.note_aliases,
        )
        return await self._infer_cited_summary_findings(
            run=run,
            messages=messages,
            note_aliases=state.note_aliases,
            expected_root_ids=evidence_payload.result_tree_ids,
            allowed_note_ids=frozenset((
                *evidence_payload.evidence_note_ids,
                *state.snapshot.selected_note.reference_note_ids,
            )),
            structural_note_ids=structural_placeholder_note_ids(
                evidence_payload.result_trees
            ),
            stage_label=f"Summary batch {batch_index + 1}",
            on_stream=on_stream,
        )

    async def _infer_cited_summary_findings(
        self,
        *,
        run: _RunContext,
        messages: list[dict[str, str]],
        note_aliases: NoteAliases,
        expected_root_ids: tuple[str, ...],
        allowed_note_ids: frozenset[str],
        structural_note_ids: frozenset[str],
        stage_label: str,
        on_stream: Callable[[StructuredInferenceProgress], None],
    ) -> SummaryBatchResult:
        """Request summary findings, asking once for a correction of uncitable IDs. The model sees
        and cites short note IDs (n1, n2…): citations are checked as it wrote them, and the
        findings kept carry note ids."""
        allowed_aliases = frozenset(note_aliases.alias(note_id) for note_id in allowed_note_ids)
        structural_aliases = frozenset(note_aliases.alias(note_id) for note_id in structural_note_ids)

        def on_progress(progress: StructuredInferenceProgress) -> None:
            self._record_inference_progress(
                run=run,
                progress=progress,
                purpose=InferencePurpose.SUMMARY_BATCH,
            )
            on_stream(progress)

        attempt_messages = messages
        for correction_round in range(_SUMMARY_CITATION_CORRECTIONS + 1):
            response = await self._request_structured_inference(
                run=run,
                model=self._model_policy.for_stage(
                    purpose=InferencePurpose.SUMMARY_BATCH,
                    selected_model=run.selected_model,
                ),
                messages=attempt_messages,
                response_model=SummaryFindingsResult,
                purpose=InferencePurpose.SUMMARY_BATCH,
                on_progress=on_progress,
            )
            findings = SummaryFindingsResult.model_validate_json(response.content)
            # Against what the batch was sent: the correction request quotes the rejected IDs.
            rejected_note_ids = classify_uncitable_note_ids(
                result=findings,
                allowed_note_ids=allowed_aliases,
                structural_note_ids=structural_aliases,
                request_text=json.dumps(messages),
            )
            if rejected_note_ids and correction_round == _SUMMARY_CITATION_CORRECTIONS:
                findings, rejected_note_ids = self._drop_citations_never_sent(
                    run=run, stage_label=stage_label, findings=findings, rejected_note_ids=rejected_note_ids,
                    note_aliases=note_aliases,
                )
            if not rejected_note_ids:
                result = attach_summary_coverage(
                    result=SummaryFindingsResult.model_validate(note_aliases.unaliased(findings.model_dump(mode="json"))),
                    expected_root_ids=expected_root_ids,
                    allowed_note_ids=allowed_note_ids,
                )
                self._record_structured_attempts(
                    run=run,
                    attempts=response.attempts,
                    parsed=result.model_dump(mode="json"),
                    purpose=InferencePurpose.SUMMARY_BATCH,
                )
                return result
            self._record_structured_attempts(
                run=run,
                attempts=response.attempts,
                parsed=findings.model_dump(mode="json"),
                purpose=InferencePurpose.SUMMARY_BATCH,
            )
            # Named by note id where the short ID is one, as written otherwise.
            rejected_detail = "; ".join(
                f"{note_aliases.note_id(note_id)} ({reason})" for note_id, reason in rejected_note_ids
            )
            self._trace_store.append_event(
                session_key=run.session_key,
                run_id=run.run_id,
                event_type="SUMMARY_CITATION_REJECTED",
                label=f"{stage_label} cited uncitable note IDs",
                detail={
                    "correction_round": correction_round,
                    "rejected_note_ids": [
                        {"note_id": note_aliases.note_id(note_id), "reason": reason}
                        for note_id, reason in rejected_note_ids
                    ],
                },
                duration_ms=0.0,
            )
            if correction_round == _SUMMARY_CITATION_CORRECTIONS:
                raise AgentExecutionError(
                    f"{stage_label} returned invalid findings: cited note IDs that "
                    "were not disclosed as evidence, even after a correction "
                    f"request: {rejected_detail}"
                )
            attempt_messages = (
                self._context_builder.build_staged_summary_citation_correction_messages(
                    messages=messages,
                    rejected_response=response.content,
                    rejected_note_ids=rejected_note_ids,
                )
            )
        raise RuntimeError("Summary citation correction loop exited without a result")

    def _drop_citations_never_sent(
        self,
        *,
        run: _RunContext,
        stage_label: str,
        findings: SummaryFindingsResult,
        rejected_note_ids: tuple[tuple[str, str], ...],
        note_aliases: NoteAliases,
    ) -> tuple[SummaryFindingsResult, tuple[tuple[str, str], ...]]:
        """After the correction, citations to notes the batch was never sent (a garbled ID, the
        maintainer's 10,087-note summary on 2026-11-08) link to nothing: dropped, with any finding
        left citing nothing, and listed in the diagnostics, so the summary goes on. The others (a
        heading without content, a note sent but not citable, such as a private one) still stop it."""
        never_sent = frozenset(note_id for note_id, reason in rejected_note_ids if reason == UNCITABLE_ABSENT_FROM_REQUEST)
        still_rejected = tuple((note_id, reason) for note_id, reason in rejected_note_ids if note_id not in never_sent)
        if not never_sent or still_rejected:
            return findings, rejected_note_ids
        kept, dropped_finding_count = drop_citations(result=findings, note_ids=never_sent)
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="SUMMARY_CITATIONS_DROPPED",
            label=f"{stage_label}: dropped citations to notes it was never sent",
            detail={
                "dropped_note_ids": sorted(note_aliases.note_id(note_id) for note_id in never_sent),
                "dropped_finding_count": dropped_finding_count,
            },
            duration_ms=0.0,
        )
        return kept, ()

    async def _reduce_staged_summaries(
        self,
        *,
        run: _RunContext,
        canonical_messages: list[dict[str, str]],
        summary_request: str,
        state: InvestigationState,
        skill: AgentSkill,
        summaries: tuple[SummaryBatchResult, ...],
    ) -> tuple[SummaryBatchResult, ...]:
        token_limit = run.retrieval_settings.max_page_approximate_tokens
        if state.snapshot.selected_note.status == "available":
            token_limit -= estimate_input_tokens(
                state.snapshot.selected_note.as_payload()
            )
        if token_limit < 1:
            raise AgentExecutionError(
                "Selected-note context leaves no room for summary reduction"
            )
        current = summaries
        for stage_index in range(1, _MAX_STAGED_SUMMARY_REDUCTION_LEVELS + 1):
            current_tokens = estimate_summary_results_tokens(current)
            if current_tokens <= token_limit:
                return current
            # lint: allow-PY001 rationale="translate a user-configured reduction budget overflow into a concise operation failure"
            try:
                groups = partition_summary_results(
                    results=current,
                    token_limit=token_limit,
                )
            # lint: allow-PY001 rationale="an external intermediate summary can legitimately exceed the configured reduction limit"
            except ValueError as exc:
                raise AgentExecutionError(
                    "The intermediate summaries cannot fit within the configured "
                    f"evidence limit: {exc}"
                ) from exc

            reduced: list[SummaryBatchResult | None] = [None] * len(groups)
            reduced[0] = await self._infer_summary_reduction_group(
                run=run,
                canonical_messages=canonical_messages,
                summary_request=summary_request,
                state=state,
                skill=skill,
                summaries=groups[0],
                stage_index=stage_index,
                group_index=0,
                group_count=len(groups),
            )
            gate = gate_for(base_url=run.base_url, model=run.selected_model)

            async def reduce_group(index: int) -> tuple[int, SummaryBatchResult]:
                # As many groups go at once as the provider's limits allow (provider_limits).
                group_tokens = (estimate_summary_results_tokens(groups[index])
                                + structured_max_output_tokens(SummaryBatchResult))
                async with gate.slot(group_tokens):
                    result = await self._infer_summary_reduction_group(
                        run=run,
                        canonical_messages=canonical_messages,
                        summary_request=summary_request,
                        state=state,
                        skill=skill,
                        summaries=groups[index],
                        stage_index=stage_index,
                        group_index=index,
                        group_count=len(groups),
                    )
                return index, result

            tasks = [
                asyncio.create_task(reduce_group(index))
                for index in range(1, len(groups))
            ]
            try:
                for completed_task in asyncio.as_completed(tasks):
                    index, result = await completed_task
                    if reduced[index] is not None:
                        raise RuntimeError(
                            "Summary reduction group completed more than once"
                        )
                    reduced[index] = result
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            if any(result is None for result in reduced):
                raise RuntimeError("Summary reduction completed with missing groups")
            next_level = tuple(result for result in reduced if result is not None)
            if estimate_summary_results_tokens(next_level) >= current_tokens:
                raise AgentExecutionError(
                    "The model did not reduce the intermediate summary size; "
                    "the complete-scope summary was not generated"
                )
            current = next_level
        raise AgentExecutionError(
            "The complete-scope summary exceeded the maximum reduction depth"
        )

    async def _infer_summary_reduction_group(
        self,
        *,
        run: _RunContext,
        canonical_messages: list[dict[str, str]],
        summary_request: str,
        state: InvestigationState,
        skill: AgentSkill,
        summaries: tuple[SummaryBatchResult, ...],
        stage_index: int,
        group_index: int,
        group_count: int,
    ) -> SummaryBatchResult:
        expected_root_ids = tuple(
            root_id
            for summary in summaries
            for root_id in summary.covered_root_ids
        )
        allowed_note_ids = frozenset((
            *summary_reference_note_ids(summaries),
            *state.snapshot.selected_note.reference_note_ids,
        ))
        messages = self._context_builder.build_staged_summary_reduction_messages(
            canonical_messages=canonical_messages,
            summary_request=summary_request,
            prompts=run.prompts,
            skill=skill,
            snapshot=state.snapshot,
            summaries=summaries,
            stage_index=stage_index,
            group_index=group_index,
            group_count=group_count,
            note_aliases=state.note_aliases,
        )
        return await self._infer_cited_summary_findings(
            run=run,
            messages=messages,
            note_aliases=state.note_aliases,
            expected_root_ids=expected_root_ids,
            allowed_note_ids=allowed_note_ids,
            structural_note_ids=frozenset(),
            stage_label=f"Summary reduction stage {stage_index}",
            on_stream=lambda progress: None,
        )

    async def _ensure_model_context(
        self,
        *,
        run: _RunContext,
        messages: list[dict[str, str]],
    ) -> AsyncIterator[dict[str, object]]:
        input_tokens = estimate_message_tokens(messages)
        yield self._status_event(
            "model_context",
            "started",
            self._model_context_check_label(),
            approx_input_tokens=input_tokens,
        )
        context_window = await self._inference.inspect_context_window(
            base_url=run.base_url,
            model=run.selected_model,
        )
        self._record_model_context(run=run, context_window=context_window)
        if not context_window.is_sufficient:
            raise AgentExecutionError(
                f"{context_window.model} is loaded with {context_window.loaded_tokens:,} "
                f"context tokens; MetaList requires {context_window.required_tokens:,}."
            )
        yield self._status_event(
            "model_context",
            "completed",
            f"{self._provider_label} context ready · {context_window.loaded_tokens:,} tokens",
            approx_input_tokens=input_tokens,
        )

    def _start_run(
        self,
        *,
        session_key: str,
        base_url: str,
        selected_model: str,
        thinking_level: str,
        canonical_messages: list[dict[str, str]],
        prompts: AgentPromptSet,
        skills: AgentSkillSet,
        retrieval_settings: AgentRetrievalSettings,
        web_settings: AgentWebSettings,
    ) -> tuple[_RunContext, list[dict[str, str]]]:
        messages = self._context_builder.build_initial_messages(
            canonical_messages=canonical_messages,
            prompts=prompts,
        )
        run_id = self._trace_store.start_run(
            session_key=session_key,
            model=selected_model,
            user_message=canonical_messages[-1]["content"],
        )
        run = _RunContext(
            session_key=session_key,
            run_id=run_id,
            base_url=base_url,
            selected_model=selected_model,
            thinking_level=thinking_level,
            current_user_request=canonical_messages[-1]["content"],
            prompts=prompts,
            skills=skills,
            retrieval_settings=retrieval_settings,
            web_settings=web_settings,
        )
        return run, messages

    async def _request_structured_inference(
        self,
        *,
        run: _RunContext,
        model: str,
        messages: list[dict[str, str]],
        response_model: type[BaseModel],
        purpose: InferencePurpose,
        on_progress: Callable[[StructuredInferenceProgress], None],
    ) -> InferenceResponse:
        # lint: allow-PY001 rationale="capture Instructor retry attempts before surfacing an external inference failure"
        try:
            return await send_structured(
                self._inference,
                base_url=run.base_url,
                model=model,
                thinking_level=run.thinking_level,
                messages=messages,
                response_model=response_model,
                on_progress=on_progress,
            )
        except StructuredInferenceError as exc:
            self._record_structured_attempts(
                run=run,
                attempts=exc.attempts,
                parsed={},
                purpose=purpose,
            )
            # Explain the failure in the chat itself (and the saved turn), so
            # it can be understood later without the Agent Debug trace.
            raise AgentExecutionError(explain_structured_failure(
                response_model=response_model,
                attempts=exc.attempts,
                setup=FailureSetup(provider_label=self._provider_label, model=model, thinking_level=run.thinking_level,
                                   web_mode=run.web_settings.mode),
            )) from exc

    def _record_inference_progress(
        self,
        *,
        run: _RunContext,
        progress: StructuredInferenceProgress,
        purpose: InferencePurpose,
    ) -> None:
        # Before anything else: building the event counts the whole request's tokens, and this
        # runs for every few words streamed, on the loop every progress event waits for.
        if progress.phase == "output_progress":
            return
        event = self._progress_status_event(
            progress,
            purpose=purpose,
            provider_label=self._provider_label,
        )
        if progress.phase == "attempt_started":
            self._record_wire_request(
                run=run,
                purpose=purpose,
                attempt=progress.attempt,
                max_attempts=progress.max_attempts,
                wire_request=progress.wire_request,
            )
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="MODEL_STATUS",
            label=event["label"],
            detail={
                "phase": progress.phase,
                "attempt": progress.attempt,
                "max_attempts": progress.max_attempts,
                "approx_input_tokens": event["approx_input_tokens"],
                "failure_kind": progress.failure_kind,
                "error_type": progress.error_type,
                "error_message": progress.error_message,
            },
            duration_ms=progress.duration_ms,
        )

    def _record_skill_activation(
        self,
        *,
        run: _RunContext,
        skill: AgentSkill,
    ) -> None:
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="SKILL",
            label=f"Activated skill: {skill.title}",
            detail={
                "skill_id": skill.skill_id,
                "title": skill.title,
                "trigger_action": skill.trigger_action,
                "content": skill.content,
            },
            duration_ms=0.0,
        )

    def _record_model_context(
        self,
        *,
        run: _RunContext,
        context_window: InferenceContextWindow,
    ) -> None:
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="MODEL_CONTEXT",
            label=f"{self._provider_label} model context",
            detail={
                "model": context_window.model,
                "maximum_tokens": context_window.maximum_tokens,
                "loaded_tokens": context_window.loaded_tokens,
                "required_tokens": context_window.required_tokens,
                "is_sufficient": context_window.is_sufficient,
            },
            duration_ms=0.0,
        )

    async def _stream_prebuilt_final_response(
        self,
        *,
        run: _RunContext,
        final_messages: list[dict[str, str]],
        reference_note_ids: tuple[str, ...],
        reference_web_evidence: tuple[WebPageEvidence, ...],
    ) -> AsyncIterator[dict[str, object]]:
        if not isinstance(reference_note_ids, tuple):
            raise TypeError("reference_note_ids must be a tuple")
        if not isinstance(reference_web_evidence, tuple):
            raise TypeError("reference_web_evidence must be a tuple")
        reference_web_ids = tuple(
            reference.evidence_id
            for reference in citation_references_for_pages(reference_web_evidence)
        )
        if len(set(reference_web_ids)) != len(reference_web_ids):
            raise ValueError("reference_web_evidence must be unique")
        model = self._model_policy.for_stage(
            purpose=InferencePurpose.FINAL_RESPONSE,
            selected_model=run.selected_model,
        )
        final_input_tokens = estimate_message_tokens(final_messages)
        yield self._status_event(
            "respond",
            "started",
            "Writing response",
            approx_input_tokens=final_input_tokens,
        )
        started_at = time.perf_counter()
        state = _FinalStreamState(thinking="", content="", usage={}, did_finish=False)
        last_reported_output_tokens = 0
        for attempt in range(1, _FINAL_RESPONSE_MAX_ATTEMPTS + 1):
            state = _FinalStreamState(thinking="", content="", usage={}, did_finish=False)
            # Shown as "Waiting for OpenAI" until the provider's first signal.
            yield self._status_event("provider_wait", "started", f"Waiting for {self._provider_label}",
                                     approx_input_tokens=final_input_tokens)
            is_waiting_for_provider = True
            # lint: allow-PY001 rationale="retry a failed external model stream only before output"
            try:
                async for event in send_text_stream(  # shockharness: ignore[EXC003] reason="each pull from the provider's stream is the external operation; the body forwards the event"
                    self._inference,
                    base_url=run.base_url,
                    model=model,
                    thinking_level=run.thinking_level,
                    messages=final_messages,
                    on_request=self._final_response_request_recorder(run=run, attempt=attempt),
                ):
                    if is_waiting_for_provider:
                        is_waiting_for_provider = False
                        yield self._status_event("provider_wait", "completed", f"{self._provider_label} responded",
                                                 approx_input_tokens=final_input_tokens)
                    if event["type"] == "provider_started":
                        continue
                    should_yield = self._consume_final_event(event=event, state=state)
                    output_tokens_received = estimate_text_tokens(
                        f"{state.thinking}{state.content}"
                    )
                    if output_tokens_received >= last_reported_output_tokens + _OUTPUT_PROGRESS_REPORT_TOKENS:
                        last_reported_output_tokens = output_tokens_received
                        yield self._output_status_event(
                            "respond",
                            "started",
                            "Writing response",
                            approx_input_tokens=final_input_tokens,
                            output_tokens_received=output_tokens_received,
                            duration_ms=(time.perf_counter() - started_at) * MS_PER_SECOND,
                        )
                    if should_yield:
                        if event["type"] == "content_delta":
                            yield {
                                **event,
                                "reference_note_ids": list(reference_note_ids),
                                "reference_web_ids": list(reference_web_ids),
                            }
                        else:
                            yield event
            # lint: allow-PY001 rationale="retry one external model-provider failure only before output"
            except InferenceProviderError:
                has_partial_output = any(
                    (state.thinking != "", state.content != "")
                )
                if has_partial_output or attempt == _FINAL_RESPONSE_MAX_ATTEMPTS:
                    raise
                yield self._status_event(
                    "respond",
                    "started",
                    (
                        f"{self._provider_label} rejected the response before output · "
                        "retrying attempt 2 of 2"
                    ),
                    approx_input_tokens=final_input_tokens,
                )
                continue
            break
        self._validate_final_stream(state)
        duration_ms = (time.perf_counter() - started_at) * MS_PER_SECOND
        self._record_final_response(run=run, state=state, duration_ms=duration_ms)
        self._trace_store.complete_run(session_key=run.session_key, run_id=run.run_id)
        final_output_tokens = estimate_text_tokens(
            f"{state.thinking}{state.content}"
        )
        if "eval_count" in state.usage:
            final_output_tokens = state.usage["eval_count"]
        yield self._output_status_event(
            "respond",
            "completed",
            "Response complete",
            approx_input_tokens=final_input_tokens,
            output_tokens_received=final_output_tokens,
            duration_ms=duration_ms,
        )
        yield {
            "type": "done",
            "reference_note_ids": list(reference_note_ids),
            "reference_web_ids": list(reference_web_ids),
        }

    def _record_evidence_payload(
        self,
        *,
        run: _RunContext,
        evidence_payload: InvestigationEvidencePayload,
    ) -> None:
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="EVIDENCE_PAYLOAD",
            label=f"Evidence payload sent to {self._provider_label}",
            detail={
                "evidence_payload": serialize_investigation_evidence_payload(
                    evidence_payload
                ),
            },
            duration_ms=0.0,
        )

    @staticmethod
    def _evidence_payload_status_label(
        evidence_payload: InvestigationEvidencePayload,
    ) -> str:
        if not isinstance(evidence_payload, InvestigationEvidencePayload):
            raise TypeError(
                "evidence_payload must be InvestigationEvidencePayload"
            )
        return (
            "Evidence ready · "
            f"{len(evidence_payload.evidence_note_ids)} notes in "
            f"{len(evidence_payload.result_tree_ids)} result trees · "
            "≈ "
            f"{evidence_payload.returned_approximate_token_count:,} "
            "evidence tokens"
        )

    @staticmethod
    def _consume_final_event(
        *,
        event: dict[str, object],
        state: _FinalStreamState,
    ) -> bool:
        event_type = event["type"]
        if event_type in {"thinking_delta", "content_delta"}:
            if "text" not in event:
                raise RuntimeError(f"Inference {event_type} is missing text")
            text = event["text"]
            if not isinstance(text, str) or text == "":
                raise RuntimeError(f"Inference {event_type} must contain text")
            if event_type == "thinking_delta":
                state.thinking += text
            else:
                state.content += text
            return True
        if event_type != "done":
            raise RuntimeError(f"Unknown inference stream event: {event_type}")
        state.did_finish = True
        raw_usage = {}
        if "usage" in event:
            raw_usage = event["usage"]
        if not isinstance(raw_usage, dict):
            raise RuntimeError("Inference done event usage must be an object")
        if not all(
            isinstance(key, str) and isinstance(value, int)
            for key, value in raw_usage.items()
        ):
            raise RuntimeError("Inference done event usage values must be integers")
        state.usage = dict(raw_usage)
        return False

    @staticmethod
    def _validate_final_stream(state: _FinalStreamState) -> None:
        if not state.did_finish:
            raise AgentExecutionError("Final response stream ended before completion")
        if state.content == "":
            raise AgentExecutionError("The model returned an empty final response")

    def _record_final_response(
        self,
        *,
        run: _RunContext,
        state: _FinalStreamState,
        duration_ms: float,
    ) -> None:
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="MODEL_RESPONSE",
            label="Model response: final-response",
            detail={
                "raw_response": state.content,
                "reasoning": state.thinking,
                "usage": state.usage,
                "validation": "not-applicable",
                "parsed": {},
                "errors": [],
            },
            duration_ms=duration_ms,
        )
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="FINAL_RESPONSE",
            label="Final response",
            detail={"content": state.content},
            duration_ms=0.0,
        )

    def _final_response_request_recorder(self, *, run: _RunContext, attempt: int) -> Callable[[dict[str, object]], None]:
        def record(wire_request: dict[str, object]) -> None:
            self._record_wire_request(
                run=run,
                purpose=InferencePurpose.FINAL_RESPONSE,
                attempt=attempt,
                max_attempts=_FINAL_RESPONSE_MAX_ATTEMPTS,
                wire_request=wire_request,
            )
        return record

    def _record_wire_request(
        self,
        *,
        run: _RunContext,
        purpose: InferencePurpose,
        attempt: int,
        max_attempts: int,
        wire_request: dict[str, object],
    ) -> None:
        attempt_suffix = self._attempt_label_suffix(
            attempt=attempt,
            max_attempts=max_attempts,
        )
        self._trace_store.append_event(
            session_key=run.session_key,
            run_id=run.run_id,
            event_type="PROVIDER_REQUEST",
            label=(
                f"{self._provider_label} wire request: {purpose.value}"
                f"{attempt_suffix}"
            ),
            detail={
                "purpose": purpose.value,
                "attempt": attempt,
                "max_attempts": max_attempts,
                **wire_request,
            },
            duration_ms=0.0,
        )

    def _record_structured_attempts(
        self,
        *,
        run: _RunContext,
        attempts: list[InferenceAttempt],
        parsed: dict[str, object],
        purpose: InferencePurpose,
    ) -> None:
        for attempt_number, attempt in enumerate(attempts, start=1):
            is_success = attempt.error == "" and attempt_number == len(attempts)
            self._trace_store.append_event(
                session_key=run.session_key,
                run_id=run.run_id,
                event_type="MODEL_RESPONSE",
                label=f"Model response: {purpose.value}",
                detail={
                    "raw_response": attempt.response,
                    "validation": "valid" if is_success else "invalid",
                    "parsed": parsed if is_success else {},
                    "errors": [] if attempt.error == "" else [attempt.error],
                },
                duration_ms=attempt.duration_ms,
            )

    def _record_failure(self, *, session_key: str, run_id: str, error: str) -> None:
        self._trace_store.append_event(
            session_key=session_key,
            run_id=run_id,
            event_type="ERROR",
            label="Agent run failed",
            detail={"error": error},
            duration_ms=0.0,
        )
        self._trace_store.fail_run(session_key=session_key, run_id=run_id, error=error)

    @staticmethod
    def _progress_status_event(
        progress: StructuredInferenceProgress,
        *,
        purpose: InferencePurpose,
        provider_label: str,
    ) -> dict[str, object]:
        if not isinstance(provider_label, str) or provider_label == "":
            raise ValueError("Structured inference provider label must be non-empty")
        if not isinstance(purpose, InferencePurpose):
            raise TypeError("Structured inference purpose is invalid")
        if progress.attempt < 1 or progress.attempt > progress.max_attempts:
            raise ValueError("Structured inference progress attempt is invalid")
        attempt_suffix = AgentRuntime._attempt_label_suffix(
            attempt=progress.attempt,
            max_attempts=progress.max_attempts,
        )
        attempt_text = attempt_suffix.removeprefix(" · ")
        approx_input_tokens = AgentRuntime._wire_request_input_tokens(
            progress.wire_request
        )
        if progress.phase == "attempt_started":
            operation_label = f"{provider_label} writing a structured reply"
            label = f"{operation_label}{attempt_suffix}"
            if progress.attempt > 1:
                label = f"Instructor retrying · {label}"
            return AgentRuntime._output_status_event(
                "model_request",
                "started",
                label,
                approx_input_tokens=approx_input_tokens,
                output_tokens_received=progress.output_tokens_received,
                duration_ms=progress.duration_ms,
            )
        if progress.phase == "output_progress":
            operation_label = f"{provider_label} writing a structured reply"
            return AgentRuntime._output_status_event(
                "model_request",
                "started",
                f"{operation_label}{attempt_suffix}",
                approx_input_tokens=approx_input_tokens,
                output_tokens_received=progress.output_tokens_received,
                duration_ms=progress.duration_ms,
            )
        if progress.phase == "response_received":
            response_label = f"{provider_label} returned a structured reply"
            return AgentRuntime._output_status_event(
                "validation",
                "started",
                (
                    f"{response_label} · validating"
                    f"{' ' + attempt_text if attempt_text else ''}"
                ),
                approx_input_tokens=approx_input_tokens,
                output_tokens_received=progress.output_tokens_received,
                duration_ms=progress.duration_ms,
            )
        if progress.phase == "retrying":
            return AgentRuntime._output_status_event(
                "retry",
                "started",
                f"{progress.failure_kind} ({progress.error_type}) · Instructor will retry",
                approx_input_tokens=approx_input_tokens,
                output_tokens_received=progress.output_tokens_received,
                duration_ms=progress.duration_ms,
            )
        if progress.phase == "attempt_failed":
            return AgentRuntime._output_status_event(
                "retry",
                "completed",
                f"{progress.failure_kind} ({progress.error_type}) · no retries remain",
                approx_input_tokens=approx_input_tokens,
                output_tokens_received=progress.output_tokens_received,
                duration_ms=progress.duration_ms,
            )
        if progress.phase == "attempt_succeeded":
            output_label = "Structured reply validated"
            return AgentRuntime._output_status_event(
                "validation",
                "completed",
                f"{output_label}{attempt_suffix}",
                approx_input_tokens=approx_input_tokens,
                output_tokens_received=progress.output_tokens_received,
                duration_ms=progress.duration_ms,
            )
        raise ValueError(f"Unsupported structured inference phase: {progress.phase}")

    @staticmethod
    def _attempt_label_suffix(*, attempt: int, max_attempts: int) -> str:
        if (
            not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or not isinstance(max_attempts, int)
            or isinstance(max_attempts, bool)
            or attempt < 1
            or max_attempts < 1
            or attempt > max_attempts
        ):
            raise ValueError("Attempt label requires a valid attempt range")
        if attempt == 1:
            return ""
        return f" · attempt {attempt} of {max_attempts}"

    def _model_context_check_label(self) -> str:
        return f"Checking {self._provider_label} model context"

    @staticmethod
    def _wire_request_input_tokens(wire_request: dict[str, object]) -> int:
        if not isinstance(wire_request, dict):
            raise TypeError("Structured inference wire request must be an object")
        body = wire_request["body"]
        if not isinstance(body, dict):
            raise TypeError("Structured inference wire request body must be an object")
        messages = body["messages"]
        if not isinstance(messages, list):
            raise TypeError("Structured inference wire messages must be a list")
        request_without_messages = {
            key: value for key, value in body.items() if key != "messages"
        }
        return estimate_message_tokens(messages) + estimate_input_tokens(
            request_without_messages
        )

    @staticmethod
    def _status_event(
        action: str,
        status: str,
        label: str,
        *,
        approx_input_tokens: int,
    ) -> dict[str, object]:
        if status not in {"started", "completed"}:
            raise ValueError("Unsupported action status")
        if (
            not isinstance(approx_input_tokens, int)
            or isinstance(approx_input_tokens, bool)
            or approx_input_tokens < 1
        ):
            raise ValueError("Approximate input tokens must be a positive integer")
        return {
            "type": "action_status",
            "action": action,
            "status": status,
            "label": label,
            "approx_input_tokens": approx_input_tokens,
            "output_tokens_received": 0,
            "duration_ms": 0.0,
        }

    @staticmethod
    def _output_status_event(
        action: str,
        status: str,
        label: str,
        *,
        approx_input_tokens: int,
        output_tokens_received: int,
        duration_ms: float,
    ) -> dict[str, object]:
        if (
            not isinstance(output_tokens_received, int)
            or isinstance(output_tokens_received, bool)
            or output_tokens_received < 0
        ):
            raise ValueError("Output tokens received must be a non-negative integer")
        if (
            not isinstance(duration_ms, (int, float))
            or isinstance(duration_ms, bool)
            or not math.isfinite(duration_ms)
            or duration_ms < 0
        ):
            raise ValueError("Activity duration must be a non-negative finite number")
        event = AgentRuntime._status_event(
            action,
            status,
            label,
            approx_input_tokens=approx_input_tokens,
        )
        event["output_tokens_received"] = output_tokens_received
        event["duration_ms"] = float(duration_ms)
        return event
