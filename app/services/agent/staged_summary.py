"""Strict structured contracts for complete-scope staged summarization."""

from __future__ import annotations

from dataclasses import dataclass
import math

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

from app.services.agent.token_estimation import estimate_input_tokens

SUMMARY_FINDING_MAX_CHARS = 2_000
SUMMARY_FINDING_MAX_SUPPORTING_NOTES = 24
SUMMARY_MAX_FINDINGS = 128
SUMMARY_PROGRESS_COMPLETE_PERCENT = 100
_SUMMARY_PROGRESS_START_PERCENT = 5
_COMPLETE_BATCH_STATE = "complete"
_LEAST_FRACTION_ONCE_RESPONDING = 0.5
_LEAST_FRACTION_BY_BATCH_STATE = {"queued": 0.0, "writing": 0.0, "responding": _LEAST_FRACTION_ONCE_RESPONDING}
_MOST_FRACTION_FROM_THE_CLOCK = 0.9
# The bar glides to the estimate (a third of the way about every 1.2 seconds), and creeps toward its
# ceiling whatever the estimate says, so it cannot stall.
_BAR_GLIDE_SECONDS = 3.0
_BAR_CREEP_SECONDS = 50.0
_BAR_CEILING_PERCENT = 95.0
_TOKENS_PER_MILLION = 1_000_000
_FEWEST_TIMED_BATCHES = 2
# Batches closer in size than this cannot tell startup cost from time per token.
_LEAST_SIZE_RATIO_FOR_A_LINE = 1.5


class SummaryFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=SUMMARY_FINDING_MAX_CHARS)
    supporting_note_ids: list[str] = Field(..., min_length=1, max_length=SUMMARY_FINDING_MAX_SUPPORTING_NOTES)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if value.strip() == "":
            raise ValueError("Summary finding text must not be blank")
        return value

    @field_validator("supporting_note_ids")
    @classmethod
    def validate_supporting_note_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(value == "" for value in normalized):
            raise ValueError("Supporting note IDs must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Supporting note IDs must be unique per finding")
        return normalized


class SummaryFindingsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[SummaryFinding] = Field(..., max_length=SUMMARY_MAX_FINDINGS)


