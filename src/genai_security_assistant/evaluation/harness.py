"""Run one eval case through the HW7 graph, with a stopwatch on every node.

The graph is the one HW7 compiled, wired from the same build_graph. What
this module adds is a timer around each node and a trace row per node:

    case -> graph run -> TriageState + list[NodeTiming] + wall clock

Timing sits inside the node rather than between two stream events. The
interval between events also holds the framework's merge work and, for
the first node, the cost of starting the graph, so a row measured that
way would report a number and name it after a node that didn't spend it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, get_args

from genai_security_assistant.config import Settings
from genai_security_assistant.models.evaluation import EvalCase, NodeTiming, RunMode
from genai_security_assistant.models.graph import NodeName, NodeRecord, TriageState
from genai_security_assistant.orchestration.langgraph_flow import LangGraphTriageFlow

# The two nodes that call RAGAnswerer. Keep in sync with langgraph_flow.py:
# a third one would silently lose its cache flag rather than fail.
ANSWERING_NODES: tuple[NodeName, ...] = ("retrieve_guidance", "answer_from_documents")
# The nodes whose work can be replayed from disk. The other three tools
# read a file in this repository and have no cache to miss.
CACHEABLE_NODES: tuple[NodeName, ...] = ("lookup_cve", *ANSWERING_NODES)

NodeFunction = Callable[[TriageState], dict[str, Any]]


@dataclass(frozen=True)
class MeasuredRun:
    """One executed case: the state it finished with, and what it cost."""

    state: TriageState
    nodes: list[NodeTiming]
    latency_ms: int


class TimedTriageFlow(LangGraphTriageFlow):
    """The HW7 graph with a stopwatch around every node.
    The workflow is untouched: build_graph still registers self.<node>,
    and what it finds there is the same method with a timer around it.
    """

    def __init__(
        self, router: Any, registry: Any, retrieval: Any
    ) -> None:
        self.durations: list[tuple[NodeName, float]] = []
        # Before super().__init__, because that call is what runs
        # build_graph, and build_graph registers whatever self.<node>
        # resolves to at that moment. An instance attribute shadows the
        # method of the same name, so the graph comes out wired to the
        # wrappers with no edit to langgraph_flow.py.
        for name in get_args(NodeName):
            setattr(self, name, self._timed(name, getattr(self, name)))
        super().__init__(router, registry, retrieval)

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, live: bool = False
    ) -> TimedTriageFlow:
        """Build as the parent does, with the return type narrowed.
        Declared so that a caller can see run_measured on what comes
        back. The body adds nothing, so how the flow is built still
        lives in one place.
        """
        flow = super().from_settings(settings, live=live)
        assert isinstance(flow, cls)
        return flow

    def _timed(self, name: NodeName, node: NodeFunction) -> NodeFunction:
        """Wrap one node so that it records how long its body took."""

        def timed(state: TriageState) -> dict[str, Any]:
            started = time.perf_counter()
            try:
                return node(state)
            finally:
                # In finally, so a node that raises still leaves a row.
                # Without it the trace would stop one node short and the
                # failure would be read as belonging to the node after.
                self.durations.append(
                    (name, (time.perf_counter() - started) * 1000)
                )

        return timed

def cache_flag(record: NodeRecord, state: TriageState) -> bool | None:
    """Say whether this node's expensive call was replayed from disk.
    None wherever the question does not arise: a node that called
    nothing, a tool that reads a file in this repository, and an answer
    the score gate stopped before the model was reached. False is left to
    mean one thing - a call that could have been replayed and was not.
    """
    if record.node not in CACHEABLE_NODES:
        return None
    if record.observation is not None:
        return record.observation.from_cache
    guidance = state.get("guidance")
    if guidance is None or guidance.status == "abstained_by_gate":
        return None
    return guidance.from_cache

def measure(flow: TimedTriageFlow, case: EvalCase, run_mode: RunMode) -> MeasuredRun:
    """Run one case and assemble a trace row for every node it executed.

    Three lists describe the same nodes in the same order: what each one
    recorded, what each one wrote, and how long each one took. All three
    carry the node's name, so they are zipped strictly and the names
    asserted equal - pairing them by position alone would put one node's
    duration on another node's row and report nothing about it.
    """
    # Cleared here rather than in the wrapper, which would keep only the
    # last node, and not in __init__, because one flow runs every case.
    flow.durations = []

    started = time.perf_counter()
    state, written = flow.run_traced(case.question, case.confirm)
    latency_ms = round((time.perf_counter() - started) * 1000)

    rows: list[NodeTiming] = []
    executed = zip(state["nodes"], written, flow.durations, strict=True)
    for sequence, (record, (name, keys), (timed, elapsed)) in enumerate(
        executed, start=1
    ):
        assert record.node == name == timed
        request = record.request
        observation = record.observation
        rows.append(
            NodeTiming(
                run_mode=run_mode,
                case_id=case.id,
                sequence=sequence,
                node=record.node,
                duration_ms=round(elapsed, 3),
                wrote=keys,
                tool_name=request.tool_name if request is not None else None,
                from_cache=cache_flag(record, state),
                error_code=observation.error_code if observation else None,
                note=record.note,
            )
        )

    return MeasuredRun(state=state, nodes=rows, latency_ms=latency_ms)
