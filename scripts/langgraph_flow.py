"""Run one goal through the LangGraph workflow (HW7).

Run from the project root:

    uv run python scripts/langgraph_flow.py -g "Does CVE-2025-68664 affect us?"
    uv run python scripts/langgraph_flow.py -g "..." --confirm
    uv run python scripts/langgraph_flow.py -g "..." --json
    uv run python scripts/langgraph_flow.py -g "..." --live
    uv run python scripts/langgraph_flow.py --graph

What it prints
--------------
One line per node as the graph finishes it, with the state keys that node
wrote, the call it made and what it concluded; then the state, then the
answer. --json adds the whole final state. --graph prints the workflow as a
Mermaid diagram and exits, which is where the one in README.md comes from.

The order differs from scripts/agent_flow.py on purpose. That script printed
the route first, because routing happened before the plan started. Here
routing is the first node, so it turns up inside the trace like any other.

Caches and keys
---------------
The same ones HW6 uses, because the flow is built from the same settings:
NVD responses in index/cve_cache.json, model output in
index/answers_cache.json, query vectors in index/query_vectors.npz. A goal
whose answers are already there runs with no network and no key. --live
ignores them.

Confirmation
------------
A run that finds an exposed service drafts a finding and stops. --confirm is
the human in the loop: no node can supply it, and without it the graph takes
the edge that leads away from the write.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from pydantic import BaseModel

from genai_security_assistant.config import Settings
from genai_security_assistant.models.graph import (
    NodeName,
    TriageState,
    executed_nodes,
    initial_state,
)
from genai_security_assistant.orchestration.langgraph_flow import LangGraphTriageFlow

LINE = "=" * 78


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one goal through the graph, printing every node."
    )
    parser.add_argument("--goal", "-g", help="What is wanted.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Approve the write. Required before any finding is recorded.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the whole final state after the answer.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Ignore the caches and call out for real.",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Print the workflow as a Mermaid diagram and exit.",
    )
    return parser.parse_args()


def plain(value: Any) -> Any:
    """Turn one state value into something json.dumps accepts.
    AgentState had model_dump for the whole object. A TypedDict has no such
    method, so the Pydantic values inside it are converted one at a time.
    That is the price of the state being a plain dict, and it is paid here
    rather than by weakening what the state is allowed to hold.
    """
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def print_node(number: int, name: str, update: dict[str, Any]) -> None:
    """Print one finished node: what it wrote, what it called, what it said."""
    print(f"{number}. {name}")

    # The line HW6 could not print. A step there mutated a shared object, so
    # nothing could say which fields that step was responsible for; a node
    # returns exactly them.
    written = sorted(key for key in update if key != "nodes")
    print(f"   wrote:       {', '.join(written) if written else '— trace only'}")

    records = update.get("nodes", [])
    if not records:
        return
    record = records[0]

    request = record.request
    if request is not None:
        arguments = json.dumps(request.arguments, sort_keys=True)
        print(f"   call:        {request.tool_name} {arguments}")

    observation = record.observation
    if observation is not None:
        outcome = "ok" if observation.success else observation.error_code
        replayed = ", cached" if observation.from_cache else ""
        print(f"   observation: {outcome}{replayed}")

    print(f"   note:        {record.note}")


def run_and_trace(
    flow: LangGraphTriageFlow, goal: str, confirmed: bool
) -> TriageState:
    """Run the goal, printing each node as the graph finishes it.

    Both stream modes at once: "updates" carries what a node just returned,
    "values" carries the whole state after it. Asking for them together is
    what keeps this to a single run - a second stream would execute every
    node again, including the one that writes.
    """
    print(LINE)
    print(f"Goal: {goal}")
    print(f"Confirmed: {confirmed}")
    print(LINE)

    final: TriageState | None = None
    number = 0
    for mode, chunk in flow.graph.stream(
        initial_state(goal, confirmed), stream_mode=["updates", "values"]
    ):
        if mode == "values":
            final = chunk
            continue
        for name, update in chunk.items():
            number += 1
            print_node(number, name, update)

    assert final is not None
    return final


def print_state(state: TriageState, total_nodes: int) -> None:
    """Print the fields a reader checks first."""
    owner = state.get("owner")
    finding = state.get("recorded_finding")
    ran = executed_nodes(state)

    print()
    print(LINE)
    print("State")
    print(LINE)
    print(f"route:                {state.get('route')}")
    print(f"because:              {state.get('route_reason')}")
    print(f"nodes run:            {len(ran)} of {total_nodes} in the graph")
    print(f"cve_id:               {state.get('cve_id')}")
    print(f"exposure:             {state.get('exposure')}")
    print(f"affected services:    {len(state.get('affected_services', []))}")
    print(f"owner:                {owner.team if owner is not None else None}")
    print(f"pending confirmation: {state.get('pending_confirmation')}")
    print(f"write authorized:     {state.get('write_authorized')}")
    print(f"recorded finding:     {finding.finding_id if finding else None}")
    print(f"halt reason:          {state.get('halt_reason')}")


def print_answer(state: TriageState) -> None:
    """Print what the run would tell the user."""
    print()
    print(LINE)
    print("Answer")
    print(LINE)
    print(state.get("final_answer") or "")


def main() -> None:
    args = parse_args()
    flow = LangGraphTriageFlow.from_settings(Settings(), live=args.live)

    if args.graph:
        # draw_mermaid renders from the compiled graph, so what it prints is
        # the graph that just ran, not a picture kept alongside it.
        print(flow.graph.get_graph().draw_mermaid())
        return

    if not args.goal:
        raise SystemExit("--goal is required unless --graph is given.")

    state = run_and_trace(flow, args.goal, args.confirm)
    print_state(state, total_nodes=len(NodeName.__args__))
    print_answer(state)

    if args.json:
        print()
        print(LINE)
        print("Final state")
        print(LINE)
        # Not sorted: the key order is the order initial_state declares them,
        # which is roughly the order the nodes fill them in.
        print(json.dumps({k: plain(v) for k, v in state.items()}, indent=2))


if __name__ == "__main__":
    main()
