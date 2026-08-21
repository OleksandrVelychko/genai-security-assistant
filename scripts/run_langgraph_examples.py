"""Regenerate the graph workflow examples from configs/langgraph_scenarios.yaml.

Run from the project root:

    uv run python scripts/run_langgraph_examples.py

The scenarios and the analysis are written by hand in the configuration
while this script runs the graph for real, so a change to a node, an edge
or a rule turns up here on the next run instead of leaving a hand-written
example quietly wrong. The diagram at the top is drawn from the compiled
graph for the same reason.

No API key is needed: every answer these goals produce is already in
index/cve_cache.json, index/query_vectors.npz and index/answers_cache.json.
The confirmed run appends to data/findings.jsonl only if the HW6 report has
not already written that finding - a finding id is a hash of its content,
and both implementations produce the same content.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from importlib.metadata import version
from typing import Any

from genai_security_assistant.config import Settings, load_yaml
from genai_security_assistant.models.graph import (
    NodeName,
    TriageState,
    executed_nodes,
    tool_calls,
)
from genai_security_assistant.models.tools import ToolObservation
from genai_security_assistant.orchestration.graph_diagram import readable_mermaid
from genai_security_assistant.orchestration.langgraph_flow import LangGraphTriageFlow

# One traced run, as this report holds it: the state it ended with and the
# keys each node wrote, in the order the nodes ran.
Run = tuple[TriageState, list[list[str]]]


def cell(text: str) -> str:
    """Make one string safe to put in a table cell."""
    return text.replace("|", "\\|")


def arguments_cell(arguments: dict[str, Any]) -> str:
    """Render call arguments short enough for a table."""
    text = json.dumps(arguments, sort_keys=True)
    shortened = f"{text[:56]}…" if len(text) > 56 else text
    return f"`{cell(shortened)}`"


def outcome_cell(observation: ToolObservation | None) -> str:
    """Say how a call ended, and show enough of it to check the answer."""
    if observation is None:
        return "—"
    if not observation.success:
        return f"`{observation.error_code}`"

    outcome = "ok, cached" if observation.from_cache else "ok"
    data = observation.data
    if "services" in data:
        names = [row["service_id"] for row in data["services"]]
        detail = ", ".join(names) if names else "no service"
    elif "vuln_status" in data:
        detail = f"{data['vuln_status']}, CVSS {data.get('cvss_score')}"
    elif "team" in data:
        detail = str(data["team"])
    elif "finding_id" in data:
        detail = str(data["finding_id"])
    else:
        detail = ""
    return f"{outcome} · {cell(detail)}" if detail else outcome


def state_digest(state: TriageState) -> dict[str, Any]:
    """The state fields a reader checks, small enough to print.

    Not the whole state: that carries a CVE record, a grounded answer and
    every observation, which runs to pages and buries the few values a
    branch turned on.
    """
    owner = state.get("owner")
    finding = state.get("recorded_finding")
    return {
        "route": state.get("route"),
        "cve_id": state.get("cve_id"),
        "exposure": state.get("exposure"),
        "affected_services": [
            service.service_id for service in state.get("affected_services", [])
        ],
        "owner": owner.team if owner is not None else None,
        "pending_confirmation": state.get("pending_confirmation"),
        "write_authorized": state.get("write_authorized"),
        "recorded_finding": finding.finding_id if finding is not None else None,
        "halt_reason": state.get("halt_reason"),
        "executed_nodes": executed_nodes(state),
        "tool_calls": [call.tool_name for call in tool_calls(state)],
    }


def render_trace(run: Run) -> list[str]:
    """One row per executed node: what it wrote, called and concluded.

    The 'Wrote' column is the one HW6's report had no way to fill. A step
    there mutated a shared object and nothing recorded which fields it was
    responsible for; a node returns exactly them, and the framework merges
    what it returned.
    """
    state, written = run
    rows = [
        "| # | Node | Wrote to state | Tool called | Observation | Note |",
        "|---|---|---|---|---|---|",
    ]
    for number, (record, keys) in enumerate(zip(state["nodes"], written), start=1):
        request = record.request
        call = (
            f"`{request.tool_name}` {arguments_cell(request.arguments)}"
            if request is not None
            else "—"
        )
        fields = ", ".join(f"`{key}`" for key in keys) if keys else "—"
        rows.append(
            f"| {number} | `{record.node}` | {fields} | {call} | "
            f"{outcome_cell(record.observation)} | {cell(record.note)} |"
        )
    return rows


def render_example(number: int, example: dict[str, Any], run: Run) -> list[str]:
    """Render one scenario: the reason it is here, then the run."""
    state, _ = run
    lines = [
        f"### {number}. {example['goal']}",
        "",
        example["why"].strip(),
        "",
        f"**Question:** {example['goal']}",
        "",
        f"**Route:** `{state.get('route')}` — {state.get('route_reason')}",
        "",
        f"**Confirmed by a human:** {state.get('confirmed')}",
        "",
        f"**Nodes run:** {len(executed_nodes(state))} of "
        f"{len(NodeName.__args__)} in the graph",
        "",
    ]
    lines += render_trace(run)

    finding = state.get("proposed_finding")
    if finding is not None:
        lines += [
            "",
            "**Finding drafted:**",
            "",
            "```json",
            json.dumps(finding.model_dump(), indent=2),
            "```",
        ]

    lines += [
        "",
        "**Final state:**",
        "",
        "```json",
        json.dumps(state_digest(state), indent=2),
        "```",
        "",
        "**Final answer:**",
        "",
        "```text",
        state.get("final_answer") or "",
        "```",
        "",
    ]
    return lines


def render_paths(rows: list[tuple[str, TriageState]]) -> list[str]:
    """One row per outcome the graph can reach, each one executed."""
    total = len(NodeName.__args__)
    lines = [
        "| Goal | Confirmed | Route | Exposure | Nodes | Calls | Wrote |",
        "|---|---|---|---|---|---|---|",
    ]
    for goal, state in rows:
        finding = state.get("recorded_finding")
        written = f"`{finding.finding_id}`" if finding is not None else "—"
        lines.append(
            f"| {cell(goal)} | {state.get('confirmed')} | "
            f"`{state.get('route')}` | {state.get('exposure') or '—'} | "
            f"{len(executed_nodes(state))} of {total} | "
            f"{len(tool_calls(state))} | {written} |"
        )
    return lines


def main() -> None:
    settings = Settings()
    config = load_yaml(settings.path("langgraph_scenarios"))
    flow = LangGraphTriageFlow.from_settings(settings)
    generation = settings.generation_config()

    lines = [
        "# LangGraph workflow — traced examples",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        f"Framework: `langgraph {version('langgraph')}` · "
        f"Model: `{generation['model']}` · Router: `{flow.router.name}`",
        "",
        "> This product uses the NVD API but is not endorsed or certified by",
        "> the NVD.",
        "",
        "Regenerate with `uv run python scripts/run_langgraph_examples.py`.",
        "The prose is written by hand in `configs/langgraph_scenarios.yaml`",
        "and `configs/langgraph_conclusions.md`; the diagram, every route,",
        "node, call, observation, state and answer below is produced by",
        "running the graph.",
        "",
        "## The graph",
        "",
        "Drawn from the compiled graph, so it is the workflow that ran and",
        "not a picture kept beside it. A dotted edge was chosen by a",
        "function; a coloured node is one such a function reads.",
        "",
        "```mermaid",
        readable_mermaid(flow.graph),
        "```",
        "",
        "## Examples",
        "",
    ]

    for number, example in enumerate(config["examples"], start=1):
        run = flow.run_traced(example["goal"], example.get("confirm", False))
        lines += render_example(number, example, run)

    lines += [
        "## Every path, run",
        "",
        "One row per outcome the graph can reach. Each was executed for this",
        "report; none of it is written by hand.",
        "",
    ]
    paths = [
        (row["goal"], flow.run(row["goal"], row.get("confirm", False)))
        for row in config["paths"]
    ]
    lines += render_paths(paths)

    lines += [
        "",
        "## Notes",
        "",
        settings.path("langgraph_conclusions").read_text(encoding="utf-8").strip(),
        "",
    ]

    destination = settings.path("langgraph_examples")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
