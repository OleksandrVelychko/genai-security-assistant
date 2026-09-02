"""Write what a run produced: a table, a summary, and a trace file.

    list[EvalResult] -> outputs/eval_results.csv       the table, as data
                     -> outputs/eval_results.md        the table, as prose
                     -> outputs/eval_summary.md        the metrics
                     -> outputs/eval_traces_*.jsonl    one line per node

The CSV carries the thirteen columns according to the assignment (HW8).

Two of those are worth knowing about. The assignment's retrieved_chunks
asks for "chunks or sources used", which is two questions: here that
column holds what search returned, and cited_chunks holds the part the
answer pointed at. They are rarely the same list, and the difference is
what "three of five chunks contributed nothing" is read from.
"""

from __future__ import annotations

import csv
from collections.abc import Sequence
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from typing import Any

from genai_security_assistant.config import Settings
from genai_security_assistant.evaluation.metrics import node_totals, replay_rate
from genai_security_assistant.models.evaluation import EvalResult, EvalSummary

# The assignment's columns, in the assignment's order and spelling. Its
# last column is called notes; the case field behind it is called comment,
# which is what configs/qa_questions.yaml calls the same thing. The name
# is translated in csv_row and nowhere else.
ASSIGNMENT_COLUMNS: tuple[str, ...] = (
    "id",
    "question",
    "expected_behavior",
    "answer",
    "retrieved_chunks",
    "route_or_mode",
    "tools_used",
    "task_success",
    "groundedness",
    "answer_quality",
    "latency_ms",
    "errors",
    "notes",
)

# What this project adds. Kept after the thirteen rather than mixed among
# them, so a reader comparing against the assignment reads left to right
# and stops where the assignment stops.
EXTRA_COLUMNS: tuple[str, ...] = (
    "case_id",
    "kind",
    "expected_route",
    "expected_mode",
    "route",
    "status",
    "cited_chunks",
    "sources",
    "best_score",
    "from_cache",
    "node_ms",
    "overhead_ms",
    "run_mode",
    "citation_placement",
    "uncited_before",
    "uncited_after",
    "repair_note",
)


def _joined(values: Sequence[str]) -> str:
    """One cell out of a list, empty when the list is."""
    return "; ".join(values)


def _errors_cell(result: EvalResult) -> str:
    """The errors cell, which says "none" rather than saying nothing."""
    return "; ".join(result.errors) or "none"


def _percent(value: float | None) -> str:
    """A rate as a percentage, or a dash where there is no rate."""
    return "—" if value is None else f"{value:.1%}"


def _cell(text: str, limit: int | None = None) -> str:
    """One string, safe inside a markdown table cell.
    A pipe ends the column and a newline ends the row, so both go first
    and the length limit is applied to what is left - the other order
    could cut an escape in half.
    """
    flat = " ".join(text.split()).replace("|", "\\|")
    if limit is not None and len(flat) > limit:
        return f"{flat[:limit]}…"
    return flat


def csv_row(result: EvalResult) -> dict[str, Any]:
    """One case as a row, keyed by the column names above."""
    case = result.case
    return {
        "id": result.number,
        "question": case.question,
        "expected_behavior": case.expected_behavior.strip(),
        "answer": result.answer,
        "retrieved_chunks": _joined(result.retrieved_chunks),
        "route_or_mode": result.route_or_mode,
        "tools_used": _joined(result.tools_used),
        # Blank rather than a placeholder while nobody has judged the
        # case: a spreadsheet can count blanks and cannot count "TBD".
        "task_success": case.task_success or "",
        "groundedness": result.groundedness,
        "answer_quality": case.answer_quality or "",
        "latency_ms": result.latency_ms,
        "errors": _errors_cell(result),
        "notes": case.comment.strip(),
        "case_id": case.id,
        "kind": case.kind,
        "expected_route": case.expected_route,
        "expected_mode": case.expected_mode,
        "route": result.route or "",
        "status": result.status or "",
        "cited_chunks": _joined(result.cited_chunks),
        "sources": _joined(result.sources),
        "best_score": "" if result.best_score is None else round(result.best_score, 4),
        "from_cache": result.from_cache,
        "node_ms": result.node_ms,
        "overhead_ms": result.overhead_ms,
        "run_mode": result.run_mode,
        "citation_placement": result.citation_placement or "",
        "uncited_before": ""
        if result.uncited_before is None
        else result.uncited_before,
        "uncited_after": "" if result.uncited_after is None else result.uncited_after,
        "repair_note": result.repair_note or "",
    }


