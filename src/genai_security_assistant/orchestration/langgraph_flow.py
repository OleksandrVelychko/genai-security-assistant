"""The HW6 workflow, rebuilt as a LangGraph state graph (HW7).

    START -> classify_request -> one of three branches -> build_answer -> END

agent_flow.run_triage holds that order as a method that calls eight others
and reads their return values to decide whether to carry on. Here the order
lives in build_graph, as edges: a node returns what it wrote, and the edge
under it reads that to choose what runs next.

What each layer had to do to move:

    routing rules        agent_router.py          called by a node, unchanged
    triage decisions     triage_rules.py          called by nodes, unchanged
    tools                tools/registry.py        unchanged
    retrieval            RAGAnswerer              unchanged
    answer composition   agent_flow.final_answer  called by a node, unchanged
    the state            models/agent.py          re-declared as a TypedDict
    the trace            add_step()               replaced by a reducer
    the order of steps   agent_flow.run_triage    replaced by edges

Read the two halves. Nothing in the top half is a decision this file makes
differently; everything in the bottom half is about how a step is called,
how it reports what it did, and where the order is written down.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from genai_security_assistant.config import Settings
from genai_security_assistant.generation.answering import RAGAnswerer
from genai_security_assistant.models.agent import AgentState
from genai_security_assistant.models.graph import NodeRecord, TriageState, initial_state
from genai_security_assistant.models.tools import (
    CveRecord,
    FindingRecord,
    ServiceExposure,
    ServiceOwner,
    ToolRequest,
)
from genai_security_assistant.orchestration.agent_flow import final_answer
from genai_security_assistant.orchestration.agent_router import AgentRouter
from genai_security_assistant.orchestration.pipeline import Answerer
from genai_security_assistant.orchestration.triage_rules import (
    build_finding,
    exposed_services,
    exposed_summary,
    exposure_of,
    guidance_question,
)
from genai_security_assistant.tools.registry import ToolRegistry, build_agent_registry


def as_agent_state(state: TriageState) -> AgentState:
    """Read a graph state as the HW6 state, for answer composition only.

    agent_flow.final_answer and the functions under it turn a finished run
    into prose and care nothing for how it was orchestrated. Calling them is
    what keeps the two implementations from wording the same answer two ways.

    What comes back is not an execution record and must not be serialized as
    one. `steps` stays empty: the trace lives in the graph state's `nodes`,
    and two of those names have no StepName to map onto.
    """
    return AgentState(
        user_goal=state["user_goal"],
        confirmed=state["confirmed"],
        route=state.get("route"),
        route_reason=state.get("route_reason", ""),
        cve_id=state.get("cve_id"),
        cve_record=state.get("cve_record"),
        affected_services=state.get("affected_services", []),
        exposure=state.get("exposure"),
        guidance=state.get("guidance"),
        owner=state.get("owner"),
        proposed_finding=state.get("proposed_finding"),
        pending_confirmation=state.get("pending_confirmation", False),
        recorded_finding=state.get("recorded_finding"),
        clarification_question=state.get("clarification_question"),
        halt_reason=state.get("halt_reason"),
    )


class LangGraphTriageFlow:
    """The same three workflows as ControlledAgentFlow, wired as a graph."""

    def __init__(
        self, router: AgentRouter, registry: ToolRegistry, retrieval: Answerer
    ) -> None:
        self.router = router
        self.registry = registry
        self.retrieval = retrieval
        self.graph = self.build_graph()

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, live: bool = False
    ) -> LangGraphTriageFlow:
        """Build everything from configs/base.yaml.
        Identical to ControlledAgentFlow.from_settings, deliberately: the two
        implementations answer from the same index, the same caches and the
        same four tools, or the report compares two different systems.
        """
        resolved = settings or Settings()
        return cls(
            router=AgentRouter(),
            registry=build_agent_registry(resolved, live=live),
            retrieval=RAGAnswerer.from_settings(resolved, live=live),
        )

    # -- nodes -------------------------------------------------------------
    # One contract for every node: read the state, return only the fields
    # this node wrote. HW6 gave the steps that could end a run a return type
    # of bool, so a signature said whether a step was a branch. Here every
    # signature is the same, and the edges say it instead.

    def classify_request(self, state: TriageState) -> dict[str, Any]:
        """Choose the branch. Reads the goal and executes nothing.
        In HW6 this was not a step at all - run() called the router before
        the plan started. A graph has no "before".
        """
        decision = self.router.route(state["user_goal"])
        return {
            "route": decision.route,
            "route_reason": decision.reason,
            "cve_id": decision.cve_id,
            "clarification_question": decision.question,
            "nodes": [
                NodeRecord(
                    node="classify_request",
                    note=f"Sent to {decision.route}: {decision.reason}",
                )
            ],
        }

    def lookup_cve(self, state: TriageState) -> dict[str, Any]:
        """Read the CVE record, or set halt_reason when there is none.
        That field is what the edge under this node reads. In HW6 the same
        fact was carried by returning False.
        """
        request = ToolRequest(
            tool_name="lookup_cve",
            arguments={"cve_id": state["cve_id"]},
            proposed_by=self.router.name,
        )
        observation = self.registry.run(request)

        if not observation.success:
            return {
                "halt_reason": observation.error_message,
                "nodes": [
                    NodeRecord(
                        node="lookup_cve",
                        note="No record to triage.",
                        request=request,
                        observation=observation,
                    )
                ],
            }

        record = CveRecord.model_validate(observation.data)
        return {
            "cve_record": record,
            "nodes": [
                NodeRecord(
                    node="lookup_cve",
                    note=f"{record.cve_id} is {record.vuln_status}.",
                    request=request,
                    observation=observation,
                )
            ],
        }

    def check_asset_inventory(self, state: TriageState) -> dict[str, Any]:
        """Read which deployed services this CVE reaches.
        An empty result is a success: "nothing here runs it" is an answer.
        A failed call halts instead, because reading a broken inventory as
        "nothing runs this" would report a safety nothing ever claimed.
        """
        request = ToolRequest(
            tool_name="check_asset_inventory",
            arguments={"cve_id": state["cve_id"]},
            proposed_by="langgraph_flow",
        )
        observation = self.registry.run(request)

        if not observation.success:
            return {
                "halt_reason": observation.error_message,
                "nodes": [
                    NodeRecord(
                        node="check_asset_inventory",
                        note="The inventory did not answer.",
                        request=request,
                        observation=observation,
                    )
                ],
            }

        services = [
            ServiceExposure.model_validate(row) for row in observation.data["services"]
        ]
        return {
            "affected_services": services,
            "nodes": [
                NodeRecord(
                    node="check_asset_inventory",
                    note=f"Services running the component: {len(services)}.",
                    request=request,
                    observation=observation,
                )
            ],
        }

    def assess_exposure(self, state: TriageState) -> dict[str, Any]:
        """Decide what the inventory rows mean for this deployment.
        Calls nothing, and is still the node the run turns on: five nodes
        downstream run or do not run because of the one word it returns.
        """
        services = state.get("affected_services", [])
        exposure = exposure_of(services)
        notes = {
            "not_affected": "Nothing deployed runs the affected component.",
            "patched": "Every affected service is already on the fix.",
            "exposed": f"{exposed_summary(services)}.",
        }
        return {
            "exposure": exposure,
            "nodes": [NodeRecord(node="assess_exposure", note=notes[exposure])],
        }

    def retrieve_guidance(self, state: TriageState) -> dict[str, Any]:
        """Ask the corpus how this class of flaw is mitigated.
        Reached only when a service is exposed, so a patched run spends no
        model call at all.
        """
        record = state.get("cve_record")
        assert record is not None
        guidance = self.retrieval.answer(guidance_question(record))
        return {
            "guidance": guidance,
            "nodes": [
                NodeRecord(
                    node="retrieve_guidance",
                    note=f"{guidance.status}, {len(guidance.citations)} citations.",
                )
            ],
        }

    def identify_owner(self, state: TriageState) -> dict[str, Any]:
        """Read who to notify. A missing owner does not stop the run.
        Which is why the edge under this node is unconditional: the lookup
        can fail and the finding is still worth writing.
        """
        exposed = exposed_services(state.get("affected_services", []))
        request = ToolRequest(
            tool_name="get_service_owner",
            # From the previous observation, never from the goal's wording.
            arguments={"service_id": exposed[0].service_id},
            proposed_by="langgraph_flow",
        )
        observation = self.registry.run(request)
        owner = (
            ServiceOwner.model_validate(observation.data)
            if observation.success
            else None
        )
        note = (
            f"Notify {owner.team}."
            if owner is not None
            else "No owner recorded; the finding is still worth writing."
        )
        return {
            "owner": owner,
            "nodes": [
                NodeRecord(
                    node="identify_owner",
                    note=note,
                    request=request,
                    observation=observation,
                )
            ],
        }

    def propose_finding(self, state: TriageState) -> dict[str, Any]:
        """Draft the finding the assessment justifies. Writes nothing."""
        record = state.get("cve_record")
        assert record is not None
        finding = build_finding(record, state.get("affected_services", []))
        return {
            "proposed_finding": finding,
            "nodes": [
                NodeRecord(node="propose_finding", note=f"Severity {finding.severity}.")
            ],
        }

    def confirm_write(self, state: TriageState) -> dict[str, Any]:
        """The gate in front of the only node that changes anything.
        Nothing here sets confirmed. It arrives on the state from the
        caller, the way it arrives on ToolRequest in HW5. This node only
        writes down what the caller said, in the field the edge reads.
        """
        if not state["confirmed"]:
            return {
                "pending_confirmation": True,
                "write_authorized": False,
                "nodes": [
                    NodeRecord(
                        node="confirm_write", note="Not confirmed; nothing written."
                    )
                ],
            }
        return {
            "write_authorized": True,
            "nodes": [
                NodeRecord(node="confirm_write", note="Confirmed by the caller.")
            ],
        }

    def record_finding(self, state: TriageState) -> dict[str, Any]:
        """Write the finding, now that a human has approved it."""
        finding = state.get("proposed_finding")
        assert finding is not None
        # BaseTool.run refuses a write whose request is not confirmed, and
        # this is the value it refuses on. Passing True unconditionally, as
        # HW6 does, makes that refusal a formality: a flow asserting its own
        # approval is not a second barrier. Reading what the gate concluded
        # arms it - a graph rewired around confirm_write is then stopped by
        # the tool, which is what HW6 claimed two independent refusals meant.
        request = ToolRequest(
            tool_name="record_security_finding",
            arguments=finding.model_dump(),
            confirmed=state.get("write_authorized") is True,
            proposed_by="langgraph_flow",
        )
        observation = self.registry.run(request)

        if observation.success:
            stored = FindingRecord.model_validate(observation.data)
            return {
                "recorded_finding": stored,
                "nodes": [
                    NodeRecord(
                        node="record_finding",
                        note=f"Stored as {stored.finding_id}.",
                        request=request,
                        observation=observation,
                    )
                ],
            }
        return {
            "halt_reason": observation.error_message,
            "nodes": [
                NodeRecord(
                    node="record_finding",
                    note="The write was refused.",
                    request=request,
                    observation=observation,
                )
            ],
        }

    def answer_from_documents(self, state: TriageState) -> dict[str, Any]:
        """Answer from the indexed corpus. This is the HW4 pipeline."""
        guidance = self.retrieval.answer(state["user_goal"])
        return {
            "guidance": guidance,
            "nodes": [
                NodeRecord(
                    node="answer_from_documents",
                    note=f"{guidance.status}, {len(guidance.citations)} citations.",
                )
            ],
        }

    def ask_for_clarification(self, state: TriageState) -> dict[str, Any]:
        """Put the missing piece back to the user. Calls nothing.
        The question itself was written by classify_request, because the
        router is what knows which piece is missing.
        """
        return {
            "nodes": [
                NodeRecord(
                    node="ask_for_clarification", note="Asked for a CVE identifier."
                )
            ]
        }

    def build_answer(self, state: TriageState) -> dict[str, Any]:
        """Compose the answer for whichever branch reached here.
        Every branch ends at this node, which is the shape a graph makes
        obvious and a plan does not: HW6 composed the answer in run(), after
        the plan, where it was easy to miss that all three routes go through
        the same three lines.
        """
        text = final_answer(as_agent_state(state))
        return {
            "final_answer": text,
            "nodes": [
                NodeRecord(
                    node="build_answer",
                    note=f"Answer for the {state.get('route')} route.",
                )
            ],
        }

    def build_graph(self) -> CompiledStateGraph:
        """Register the nodes, wire the edges, compile.
        Everything about the order of this workflow is in this one method,
        which is what agent_flow.run_triage was, and the reason that method
        has no counterpart here.
        """
        # StateT is bound to a protocol asking for __required_keys__ and
        # __optional_keys__. Every TypedDict has both at runtime, and mypy
        # accepts this line. PyCharm doesn't match a TypedDict against a
        # protocol structurally and reports an error that is not one.
        # noinspection PyTypeChecker
        graph = StateGraph(TriageState)

        graph.add_node("classify_request", self.classify_request)
        graph.add_node("lookup_cve", self.lookup_cve)
        graph.add_node("check_asset_inventory", self.check_asset_inventory)
        graph.add_node("assess_exposure", self.assess_exposure)
        graph.add_node("retrieve_guidance", self.retrieve_guidance)
        graph.add_node("identify_owner", self.identify_owner)
        graph.add_node("propose_finding", self.propose_finding)
        graph.add_node("confirm_write", self.confirm_write)
        graph.add_node("record_finding", self.record_finding)
        graph.add_node("answer_from_documents", self.answer_from_documents)
        graph.add_node("ask_for_clarification", self.ask_for_clarification)
        graph.add_node("build_answer", self.build_answer)

        graph.add_edge(START, "classify_request")

        # The three-way split HW6 did in run() with an if/elif/else.
        graph.add_conditional_edges(
            "classify_request",
            route_after_classify,
            {
                "triage": "lookup_cve",
                "guidance": "answer_from_documents",
                "clarification": "ask_for_clarification",
            },
        )

        # Both lookups fail the same way, so both read the same selector.
        graph.add_conditional_edges(
            "lookup_cve",
            halted,
            {"continue": "check_asset_inventory", "halt": "build_answer"},
        )
        graph.add_conditional_edges(
            "check_asset_inventory",
            halted,
            {"continue": "assess_exposure", "halt": "build_answer"},
        )

        # The branch the workflow exists for. retrieve_guidance is the only
        # node on this path that spends a model call, and a settled
        # assessment never reaches it.
        graph.add_conditional_edges(
            "assess_exposure",
            after_assessment,
            {"exposed": "retrieve_guidance", "settled": "build_answer"},
        )

        graph.add_edge("retrieve_guidance", "identify_owner")
        graph.add_edge("identify_owner", "propose_finding")
        graph.add_edge("propose_finding", "confirm_write")

        # The gate is the node above; this edge only reads what it concluded.
        graph.add_conditional_edges(
            "confirm_write",
            after_confirmation,
            {"confirmed": "record_finding", "blocked": "build_answer"},
        )

        graph.add_edge("record_finding", "build_answer")
        graph.add_edge("answer_from_documents", "build_answer")
        graph.add_edge("ask_for_clarification", "build_answer")
        graph.add_edge("build_answer", END)

        return graph.compile()

    def run(self, user_goal: str, confirmed: bool = False) -> TriageState:
        """Run one goal to the end and return the state it finished with."""
        return self.graph.invoke(initial_state(user_goal, confirmed))

    def run_traced(
        self, user_goal: str, confirmed: bool = False
    ) -> tuple[TriageState, list[list[str]]]:
        """Run one goal, and report what each node wrote as well as the state.

        invoke() returns the state a run finished with and says nothing about
        which node put what there. Streaming both modes at once does:
        "updates" carries one node's return value, "values" the whole state
        after it. Asking for them together keeps this to a single run - a
        second stream would execute every node again, including the one that
        writes.

        The second return value lines up with state["nodes"], one entry per
        executed node, each listing the state keys that node wrote. 'nodes'
        is left out of them, because every node writes it.
        """
        final: TriageState | None = None
        written: list[list[str]] = []
        for mode, chunk in self.graph.stream(
            initial_state(user_goal, confirmed), stream_mode=["updates", "values"]
        ):
            if mode == "values":
                final = chunk
                continue
            for update in chunk.values():
                written.append(sorted(key for key in update if key != "nodes"))
        assert final is not None
        return final, written


# -- edges -----------------------------------------------------------------
# The selectors below are pure: each reads the state the node above returned
# and names a key in that edge's map. None of them decides anything - the
# node already decided, and this reads the decision back. `halted` is wired
# to two edges because both lookups fail the same way.


def route_after_classify(
    state: TriageState,
) -> Literal["triage", "guidance", "clarification"]:
    """Send the goal to the branch the router named."""
    route = state.get("route")
    assert route is not None
    return route


def halted(state: TriageState) -> Literal["continue", "halt"]:
    """Stop when the node above could not get what the next one needs."""
    return "halt" if state.get("halt_reason") else "continue"


def after_assessment(state: TriageState) -> Literal["exposed", "settled"]:
    """Carry on only for a service the fix has not reached.
    not_affected and patched are answers, not failures, which is why this
    returns `settled` for both rather than reusing `halt`.
    """
    return "exposed" if state.get("exposure") == "exposed" else "settled"


def after_confirmation(state: TriageState) -> Literal["confirmed", "blocked"]:
    """Take the write only on an explicit yes from the gate above.
    `is True` and not a truth test: None means the gate never ran, and a run
    that skipped its gate must not be read as an approved one.
    """
    return "confirmed" if state.get("write_authorized") is True else "blocked"
