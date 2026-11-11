from __future__ import annotations

import pytest

from app.services.agent.staged_summary import UNCITABLE_ABSENT_FROM_REQUEST
from app.services.agent.staged_summary import UNCITABLE_NON_EVIDENCE_REFERENCE
from app.services.agent.staged_summary import UNCITABLE_STRUCTURAL_PLACEHOLDER
from app.services.agent.staged_summary import SummaryBatchResult
from app.services.agent.staged_summary import SummaryFindingsResult
from app.services.agent.staged_summary import SummaryFinding
from app.services.agent.staged_summary import attach_summary_coverage
from app.services.agent.staged_summary import classify_uncitable_note_ids
from app.services.agent.staged_summary import partition_summary_results
from app.services.agent.staged_summary import structural_placeholder_note_ids
from app.services.agent.staged_summary import ModelTiming
from app.services.agent.staged_summary import advanced_progress_percent
from app.services.agent.staged_summary import fit_model_timing
from app.services.agent.staged_summary import summary_progress_percent


def test_application_attaches_authoritative_root_coverage() -> None:
    result = attach_summary_coverage(
        result=SummaryFindingsResult(findings=[SummaryFinding(
            text="The notes compare two approaches.",
            supporting_note_ids=["child-a"],
        )]),
        expected_root_ids=("root-a", "root-b"),
        allowed_note_ids=frozenset({"root-a", "child-a", "root-b"}),
    )

    assert result.covered_root_ids == ["root-a", "root-b"]


def test_summary_batch_rejects_invented_note_ids() -> None:
    result = SummaryFindingsResult(
        findings=[
            SummaryFinding(
                text="Unsupported claim.",
                supporting_note_ids=["outside-batch"],
            )
        ],
    )

    with pytest.raises(ValueError, match="outside the disclosed evidence"):
        attach_summary_coverage(
            result=result,
            expected_root_ids=("root-a",),
            allowed_note_ids=frozenset({"root-a"}),
        )


def test_summary_reduction_partitions_all_results_without_reordering() -> None:
    results = tuple(
        SummaryBatchResult(
            covered_root_ids=[f"root-{index}"],
            findings=[SummaryFinding(
                text=(f"Finding {index} " * 80),
                supporting_note_ids=[f"note-{index}"],
            )],
        )
        for index in range(5)
    )

    groups = partition_summary_results(results=results, token_limit=500)

    assert len(groups) > 1
    assert tuple(result for group in groups for result in group) == results


def test_structural_placeholders_are_collected_from_nested_trees() -> None:
    trees = (
        {
            "note_id": "heading",
            "is_evidence": False,
            "children": [
                {"note_id": "match", "content_text": "Evidence"},
                {
                    "note_id": "subheading",
                    "is_evidence": False,
                    "children": [{"note_id": "deep", "content_text": "More"}],
                },
            ],
        },
        {"note_id": "root-evidence", "content_text": "Root"},
    )

    assert structural_placeholder_note_ids(trees) == frozenset({"heading", "subheading"})


def test_uncitable_note_ids_are_classified_for_diagnosis() -> None:
    result = SummaryFindingsResult(findings=[
        SummaryFinding(text="A", supporting_note_ids=["match", "heading"]),
        SummaryFinding(text="B", supporting_note_ids=["from-history", "invented"]),
        SummaryFinding(text="C", supporting_note_ids=["heading"]),
    ])

    assert classify_uncitable_note_ids(
        result=result,
        allowed_note_ids=frozenset({"match"}),
        structural_note_ids=frozenset({"heading"}),
        request_text='[{"content":"Earlier answer cited [[from-history]]"}]',
    ) == (
        ("heading", UNCITABLE_STRUCTURAL_PLACEHOLDER),
        ("from-history", UNCITABLE_NON_EVIDENCE_REFERENCE),
        ("invented", UNCITABLE_ABSENT_FROM_REQUEST),
    )


def test_selected_note_ancestor_is_citable_even_when_structural_in_batch() -> None:
    result = SummaryFindingsResult(findings=[
        SummaryFinding(text="A", supporting_note_ids=["heading"]),
    ])

    assert classify_uncitable_note_ids(
        result=result,
        allowed_note_ids=frozenset({"heading"}),
        structural_note_ids=frozenset({"heading"}),
        request_text="",
    ) == ()


def _percent(batch_tokens, batch_states) -> int:
    return summary_progress_percent(
        batch_tokens=batch_tokens, batch_states=batch_states,
        batch_elapsed_seconds=(0.0,) * len(batch_tokens), timing=None,
    )


def _percent_by_clock(batch_tokens, batch_states, elapsed) -> int:
    return summary_progress_percent(
        batch_tokens=batch_tokens, batch_states=batch_states, batch_elapsed_seconds=elapsed, timing=TIMING,
    )


def test_summary_progress_starts_above_zero_and_counts_a_responding_batch_as_half_done() -> None:
    equal = (100, 100)
    assert _percent(equal, ("queued", "writing")) == 5
    assert _percent(equal, ("responding", "writing")) == 28
    assert _percent(equal, ("responding", "responding")) == 52
    assert _percent(equal, ("complete", "queued")) == 52
    assert _percent(equal, ("complete", "responding")) == 76
    assert _percent(equal, ("complete", "complete")) == 100


def test_summary_progress_weighs_each_batch_by_its_size() -> None:
    assert _percent((300, 100), ("complete", "queued")) == 76
    assert _percent((300, 100), ("queued", "complete")) == 28


def test_summary_progress_refuses_a_state_it_does_not_know() -> None:
    with pytest.raises(KeyError):
        _percent((100,), ("streaming",))


