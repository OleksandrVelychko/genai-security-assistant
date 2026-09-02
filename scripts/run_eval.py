"""Run the eval set through the graph and write the HW8 deliverables.

Run from the project root:

    uv run python scripts/run_eval.py          # replays index/*.json
    uv run python scripts/run_eval.py --live   # calls OpenAI and NVD

--live runs the cases twice, live first and then out of the cache it has
just filled, so one report can put the two latencies side by side.

The live half is what the committed files were built from: a replayed
answer costs microseconds and measures nothing about the system. The
cached half is what a clone with no API key can reproduce, and the two
differ in latency alone - the answers, routes and citations are the same.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from genai_security_assistant.config import Settings
from genai_security_assistant.evaluation.harness import TimedTriageFlow, measure
from genai_security_assistant.evaluation.labels import to_result
from genai_security_assistant.evaluation.metrics import summarize
from genai_security_assistant.evaluation.reporting import (
    write_csv,
    write_results_md,
    write_summary_md,
    write_traces,
)
from genai_security_assistant.models.evaluation import (
    EvalCase,
    EvalResult,
    EvalSummary,
    RunMode,
)

# Which configured path holds each mode's trace. One file per mode, so a
# run rewrites its own and leaves the other alone.
TRACE_PATHS: dict[RunMode, str] = {
    "live": "eval_traces_live",
    "cached": "eval_traces_cached",
}

# The two run plans, named rather than written inline. Tuples because a
# list of string literals is a list[str], which is not a list[RunMode] -
# lists are invariant - and because the plan does not change while it
# runs. The order carries meaning: live goes first, so the cached half
# replays the cache that the live half has just filled.
LIVE_THEN_CACHED: tuple[RunMode, ...] = ("live", "cached")
CACHED_ONLY: tuple[RunMode, ...] = ("cached",)


def load_cases(settings: Settings) -> list[EvalCase]:
    """Read configs/eval_cases.yaml into typed cases, in file order."""
    raw = yaml.safe_load(settings.path("eval_cases").read_text(encoding="utf-8"))
    return [EvalCase.model_validate(case) for case in raw["cases"]]


def run_cases(
    cases: list[EvalCase], run_mode: RunMode, settings: Settings
) -> list[EvalResult]:
    """Run every case once, printing each as it finishes.
    The flow is built once and reused, so no case pays for loading the
    index. The progress lines are here because a live run spends most of
    its time inside the NVD client's own rate limit and looks stuck.
    """
    print(f"\n{run_mode} run")
    flow = TimedTriageFlow.from_settings(settings, live=(run_mode == "live"))

    results: list[EvalResult] = []
    for number, case in enumerate(cases, start=1):
        result = to_result(number, case, measure(flow, case, run_mode), run_mode)
        results.append(result)
        print(
            f"  {number:>2}. {case.id:<34} {result.route_or_mode:<14}"
            f"{result.latency_ms:>7} ms"
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="call OpenAI and NVD for real, then run the cases again cached",
    )
    args = parser.parse_args()

    settings = Settings()
    cases = load_cases(settings)

    modes = LIVE_THEN_CACHED if args.live else CACHED_ONLY
    runs: list[tuple[list[EvalResult], EvalSummary]] = []
    written: list[Path] = []

    for run_mode in modes:
        results = run_cases(cases, run_mode, settings)
        trace_path = settings.path(TRACE_PATHS[run_mode])
        write_traces(results, trace_path)
        written.append(trace_path)
        runs.append((results, summarize(results)))

    # The table and the summary describe the first run: live when it ran,
    # cached otherwise. Only the latencies differ between the two, and
    # those are what the comparison block carries.
    results, summary = runs[0]
    csv_path = settings.path("eval_results_csv")
    results_path = settings.path("eval_results_md")
    summary_path = settings.path("eval_summary")

    write_csv(results, csv_path)
    write_results_md(results, summary, settings, results_path)
    write_summary_md(
        results,
        summary,
        settings,
        summary_path,
        comparison=[other for _, other in runs[1:]],
    )
    written += [csv_path, results_path, summary_path]

    print()
    for path in written:
        print(f"Wrote {path}")

    if summary.judged_cases == 0:
        print(
            "\nNo case has been judged yet. task_success, answer_quality and "
            "notes are empty in configs/eval_cases.yaml, so the report prints "
            "a dash for the three rates that depend on them."
        )


if __name__ == "__main__":
    main()
