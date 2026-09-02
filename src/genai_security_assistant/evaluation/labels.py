"""Turn one executed run into the columns for HW8.

    MeasuredRun -> route, mode, groundedness, errors, chunks, timing
                -> EvalResult

Two rules decide what belongs in this file.

The errors column describes and task_success judges. A lookup that
answers "no such record" leaves tool_error on the row and the case can
still be a success, because it was asking what happens to an identifier
that doesn't exist. Nothing here settles that; a reader does, in
configs/eval_cases.yaml.

Only what a check can prove is derived. Whether an answer invented
something, or leaned on the wrong chunk, is out of reach of anything
this file could compute, and those three error types stay with the
reader as well.
"""

from __future__ import annotations

from genai_security_assistant.evaluation.harness import ANSWERING_NODES, MeasuredRun
from genai_security_assistant.models.evaluation import (
    EvalCase,
    EvalError,
    EvalResult,
    Groundedness,
    RouteOrMode,
    RunMode,
)
from genai_security_assistant.models.generation import GroundedAnswer
from genai_security_assistant.models.graph import NodeName, TriageState, tool_calls

# The nodes whose work can be replayed from disk. The other three tools
# read a file in this repository, so their from_cache is False with no
# request behind it. Keep in step with ANSWERING_NODES in harness.py.
CACHEABLE_NODES: tuple[NodeName, ...] = ("lookup_cve", *ANSWERING_NODES)


def route_or_mode(state: TriageState) -> RouteOrMode:
    """Say how the run ended, which is not always where it was sent.
    A triage run whose lookup finds no record ends in fallback while its
    route stays triage. So does a guidance run that refuses to answer.
    """
    route = state.get("route")
    assert route is not None
    if route == "clarification":
        return "clarification"
    if route == "triage":
        return "fallback" if state.get("halt_reason") else "tool"

    guidance = state.get("guidance")
    return "RAG" if guidance is not None and not guidance.abstained else "fallback"


def groundedness_of(guidance: GroundedAnswer | None) -> Groundedness:
    """Score how far the answer is held up by what was retrieved.
    Only an answered run is scored. GroundedAnswer.is_grounded already
    takes that position - an abstention is a refusal rather than a bad
    answer - and a refusal makes no claim for a context to support.
    """
    if guidance is None or guidance.abstained:
        return "not_applicable"
    if not guidance.citations:
        return "bad"
    return "partial" if guidance.unsupported_citations else "good"


def detect_errors(
    case: EvalCase, state: TriageState, mode: RouteOrMode
) -> list[EvalError]:
    """Every fault a check can prove, in a fixed order.
    Fixed rather than incidental, so two runs over the same data write
    the same cell and the file diffs cleanly.
    """
    found: list[EvalError] = []

    if state.get("route") != case.expected_route:
        found.append("wrong_route")
    if mode != case.expected_mode:
        found.append("wrong_mode")
    if any(
        record.observation is not None and not record.observation.success
        for record in state.get("nodes", [])
    ):
        found.append("tool_error")

    guidance = state.get("guidance")
    if guidance is not None and not guidance.abstained:
        if not guidance.citations:
            found.append("no_citations")
        if guidance.unsupported_citations:
            found.append("unsupported_citation")

    return found


def reached_network(run: MeasuredRun) -> bool:
    """Whether any call that has a cache had to be made for real.
    Read over CACHEABLE_NODES only: a local tool reports from_cache False
    because it has no cache, and counting that would claim network
    traffic this repository never generates.
    """
    return any(
        row.from_cache is False
        for row in run.nodes
        if row.node in CACHEABLE_NODES
    )


def to_result(
    number: int, case: EvalCase, run: MeasuredRun, run_mode: RunMode
) -> EvalResult:
    """Assemble one row of the eval table from one executed case."""
    state = run.state
    guidance = state.get("guidance")
    mode = route_or_mode(state)

    return EvalResult(
        number=number,
        case=case,
        run_mode=run_mode,
        answer=state.get("final_answer") or "",
        route=state.get("route"),
        route_or_mode=mode,
        status=guidance.status if guidance is not None else None,
        tools_used=[call.tool_name for call in tool_calls(state)],
        # Both lists: what search returned, and the part the answer
        # pointed at. The gap between them is what "two of five chunks
        # contributed nothing" is counted from.
        retrieved_chunks=guidance.retrieved_ids if guidance is not None else [],
        cited_chunks=(
            [citation.chunk_id for citation in guidance.citations]
            if guidance is not None
            else []
        ),
        sources=guidance.sources if guidance is not None else [],
        best_score=guidance.best_score if guidance is not None else None,
        latency_ms=run.latency_ms,
        nodes=run.nodes,
        from_cache=not reached_network(run),
        groundedness_auto=groundedness_of(guidance),
        detected_errors=detect_errors(case, state, mode),
    )