# 10 seconds to start and 100 seconds per million tokens: 100,000 tokens take 20 seconds.
TIMING = ModelTiming(startup_seconds=10.0, seconds_per_million_tokens=100.0)
HUNDRED_K = (100_000, 100_000)


def test_summary_progress_follows_the_clock_while_a_batch_is_reading() -> None:
    assert _percent_by_clock(HUNDRED_K, ("writing", "writing"), (0.0, 0.0)) == 5
    assert _percent_by_clock(HUNDRED_K, ("writing", "writing"), (10.0, 10.0)) == 52
    assert _percent_by_clock(HUNDRED_K, ("writing", "queued"), (10.0, 0.0)) == 28


def test_the_clock_alone_never_takes_a_batch_past_ninety_percent() -> None:
    assert _percent_by_clock(HUNDRED_K, ("writing", "writing"), (500.0, 500.0)) == 90
    assert _percent_by_clock(HUNDRED_K, ("complete", "writing"), (0.0, 500.0)) == 95


def test_a_responding_batch_counts_half_even_when_the_clock_says_less() -> None:
    assert _percent_by_clock(HUNDRED_K, ("responding", "queued"), (2.0, 0.0)) == 28
    assert _percent_by_clock(HUNDRED_K, ("responding", "queued"), (16.0, 0.0)) == 43


def test_two_sizes_separate_startup_cost_from_time_per_token() -> None:
    for timed_batches in (((100_000, 20.0), (200_000, 30.0)), ((100_000, 20.0), (200_000, 30.0), (400_000, 50.0))):
        fitted = fit_model_timing(timed_batches)
        assert fitted.startup_seconds == pytest.approx(TIMING.startup_seconds)
        assert fitted.seconds_per_million_tokens == pytest.approx(TIMING.seconds_per_million_tokens)


def test_timing_needs_two_finished_batches() -> None:
    assert fit_model_timing(()) is None
    assert fit_model_timing(((100_000, 20.0),)) is None
    # Batches no clock could time (Windows' monotonic clock moves in steps of about 15 ms) say
    # nothing about the model: no fit, not an error.
    assert fit_model_timing(((100_000, 0.0), (200_000, 0.0))) is None


def test_batches_of_about_one_size_can_only_give_time_per_token() -> None:
    assert fit_model_timing(((100_000, 20.0), (101_000, 21.0))).startup_seconds == 0.0
    assert fit_model_timing(((100_000, 10.0), (100_000, 30.0))) == ModelTiming(
        startup_seconds=0.0, seconds_per_million_tokens=200.0)


def test_jitter_that_makes_no_sense_falls_back_to_time_per_token() -> None:
    # The bigger batch came back faster: no line through these two means anything.
    assert fit_model_timing(((100_000, 30.0), (200_000, 30.0))) == ModelTiming(
        startup_seconds=0.0, seconds_per_million_tokens=200.0)
    # A line that would start below zero.
    assert fit_model_timing(((100_000, 5.0), (200_000, 30.0))) == ModelTiming(
        startup_seconds=0.0, seconds_per_million_tokens=350.0 / 3.0)


@pytest.mark.parametrize("arguments", [
    {"startup_seconds": -1.0, "seconds_per_million_tokens": 100.0},
    {"startup_seconds": 0.0, "seconds_per_million_tokens": 0.0},
])
def test_a_timing_that_makes_no_sense_is_refused(arguments) -> None:
    with pytest.raises(ValueError):
        ModelTiming(**arguments)


def _shown_each_second(shown: float, target: float, seconds: int) -> list[float]:
    shown_values = []
    for _second in range(seconds):
        shown = advanced_progress_percent(shown=shown, target=target, seconds=1.0)
        shown_values.append(shown)
    return shown_values


def test_the_bar_keeps_moving_when_the_estimate_falls_behind_it() -> None:
    # The maintainer, 2026-11-08: "stuck on 27% for like 20 seconds straight".
    shown_values = _shown_each_second(27.0, 12.0, 20)
    previous = 27.0
    for shown in shown_values:
        assert shown >= previous + 0.5
        previous = shown


def test_the_bar_keeps_moving_when_the_estimate_stands_still() -> None:
    shown_values = _shown_each_second(27.0, 27.0, 20)
    assert shown_values[0] > 27.5
    assert shown_values == sorted(set(shown_values))


def test_a_jump_in_the_estimate_is_a_glide() -> None:
    shown_values = _shown_each_second(30.0, 90.0, 15)
    assert shown_values[0] < 50.0
    assert shown_values == sorted(set(shown_values))
    assert shown_values[-1] > 85.0
    assert max(shown_values) <= 90.0


def test_the_clock_alone_never_takes_the_bar_past_its_ceiling() -> None:
    assert _shown_each_second(5.0, 5.0, 2_000)[-1] <= 95.0


def test_the_bar_is_full_only_when_every_batch_is_done() -> None:
    assert advanced_progress_percent(shown=40.0, target=100.0, seconds=0.0) == 100.0
    assert max(_shown_each_second(40.0, 99.0, 500)) < 100.0


def test_the_bar_does_not_depend_on_how_often_it_is_moved() -> None:
    once = advanced_progress_percent(shown=30.0, target=30.0, seconds=2.0)
    twice = advanced_progress_percent(
        shown=advanced_progress_percent(shown=30.0, target=30.0, seconds=1.0), target=30.0, seconds=1.0,
    )
    assert once == pytest.approx(twice)


def test_no_time_passing_moves_nothing() -> None:
    assert advanced_progress_percent(shown=5.0, target=80.0, seconds=0.0) == 5.0