class SummaryBatchResult(SummaryFindingsResult):
    covered_root_ids: list[str] = Field(..., min_length=1)

    @field_validator("covered_root_ids")
    @classmethod
    def validate_covered_root_ids(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(value == "" for value in normalized):
            raise ValueError("Covered root IDs must not be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("Covered root IDs must be unique")
        return normalized


def attach_summary_coverage(
    *,
    result: SummaryFindingsResult,
    expected_root_ids: tuple[str, ...],
    allowed_note_ids: frozenset[str],
) -> SummaryBatchResult:
    if not isinstance(result, SummaryFindingsResult):
        raise TypeError("result must be SummaryFindingsResult")
    for finding in result.findings:
        unknown_note_ids = set(finding.supporting_note_ids) - allowed_note_ids
        if unknown_note_ids:
            raise ValueError(
                "Summary finding cited note IDs outside the disclosed evidence: "
                + ", ".join(sorted(unknown_note_ids))
            )
    return SummaryBatchResult(
        covered_root_ids=list(expected_root_ids),
        findings=result.findings,
    )


UNCITABLE_STRUCTURAL_PLACEHOLDER = "structural placeholder without disclosed content"
UNCITABLE_NON_EVIDENCE_REFERENCE = (
    "appears in the request but is not citable evidence for this stage"
)
UNCITABLE_ABSENT_FROM_REQUEST = "does not appear anywhere in the request"


def structural_placeholder_note_ids(
    result_trees: tuple[dict[str, object], ...],
) -> frozenset[str]:
    """Return tree nodes serialized only as structure (``is_evidence: false``)."""
    placeholder_ids: set[str] = set()
    pending = list(result_trees)
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            raise TypeError("Serialized result tree nodes must be objects")
        note_id = node["note_id"]
        if not isinstance(note_id, str) or note_id == "":
            raise TypeError("Serialized result tree nodes require note IDs")
        if "is_evidence" in node:
            if node["is_evidence"] is not False:
                raise ValueError("Structural tree nodes must be marked is_evidence false")
            placeholder_ids.add(note_id)
        if "children" in node:
            children = node["children"]
            if not isinstance(children, list):
                raise TypeError("Serialized result tree children must be a list")
            pending.extend(children)
    return frozenset(placeholder_ids)


def classify_uncitable_note_ids(
    *,
    result: SummaryFindingsResult,
    allowed_note_ids: frozenset[str],
    structural_note_ids: frozenset[str],
    request_text: str,
) -> tuple[tuple[str, str], ...]:
    """Explain each cited ID that was not disclosed as citable evidence."""
    if not isinstance(result, SummaryFindingsResult):
        raise TypeError("result must be SummaryFindingsResult")
    rejected_ids = dict.fromkeys(
        note_id
        for finding in result.findings
        for note_id in finding.supporting_note_ids
        if note_id not in allowed_note_ids
    )
    classified: list[tuple[str, str]] = []
    for note_id in rejected_ids:
        reason = UNCITABLE_ABSENT_FROM_REQUEST
        if note_id in structural_note_ids:
            reason = UNCITABLE_STRUCTURAL_PLACEHOLDER
        elif note_id in request_text:
            reason = UNCITABLE_NON_EVIDENCE_REFERENCE
        classified.append((note_id, reason))
    return tuple(classified)


def drop_citations(
    *,
    result: SummaryFindingsResult,
    note_ids: frozenset[str],
) -> tuple[SummaryFindingsResult, int]:
    """result without citations to note_ids, and without the findings left citing nothing;
    with how many findings were dropped."""
    if not isinstance(result, SummaryFindingsResult):
        raise TypeError("result must be SummaryFindingsResult")
    kept: list[SummaryFinding] = []
    for finding in result.findings:
        supporting = [note_id for note_id in finding.supporting_note_ids if note_id not in note_ids]
        if supporting:
            kept.append(finding.model_copy(update={"supporting_note_ids": supporting}))
    return SummaryFindingsResult(findings=kept), len(result.findings) - len(kept)


@dataclass(frozen=True, slots=True)
class ModelTiming:
    """How long a model takes over a batch: a fixed startup cost, then time per token."""

    startup_seconds: float
    seconds_per_million_tokens: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.startup_seconds) or self.startup_seconds < 0:
            raise ValueError("A model's startup time must be zero or more seconds")
        if not math.isfinite(self.seconds_per_million_tokens) or self.seconds_per_million_tokens <= 0:
            raise ValueError("A model's time per token must be above zero")

    def expected_seconds(self, tokens: int) -> float:
        return self.startup_seconds + tokens * self.seconds_per_million_tokens / _TOKENS_PER_MILLION


def fit_model_timing(timed_batches: tuple[tuple[int, float], ...]) -> ModelTiming | None:
    """The line through finished batches (tokens, seconds): two sizes separate startup cost from
    time per token (the maintainer, 2026-11-08). Batches of about one size, or jitter that gives a
    line no model could follow, leave only time per token. None until two batches have finished,
    and while the finished ones took no time a clock can measure (they say nothing about the model)."""
    if len(timed_batches) < _FEWEST_TIMED_BATCHES:
        return None
    sizes = [tokens for tokens, _seconds in timed_batches]
    seconds = [taken for _tokens, taken in timed_batches]
    if sum(seconds) <= 0:
        return None
    time_per_token_only = ModelTiming(
        startup_seconds=0.0, seconds_per_million_tokens=sum(seconds) / sum(sizes) * _TOKENS_PER_MILLION,
    )
    if max(sizes) < min(sizes) * _LEAST_SIZE_RATIO_FOR_A_LINE:
        return time_per_token_only
    mean_size = sum(sizes) / len(sizes)
    mean_seconds = sum(seconds) / len(seconds)
    slope = sum((size - mean_size) * (taken - mean_seconds) for size, taken in zip(sizes, seconds)) / sum(
        (size - mean_size) * (size - mean_size) for size in sizes
    )
    startup_seconds = mean_seconds - slope * mean_size
    if slope <= 0 or startup_seconds < 0:
        return time_per_token_only
    return ModelTiming(startup_seconds=startup_seconds, seconds_per_million_tokens=slope * _TOKENS_PER_MILLION)


def _batch_fraction_done(*, tokens: int, state: str, elapsed_seconds: float, timing: ModelTiming | None) -> float:
    if state == _COMPLETE_BATCH_STATE:
        return 1.0
    least = _LEAST_FRACTION_BY_BATCH_STATE[state]
    if timing is None:
        return least
    return max(least, min(_MOST_FRACTION_FROM_THE_CLOCK, elapsed_seconds / timing.expected_seconds(tokens)))


def summary_progress_percent(
    *,
    batch_tokens: tuple[int, ...],
    batch_states: tuple[str, ...],
    batch_elapsed_seconds: tuple[float, ...],
    timing: ModelTiming | None,
) -> int:
    """How far a summary's batches are, each weighed by its size. Above zero from the first
    moment; the clock moves a batch up to 90% against the model's timing, a batch counts half
    once its response starts arriving, and only finishing completes it."""
    assert len(batch_tokens) == len(batch_states) == len(batch_elapsed_seconds)
    assert all(tokens > 0 for tokens in batch_tokens)
    tokens_done = sum(
        tokens * _batch_fraction_done(tokens=tokens, state=state, elapsed_seconds=elapsed, timing=timing)
        for tokens, state, elapsed in zip(batch_tokens, batch_states, batch_elapsed_seconds)
    )
    percent_to_earn = SUMMARY_PROGRESS_COMPLETE_PERCENT - _SUMMARY_PROGRESS_START_PERCENT
    return _SUMMARY_PROGRESS_START_PERCENT + int(percent_to_earn * tokens_done / sum(batch_tokens))


def advanced_progress_percent(*, shown: float, target: float, seconds: float) -> float:
    """Where the bar goes next: the estimate says where it should be, but an estimate can jump,
    stand still or fall behind, and the bar must do none of those (the maintainer, 2026-11-08:
    "stuck on 27% for like 20 seconds straight"). It glides toward the estimate and always
    creeps, slower as it nears its ceiling; only every batch finishing fills it."""
    assert seconds >= 0
    if target >= SUMMARY_PROGRESS_COMPLETE_PERCENT:
        return float(SUMMARY_PROGRESS_COMPLETE_PERCENT)
    glide = (target - shown) * (1 - math.exp(-seconds / _BAR_GLIDE_SECONDS))
    creep = (_BAR_CEILING_PERCENT - shown) * (1 - math.exp(-seconds / _BAR_CREEP_SECONDS))
    return shown + max(glide, creep, 0.0)


def summary_reference_note_ids(
    results: tuple[SummaryBatchResult, ...],
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        note_id
        for result in results
        for finding in result.findings
        for note_id in finding.supporting_note_ids
    ))


def estimate_summary_results_tokens(
    results: tuple[SummaryBatchResult, ...],
) -> int:
    return estimate_input_tokens([
        result.model_dump(mode="json") for result in results
    ])


def partition_summary_results(
    *,
    results: tuple[SummaryBatchResult, ...],
    token_limit: int,
) -> tuple[tuple[SummaryBatchResult, ...], ...]:
    if not results:
        raise ValueError("Summary reduction requires at least one result")
    if not isinstance(token_limit, int) or isinstance(token_limit, bool) or token_limit < 1:
        raise ValueError("Summary reduction token limit must be positive")
    groups: list[tuple[SummaryBatchResult, ...]] = []
    current: list[SummaryBatchResult] = []
    for result in results:
        if estimate_summary_results_tokens((result,)) > token_limit:
            raise ValueError(
                "One intermediate summary exceeds the configured evidence limit"
            )
        candidate = (*current, result)
        if current and estimate_summary_results_tokens(candidate) > token_limit:
            groups.append(tuple(current))
            current = []
        current.append(result)
    if current:
        groups.append(tuple(current))
    return tuple(groups)
