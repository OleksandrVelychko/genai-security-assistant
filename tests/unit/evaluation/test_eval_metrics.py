"""Unit tests for the numbers a finished run is counted into."""

from __future__ import annotations

from typing import Any

import pytest

from genai_security_assistant.evaluation.metrics import (
    error_counts,
    node_totals,
    replay_rate,
    summarize,
)
from genai_security_assistant.models.evaluation import (
    EvalCase,
    EvalResult,
    NodeTiming,
    RunMode,
)
from genai_security_assistant.models.graph import NodeName


def case(**fields: Any) -> EvalCase:
    defaults: dict[str, Any] = {
        "id": "e01_case",
        "question": "What is excessive agency?",
        "kind": "kb_simple",
        "expected_route": "guidance",
        "expected_mode": "RAG",
        "expected_behavior": "Answer from the knowledge base.",
    }
    return EvalCase.model_validate({**defaults, **fields})


def timing(
    node: NodeName = "lookup_cve",
    duration_ms: float = 1.0,
    from_cache: bool | None = None,
) -> NodeTiming:
    return NodeTiming(
        run_mode="live",
        case_id="e01_case",
        sequence=1,
        node=node,
        duration_ms=duration_ms,
        from_cache=from_cache,
    )


def result(
    number: int = 1,
    run_mode: RunMode = "live",
    latency_ms: int = 100,
    groundedness_auto: str = "good",
    detected: tuple[str, ...] = (),
    nodes: tuple[NodeTiming, ...] = (),
    **case_fields: Any,
) -> EvalResult:
    return EvalResult(
        number=number,
        case=case(**case_fields),
        run_mode=run_mode,
        answer="An answer.",
        route="guidance",
        route_or_mode="RAG",
        status="answered",
        latency_ms=latency_ms,
        nodes=list(nodes),
        groundedness_auto=groundedness_auto,
        detected_errors=list(detected),
    )


# --- rates ----------------------------------------------------------------


def test_rates_are_absent_until_someone_judges():
    """A rate over no judgments is not zero: it does not exist yet."""
    summary = summarize([result()])
    assert summary.judged_cases == 0
    assert summary.success_rate is None
    assert summary.partial_rate is None
    assert summary.failure_rate is None


def test_rates_are_counted_over_the_judged_cases_only():
    summary = summarize(
        [
            result(number=1, task_success="yes"),
            result(number=2, task_success="partial"),
            result(number=3),
        ]
    )
    assert summary.judged_cases == 2
    assert summary.success_rate == 0.5
    assert summary.partial_rate == 0.5


def test_groundedness_is_counted_over_two_denominators():
    """The headline rate is bounded by how much of a set asks the corpus."""
    summary = summarize(
        [
            result(number=1, groundedness_auto="good"),
            result(number=2, groundedness_auto="not_applicable"),
        ]
    )
    assert summary.groundedness_good_rate == 0.5
    assert summary.applicable_cases == 1
    assert summary.groundedness_good_rate_applicable == 1.0


def test_one_summary_describes_one_run():
    """Averaging a replayed answer against a fetched one is not a latency."""
    with pytest.raises(ValueError):
        summarize(
            [result(number=1, run_mode="live"), result(number=2, run_mode="cached")]
        )


def test_an_empty_run_has_nothing_to_summarize():
    with pytest.raises(ValueError):
        summarize([])


# --- errors ---------------------------------------------------------------


def test_a_clean_row_is_counted_under_none():
    assert error_counts([result()]) == {"none": 1}


def test_a_row_with_two_errors_is_counted_under_both():
    counts = error_counts([result(detected=("wrong_route", "tool_error"))])
    assert counts == {"wrong_route": 1, "tool_error": 1}


def test_error_types_are_ordered_by_count_then_by_name():
    summary = summarize(
        [
            result(number=1, detected=("tool_error",)),
            result(number=2, detected=("tool_error",)),
            result(number=3, detected=("missing_context",)),
            result(number=4),
        ]
    )
    assert summary.top_error_types == [
        ("tool_error", 2),
        ("missing_context", 1),
        ("none", 1),
    ]


# --- where the time goes --------------------------------------------------


def test_nodes_are_ordered_by_time_then_by_name():
    rows = [
        result(
            nodes=(
                timing("build_answer", 1.0),
                timing("lookup_cve", 5.0),
                timing("classify_request", 1.0),
            )
        )
    ]
    assert node_totals(rows) == [
        ("lookup_cve", 1, 5.0),
        ("build_answer", 1, 1.0),
        ("classify_request", 1, 1.0),
    ]


def test_a_node_run_twice_is_summed():
    rows = [
        result(number=1, nodes=(timing("build_answer", 1.5),)),
        result(number=2, nodes=(timing("build_answer", 2.5),)),
    ]
    assert node_totals(rows) == [("build_answer", 2, 4.0)]


# --- replay ---------------------------------------------------------------


def test_replay_counts_only_the_nodes_that_have_a_cache():
    rows = [
        result(
            nodes=(
                timing("lookup_cve", from_cache=True),
                timing("check_asset_inventory", from_cache=False),
                timing("assess_exposure", from_cache=None),
            )
        )
    ]
    assert replay_rate(rows) == 1.0


def test_replay_is_absent_when_nothing_could_be_replayed():
    assert replay_rate([result(nodes=(timing("assess_exposure"),))]) is None
