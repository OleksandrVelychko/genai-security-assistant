"""Run one goal through the controlled agent workflow (HW6).

Run from the project root:

    uv run python scripts/agent_flow.py -g "Does CVE-2025-68664 affect us?"
    uv run python scripts/agent_flow.py -g "..." --confirm
    uv run python scripts/agent_flow.py -g "..." --json
    uv run python scripts/agent_flow.py -g "..." --live

What it prints
--------------
The route the goal took and why, then every step that ran with the call it
made and what it concluded, then the answer. --json adds the whole
AgentState, which is what outputs/agent_flow_examples.md is built from.

Caches and keys
---------------
NVD responses live in index/cve_cache.json, model output in
index/answers_cache.json and query vectors in index/query_vectors.npz. A
goal whose answers are already there runs with no network and no key.
--live ignores them.

Confirmation
------------
A run that finds an exposed service drafts a finding and stops. --confirm
is the human in the loop: no step can supply it, and nothing is written
without it.
"""

from __future__ import annotations

import argparse
import json

from genai_security_assistant.config import Settings
from genai_security_assistant.models.agent import AgentState
from genai_security_assistant.orchestration.agent_flow import ControlledAgentFlow

LINE = "=" * 78


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route one goal and run the workflow it names."
    )
    parser.add_argument("--goal", "-g", required=True, help="What is wanted.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Approve the write. Required before any finding is recorded.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the whole AgentState after the answer.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Ignore the caches and call out for real.",
    )
    return parser.parse_args()


def print_route(state: AgentState) -> None:
    """Print the goal, where it was sent, and the plan that follows."""
    print(LINE)
    print(f"Goal: {state.user_goal}")
    print(LINE)
    print(f"Route:     {state.route}")
    print(f"Because:   {state.route_reason}")
    print(f"Confirmed: {state.confirmed}")
    print(f"Plan:      {' -> '.join(state.plan)}")


def print_trace(state: AgentState) -> None:
    """Print every step that ran, with the call it made and its note."""
    print()
    print(LINE)
    print(f"Trace: {len(state.completed_steps)} of {len(state.plan)} planned steps")
    print(LINE)
    for number, step in enumerate(state.steps, start=1):
        print(f"{number}. {step.step}")

        request = step.request
        if request is not None:
            arguments = json.dumps(request.arguments, sort_keys=True)
            print(f"   call:        {request.tool_name} {arguments}")

        observation = step.observation
        if observation is not None:
            outcome = "ok" if observation.success else observation.error_code
            replayed = ", cached" if observation.from_cache else ""
            print(f"   observation: {outcome}{replayed}")

        print(f"   note:        {step.note}")


def print_state(state: AgentState) -> None:
    """Print the fields a reader checks first."""
    owner = state.owner
    finding = state.recorded_finding

    print()
    print(LINE)
    print("State")
    print(LINE)
    print(f"cve_id:               {state.cve_id}")
    print(f"exposure:             {state.exposure}")
    print(f"affected services:    {len(state.affected_services)}")
    print(f"owner:                {owner.team if owner is not None else None}")
    print(f"pending confirmation: {state.pending_confirmation}")
    print(f"recorded finding:     {finding.finding_id if finding else None}")
    print(f"halt reason:          {state.halt_reason}")


def print_answer(state: AgentState) -> None:
    """Print what the run would tell the user."""
    print()
    print(LINE)
    print("Answer")
    print(LINE)
    print(state.final_answer or "")


def main() -> None:
    args = parse_args()
    flow = ControlledAgentFlow.from_settings(Settings(), live=args.live)
    state = flow.run(args.goal, confirmed=args.confirm)

    print_route(state)
    print_trace(state)
    print_state(state)
    print_answer(state)

    if args.json:
        print()
        print(LINE)
        print("AgentState")
        print(LINE)
        # Not sorted: the field order is the order the steps fill them in,
        # and that order is half of what the state is showing.
        print(json.dumps(state.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    main()
