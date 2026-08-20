"""Regenerate the agent workflow examples from configs/agent_scenarios.yaml.

Run from the project root:

    uv run python scripts/run_agent_flow_examples.py

The scenarios and the analysis are written by hand in the configuration
while this script runs the workflow for real, so a change to a route, a
rule or a tool turns up here on the next run instead of leaving a
hand-written example quietly wrong.

No API key is needed: every answer these goals produce is already in
index/cve_cache.json, index/query_vectors.npz and index/answers_cache.json.
The confirmed run appends to data/findings.jsonl the first time and nothing
after that, because a finding id is a hash of its own content.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from genai_security_assistant.config import Settings, load_yaml
from genai_security_assistant.models.agent import AgentState
from genai_security_assistant.models.tools import ToolObservation
from genai_security_assistant.orchestration.agent_flow import ControlledAgentFlow


def cell(text: str) -> str:
    """Make one string safe to put in a table cell."""
    return text.replace("|", "\\|")


def arguments_cell(arguments: dict[str, Any]) -> str:
    """Render call arguments short enough for a table.
    The write call carries a title and a summary; the whole finding is
    printed under the trace instead.
    """
    text = json.dumps(arguments, sort_keys=True)
    shortened = f"{text[:56]}…" if len(text) > 56 else text
    return f"`{cell(shortened)}`"


def outcome_cell(observation: ToolObservation | None) -> str:
    """Say how a call ended, and show enough of it to check the answer.
    The outcome alone is not checkable: four steps in a row reporting "ok"
    say nothing about what came back or what the next step read.
    """
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


def state_digest(state: AgentState) -> dict[str, Any]:
    """The state fields a reader checks, small enough to print.
    Not model_dump(): that carries whole CVE records and every observation,
    which runs to pages and buries the few values a branch turned on.
    """
    owner = state.owner
    finding = state.recorded_finding
    return {
        "route": state.route,
        "cve_id": state.cve_id,
        "exposure": state.exposure,
        "affected_services": [
            service.service_id for service in state.affected_services
        ],
        "owner": owner.team if owner is not None else None,
        "pending_confirmation": state.pending_confirmation,
        "recorded_finding": finding.finding_id if finding is not None else None,
        "halt_reason": state.halt_reason,
        "completed_steps": state.completed_steps,
        "tool_calls": [call.tool_name for call in state.tool_calls],
    }


def render_trace(state: AgentState) -> list[str]:
    """One row per executed step: the call it made and what it concluded."""
    rows = [
        "| # | Step | Tool called | Observation | Note |",
        "|---|---|---|---|---|",
    ]
    for number, step in enumerate(state.steps, start=1):
        request = step.request
        call = (
            f"`{request.tool_name}` {arguments_cell(request.arguments)}"
            if request is not None
            else "—"
        )
        rows.append(
            f"| {number} | `{step.step}` | {call} | "
            f"{outcome_cell(step.observation)} | {cell(step.note)} |"
        )
    return rows


def render_example(
    number: int, example: dict[str, Any], state: AgentState
) -> list[str]:
    """Render one scenario: the reason it is here, then the run."""
    lines = [
        f"### {number}. {example['goal']}",
        "",
        example["why"].strip(),
        "",
        f"**Question:** {example['goal']}",
        "",
        f"**Route:** `{state.route}` — {state.route_reason}",
        "",
        f"**Confirmed by a human:** {state.confirmed}",
        "",
        f"**Planned steps:** {len(state.plan)} · "
        f"**Completed:** {len(state.completed_steps)}",
        "",
    ]
    lines += render_trace(state)

    finding = state.proposed_finding
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
        "**State after the last step:**",
        "",
        "```json",
        json.dumps(state_digest(state), indent=2),
        "```",
        "",
        "**Final answer:**",
        "",
        "```text",
        state.final_answer or "",
        "```",
        "",
    ]
    return lines


def render_paths(rows: list[tuple[str, AgentState]]) -> list[str]:
    """One row per outcome the workflow can reach, each one executed."""
    lines = [
        "| Goal | Confirmed | Route | Exposure | Steps | Calls | Wrote |",
        "|---|---|---|---|---|---|---|",
    ]
    for goal, state in rows:
        finding = state.recorded_finding
        written = f"`{finding.finding_id}`" if finding is not None else "—"
        lines.append(
            f"| {cell(goal)} | {state.confirmed} | `{state.route}` | "
            f"{state.exposure or '—'} | "
            f"{len(state.completed_steps)} of {len(state.plan)} | "
            f"{len(state.tool_calls)} | {written} |"
        )
    return lines


def main() -> None:
    settings = Settings()
    config = load_yaml(settings.path("agent_scenarios"))
    flow = ControlledAgentFlow.from_settings(settings)
    generation = settings.generation_config()

    lines = [
        "# Controlled agent workflow — traced examples",
        "",
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        f"Model: `{generation['model']}` · Router: `{flow.router.name}`",
        "",
        "> This product uses the NVD API but is not endorsed or certified by",
        "> the NVD.",
        "",
        "Regenerate with `uv run python scripts/run_agent_flow_examples.py`.",
        "The prose is written by hand in `configs/agent_scenarios.yaml` and",
        "`configs/agent_conclusions.md`; every route, call, observation,",
        "state and answer below is produced by running the workflow.",
        "",
        "The assignment asks for one `State after step` per example. This",
        "workflow runs up to eight steps, so each step gets a row of its own",
        "in the trace and the state is printed once, after the last one.",
        "",
        "## Examples",
        "",
    ]

    for number, example in enumerate(config["examples"], start=1):
        state = flow.run(example["goal"], confirmed=example.get("confirm", False))
        lines += render_example(number, example, state)

    lines += [
        "## Every path, run",
        "",
        "One row per outcome the workflow can reach. Each was executed for",
        "this report; none of it is written by hand.",
        "",
    ]
    paths = []
    for row in config["paths"]:
        state = flow.run(row["goal"], confirmed=row.get("confirm", False))
        paths.append((row["goal"], state))
    lines += render_paths(paths)

    lines += [
        "",
        "## Notes",
        "",
        settings.path("agent_conclusions").read_text(encoding="utf-8").strip(),
        "",
    ]

    destination = settings.path("agent_flow_examples")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
