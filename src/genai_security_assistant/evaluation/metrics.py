"""Count a finished run into the numbers the report prints.

Nothing here touches the graph or the cases: every function reads
EvalResult rows, so the same code summarizes a live run and a cached one.

Two decisions worth knowing before reading the output.

A rate over no judgments is not zero, it is nothing, so the three rates
that depend on a person return None until at least one case is judged.

The mean is reported beside the median rather than instead of it. This
eval set holds both a refusal that calls nothing and a lookup that waits
out a rate limit, by design, and their mean describes neither.
Regenerate the pair with: uv run python scripts/run_eval.py
"""

from __future__ import annotations

from collections import Counter
from statistics import mean, median

from genai_security_assistant.evaluation.harness import CACHEABLE_NODES
from genai_security_assistant.models.evaluation import (
    EvalResult,
    EvalSummary,
    TaskSuccess,
)


def _share(count: int, total: int) -> float | None:
    """The count as a fraction of the total, or None when there is none."""
    return count / total if total else None


def _scored(results: list[EvalResult], verdict: TaskSuccess) -> int:
    """How many judged cases carry this verdict."""
    return sum(1 for result in results if result.case.task_success == verdict)


def error_counts(results: list[EvalResult]) -> dict[str, int]:
    """How often each error type appeared, with "none" for the clean rows.
    A case carrying two errors is counted under both, so these add up to
    more than the number of cases wherever one does.
    """
    counts: Counter[str] = Counter()
    for result in results:
        if result.errors:
            counts.update(result.errors)
        else:
            counts["none"] += 1
    return dict(counts)


def _by_time_then_name(total: tuple[str, int, float]) -> tuple[float, str]:
    """Order one node row: most time first, then by name.
    A named function rather than an inline key, so the checker verifies
    it against this signature instead of against a shape it guessed.
    """
    node, _, spent = total
    return -spent, node


def node_totals(results: list[EvalResult]) -> list[tuple[str, int, float]]:
    """Per node: how often it ran, and how long it took in total.
    Ordered by time spent, because the question this answers is which
    node the run waits on. Ties break by name, so the table is stable.
    Not rounded here: this is the measurement, and how many decimals to
    print is the report's business.

    Keyed by str, not NodeName. Nothing downstream checks that a name is
    one of the twelve - the rows are counted and printed - so carrying
    the Literal through a Counter and back out costs more than it says.
    """
    calls: Counter[str] = Counter()
    spent: dict[str, float] = {}
    for result in results:
        for row in result.nodes:
            calls[row.node] += 1
            spent[row.node] = spent.get(row.node, 0.0) + row.duration_ms

    totals: list[tuple[str, int, float]] = []
    for node, count in calls.items():
        totals.append((node, count, spent[node]))

    totals.sort(key=_by_time_then_name)
    return totals


def replay_rate(results: list[EvalResult]) -> float | None:
    """Share of the calls that have a cache which were answered from one.
    Counted over CACHEABLE_NODES only. The other three tools read a file
    in this repository, and letting their False count here would report
    a cache miss for a request nobody made.
    """
    # Counted in a loop rather than filtered into a list. from_cache
    # carries three values, and no checker narrows away the None inside
    # a comprehension - so summing that list is summing bool | None.
    replayed = 0
    cacheable = 0
    for result in results:
        for row in result.nodes:
            if row.node not in CACHEABLE_NODES or row.from_cache is None:
                continue
            cacheable += 1
            replayed += int(row.from_cache)
    return _share(replayed, cacheable)


def summarize(results: list[EvalResult]) -> EvalSummary:
    """Count one run into the metrics the assignment asks for."""
    if not results:
        raise ValueError("There is nothing to summarize.")

    # One summary describes one run. Mixing modes would average a replayed
    # answer against a fetched one and call the result a latency.
    modes = {result.run_mode for result in results}
    if len(modes) != 1:
        raise ValueError(f"Expected one run mode, got {sorted(modes)}.")

    total = len(results)
    judged = [result for result in results if result.judged]
    applicable = [
        result for result in results if result.groundedness != "not_applicable"
    ]
    # Only where citations had somewhere to go. A clarification run has
    # no answer and an abstention makes no claim, and both would count as
    # compliant for having nothing to get wrong.
    placed = [
        result
        for result in results
        if result.citation_placement not in (None, "not_applicable")
    ]
    cited = sum(1 for result in placed if result.uncited_after == 0)
    good = sum(1 for result in results if result.groundedness == "good")

    latencies = [result.latency_ms for result in results]
    slowest = max(results, key=lambda result: result.latency_ms)

    return EvalSummary(
        run_mode=results[0].run_mode,
        total_cases=total,
        judged_cases=len(judged),
        success_rate=_share(_scored(judged, "yes"), len(judged)),
        partial_rate=_share(_scored(judged, "partial"), len(judged)),
        failure_rate=_share(_scored(judged, "no"), len(judged)),
        groundedness_good_rate=good / total,
        applicable_cases=len(applicable),
        groundedness_good_rate_applicable=_share(good, len(applicable)),
        average_latency_ms=round(mean(latencies)),
        median_latency_ms=round(median(latencies)),
        max_latency_ms=max(latencies),
        slowest_case=slowest.case.id,
        error_counts=error_counts(results),
        placed_cases=len(placed),
        citation_compliance_rate=_share(cited, len(placed)),
    )