def write_csv(results: list[EvalResult], path: Path) -> None:
    """Write the eval table as data, one row per case."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" is what the csv module asks for. Without it Windows
    # writes \r\r\n and every second row of the file is blank.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=[*ASSIGNMENT_COLUMNS, *EXTRA_COLUMNS]
        )
        writer.writeheader()
        for result in results:
            writer.writerow(csv_row(result))


def write_traces(results: list[EvalResult], path: Path) -> None:
    """Write one line per executed node, in the order the nodes ran.
    Rewritten whole by the run that produced it. This is a build
    artifact, not a log: appending would mix two runs in one file, and
    every count taken from it would then be wrong by whatever overlapped.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [row.model_dump_json() for result in results for row in result.nodes]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_table(results: list[EvalResult]) -> list[str]:
    """The eval table as markdown, with the answers cut down to fit."""
    rows = [
        "| id | question | expected | answer | mode | tools | success "
        "| ground | quality | ms | errors | notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for result in results:
        case = result.case
        rows.append(
            f"| {result.number} | {_cell(case.question, 60)} "
            f"| {_cell(case.expected_behavior, 60)} "
            f"| {_cell(result.answer, 80)} | `{result.route_or_mode}` "
            f"| {_cell(_joined(result.tools_used)) or '—'} "
            f"| {case.task_success or '—'} | {result.groundedness} "
            f"| {case.answer_quality or '—'} | {result.latency_ms} "
            f"| {_errors_cell(result)} | {_cell(case.comment) or '—'} |"
        )
    return rows


def render_case(result: EvalResult) -> list[str]:
    """One case in full: the answer nobody could read in a table cell."""
    case = result.case
    lines = [
        f"### {result.number}. {case.id}",
        "",
        f"**Question:** {case.question}",
        "",
        f"**Expected:** {case.expected_behavior.strip()}",
        "",
        f"**Why this case is here:** {case.note.strip()}",
        "",
        f"**Route:** `{result.route}` → mode `{result.route_or_mode}`"
        f" · status `{result.status or 'no answerer ran'}`"
        f" · {result.latency_ms} ms ({result.node_ms} in nodes,"
        f" {result.overhead_ms} in the framework)",
        "",
        "**Answer:**",
        "",
        "```text",
        result.answer,
        "```",
        "",
    ]

    if result.retrieved_chunks:
        cited = set(result.cited_chunks)
        marked = [
            f"`{chunk_id}`" + ("" if chunk_id in cited else " (not cited)")
            for chunk_id in result.retrieved_chunks
        ]
        lines += [f"**Retrieved:** {', '.join(marked)}", ""]

    lines += [
        "| # | Node | ms | Tool | Replayed | Note |",
        "|---|---|---|---|---|---|",
    ]
    for row in result.nodes:
        replayed = "—" if row.from_cache is None else str(row.from_cache)
        tool = f"`{row.tool_name}`" if row.tool_name else "—"
        lines.append(
            f"| {row.sequence} | `{row.node}` | {row.duration_ms} "
            f"| {tool} | {replayed} | {_cell(row.note)} |"
        )
    lines.append("")
    return lines


def _header(settings: Settings, summary: EvalSummary, title: str) -> list[str]:
    """The provenance block every generated file in this repository has."""
    generation = settings.generation_config()
    return [
        f"# {title}",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        f"Run mode: `{summary.run_mode}` · "
        f"Model: `{generation['model']}` · "
        f"Prompt: `{settings.generation.get('prompt_version')}` · "
        f"Framework: `langgraph {version('langgraph')}`",
        "",
        "> This product uses the NVD API but is not endorsed or certified by",
        "> the NVD.",
        "",
        "Regenerate with `uv run python scripts/run_eval.py --live`.",
        "",
    ]


def write_results_md(
    results: list[EvalResult], summary: EvalSummary, settings: Settings, path: Path
) -> None:
    """Write the eval table as prose, with every answer in full below it."""
    lines = _header(settings, summary, "Evaluation results")
    lines += render_table(results)
    lines += ["", "## Each case in full", ""]
    for result in results:
        lines += render_case(result)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_md(
    results: list[EvalResult],
    summary: EvalSummary,
    settings: Settings,
    path: Path,
    comparison: Sequence[EvalSummary] = (),
) -> None:
    """Write the observability metrics, and the notes written by hand.
    'comparison' holds the summaries of the other runs of the same cases.
    Only their latencies are printed: routing and grounding do not depend
    on where an answer came from, so repeating them would say nothing.
    """
    judged = f"{summary.judged_cases} of {summary.total_cases} judged"
    lines = _header(settings, summary, "Observability metrics")
    lines += [
        "## Metrics",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| total_cases | {summary.total_cases} |",
        f"| success_rate | {_percent(summary.success_rate)} ({judged}) |",
        f"| partial_rate | {_percent(summary.partial_rate)} |",
        f"| failure_rate | {_percent(summary.failure_rate)} |",
        f"| groundedness_good_rate | {_percent(summary.groundedness_good_rate)} |",
        f"| groundedness_good_rate, where it applies | "
        f"| citation_compliance_rate | "
        f"{_percent(summary.citation_compliance_rate)} "
        f"({summary.placed_cases} answers with citations to place) |",
        f"{_percent(summary.groundedness_good_rate_applicable)} "
        f"({summary.applicable_cases} cases) |",
        f"| average_latency_ms | {summary.average_latency_ms} |",
        f"| median_latency_ms | {summary.median_latency_ms} |",
        f"| max_latency_ms | {summary.max_latency_ms} (`{summary.slowest_case}`) |",
        f"| replayed from cache | {_percent(replay_rate(results))} "
        f"of cacheable calls |",
        "",
        "A case with no retrieval behind it cannot be grounded in anything,",
        "so the first groundedness rate is bounded by how much of the set",
        "asks the corpus at all. The second one is over those cases only.",
        "",
        "groundedness_good_rate asks whether a citation resolves to a chunk",
        "the answer was given. citation_compliance_rate asks whether it sits",
        "on the sentence it supports. The first read 100% on a run where most",
        "answers bundled every citation at the end of the paragraph, which is",
        "the gap this column exists to close.",
        "",
        "## top_error_types",
        "",
        "| Error | Cases |",
        "|---|---|",
    ]
    lines += [f"| `{name}` | {count} |" for name, count in summary.top_error_types]

    if comparison:
        lines += [
            "",
            "## The same cases, run the other way",
            "",
            "| Run | Mean ms | Median ms | Max ms |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| `{other.run_mode}` | {other.average_latency_ms} "
            f"| {other.median_latency_ms} | {other.max_latency_ms} |"
            for other in (summary, *comparison)
        ]

    lines += [
        "",
        "## Where the time goes",
        "",
        "One row per node, over every case that executed it.",
        "",
        "| Node | Calls | Total ms |",
        "|---|---|---|",
    ]
    lines += [
        f"| `{node}` | {calls} | {spent:.3f} |"
        for node, calls, spent in node_totals(results)
    ]

    conclusions = settings.path("eval_conclusions")
    if conclusions.exists():
        lines += ["", "## Notes", "", conclusions.read_text(encoding="utf-8").strip()]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
