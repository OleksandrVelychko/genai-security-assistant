"""The state one graph run carries, and the names of the nodes that fill it.

models/agent.py declares the same run as a Pydantic model that eight steps
mutate in place. A graph run works the other way round: a node is handed the
state, returns only the keys it wrote, and the framework merges them. That
difference is why this file exists instead of reusing AgentState.

    AgentState (HW6)              TriageState (HW7)
    one object, mutated           one dict, merged from partial updates
    add_step() appends by hand    a reducer concatenates
    plan is a list of names       the plan is the graph

Nothing below the orchestration layer moved. CveRecord, ServiceExposure,
GroundedAnswer and the rest arrive exactly as HW5 and HW6 defined them and
travel as values inside the dict.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel

from genai_security_assistant.models.agent import AgentRoute, ExposureLevel
from genai_security_assistant.models.generation import GroundedAnswer
from genai_security_assistant.models.tools import (
    CveRecord,
    FindingRecord,
    SecurityFindingInput,
    ServiceExposure,
    ServiceOwner,
    ToolObservation,
    ToolRequest,
)

# Every node this graph can run. The names shared with HW6 are spelled the
# same, so a trace from either implementation lines up row for row.
# classify_request and build_answer are the two that are new: they are the
# work run() used to do around the plan rather than inside it.
NodeName = Literal[
    "classify_request",
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure",
    "retrieve_guidance",
    "identify_owner",
    "propose_finding",
    "confirm_write",
    "record_finding",
    "answer_from_documents",
    "ask_for_clarification",
    "build_answer",
]


class NodeRecord(BaseModel):
    """One executed node: what ran, and what came back.
    The same four fields as StepRecord in HW6, and deliberately not that
    class. Its 'step' is typed to the step plan, which has no name for
    routing or for composing an answer. Widening StepName instead would let
    a HW6 trace claim a node HW6 has no way to run.
    """

    node: NodeName
    note: str
    request: ToolRequest | None = None
    observation: ToolObservation | None = None


class TriageState(TypedDict, total=False):
    """Everything one graph run accumulates, and all a node ever sees.

    total=False is the contract rather than a shortcut: a node returns the
    fields it changed and no others, so every subset of this is a legal
    update. initial_state fills them all in anyway, for the reason given
    there.
    """

    # From the caller. 'confirmed' arrives here for the same reason it
    # arrives on ToolRequest in HW5: nothing inside approves its own write.
    user_goal: str
    confirmed: bool

    # Written by classify_request, before any branch is chosen. 'route' is
    # what the conditional edge under it reads; 'cve_id' goes to the two
    # lookup nodes. 'route_reason' is read by no node at all - the report
    # prints it - which is why it is a plain string: for a printed line,
    # "not decided yet" and "" say the same thing.
    route: AgentRoute | None
    route_reason: str
    cve_id: str | None

    # The one field every node writes, and so the one field with a reducer.
    # Each node returns a one-item list and operator.add concatenates it
    # onto what the earlier nodes returned.
    #
    # HW6 appended into a shared list by calling add_step, which meant a
    # step could also have replaced that list. A node here holds no
    # reference to it and can only add. What the reducer doesn't do is
    # check anything: a node that writes a misleading note produces a
    # misleading trace either way.
    #
    # The records come out in the order the nodes ran because no
    # conditional edge in this graph selects more than one target, so no
    # two nodes ever write in the same superstep. That's a property of
    # this graph, not a promise from operator.add.
    nodes: Annotated[list[NodeRecord], operator.add]

    # Written along the triage branch, except 'guidance', which the
    # guidance branch writes too - through answer_from_documents rather
    # than retrieve_guidance. The two can't both run, and nothing else
    # here has a second writer, so plain last-value merge is correct and
    # none of these needs a reducer.
    cve_record: CveRecord | None
    affected_services: list[ServiceExposure]
    exposure: ExposureLevel | None
    guidance: GroundedAnswer | None
    owner: ServiceOwner | None
    proposed_finding: SecurityFindingInput | None
    pending_confirmation: bool
    recorded_finding: FindingRecord | None

    # Written on the clarification branch and nowhere else.
    clarification_question: str | None
    # Set when a node can't carry its branch any further.
    halt_reason: str | None
    # Written once, by build_answer, after a branch has finished.
    final_answer: str | None


def initial_state(user_goal: str, confirmed: bool = False) -> TriageState:
    """Seed every key the graph can write, not only the two it's given.

    LangGraph carries a key from the moment some node writes it, so a run
    that halts early comes back without the fields it never reached. Code
    reads with .get() and doesn't care. A report does: a missing
    'exposure' and an 'exposure' of None print the same and mean different
    things - one says nothing decided it, the other says nothing reached it.
    """
    return {
        "user_goal": user_goal,
        "confirmed": confirmed,
        "route": None,
        "route_reason": "",
        "cve_id": None,
        "nodes": [],
        "cve_record": None,
        "affected_services": [],
        "exposure": None,
        "guidance": None,
        "owner": None,
        "proposed_finding": None,
        "pending_confirmation": False,
        "recorded_finding": None,
        "clarification_question": None,
        "halt_reason": None,
        "final_answer": None,
    }


def executed_nodes(state: TriageState) -> list[NodeName]:
    """The nodes that ran, in order, whether or not they succeeded."""
    return [record.node for record in state.get("nodes", [])]


def tool_calls(state: TriageState) -> list[ToolRequest]:
    """Every call this run proposed, in order."""
    return [
        record.request
        for record in state.get("nodes", [])
        if record.request is not None
    ]
