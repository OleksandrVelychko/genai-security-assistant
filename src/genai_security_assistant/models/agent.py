"""Data contracts for the controlled agent workflow (HW6).

Declared here, filled in by the orchestration package, the same way
models/orchestration.py works. What differs is how much they carry: a
routing decision describes one action, while a run decides more than once
and every step after the first reads what the ones before it wrote down.

Two vocabularies and three contracts:
  AgentRoute, StepName - what this layer can choose, and what it can run
  AgentDecision        - the workflow one goal was sent to, and why
  StepRecord           - one executed step: what ran, and what came back
  AgentState           - everything a run accumulates, and all a step sees
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

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

# Declared separately rather than by widening models/orchestration.Route:
# that one chooses between a tool and the index, this one chooses between
# whole workflows, and outputs/tool_examples.md has to keep reproducing.
AgentRoute = Literal["triage", "guidance", "clarification"]

# Not every step calls a tool: assess_exposure and propose_finding only read
# what earlier steps left behind, which is why both request and observation
# on StepRecord are optional.
StepName = Literal[
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
]

# What assess_exposure concluded, and what the flow branches on:
#   not_affected - the inventory returned no service
#   patched      - every affected service already runs the fixed version
#   exposed      - at least one service runs a version below the fix
ExposureLevel = Literal["not_affected", "patched", "exposed"]


class AgentDecision(BaseModel):
    """Which workflow one goal gets, and the grounds for it.
    Decision-only, like RouteDecision in HW5: this reads the goal, and the
    flow that acts on it is what calls a tool.
    """

    route: AgentRoute
    reason: str
    decided_by: str
    # Set on the triage route only: the identifier the flow looks up.
    cve_id: str | None = None
    # Set on the clarification route only: what to put back to the user.
    question: str | None = None


class StepRecord(BaseModel):
    """One executed step: what ran, and what came back.
    request and observation are empty for a step that calls nothing. note
    is not: a step that only reads the state still has to say what it
    concluded, or the trace shows a gap where the decision was made.
    """

    step: StepName
    note: str
    request: ToolRequest | None = None
    observation: ToolObservation | None = None


class AgentState(BaseModel):
    """Everything one run accumulates, and the only thing steps share.
    A step reads this and writes this and touches nothing else, so the
    order they run in is the only coupling between them - which is what
    lets each become a graph node in HW7 without its body changing.
    """

    user_goal: str
    # Comes from the caller, never from a step. The same rule as
    # ToolRequest.confirmed: nothing here approves its own write.
    confirmed: bool = False

    route: AgentRoute | None = None
    route_reason: str = ""
    # The identifier the router read out of the goal, normalized. Two steps
    # need it, and re-reading the goal in each would let them disagree.
    cve_id: str | None = None
    plan: list[StepName] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)

    # Written by the triage steps, in the order those steps run.
    cve_record: CveRecord | None = None
    affected_services: list[ServiceExposure] = Field(default_factory=list)
    exposure: ExposureLevel | None = None
    guidance: GroundedAnswer | None = None
    owner: ServiceOwner | None = None
    proposed_finding: SecurityFindingInput | None = None
    # Set when a write was prepared and the caller did not confirm it.
    pending_confirmation: bool = False
    recorded_finding: FindingRecord | None = None

    clarification_question: str | None = None
    # Set when a run ends before the end of its plan. The final answer says
    # the same thing in prose; this is the field a test asserts on.
    halt_reason: str | None = None
    final_answer: str | None = None

    @computed_field
    @property
    def completed_steps(self) -> list[StepName]:
        """The steps that ran, in order, whether or not they succeeded."""
        return [record.step for record in self.steps]

    @computed_field
    @property
    def tool_calls(self) -> list[ToolRequest]:
        """Every call this run proposed, in order."""
        return [
            record.request
            for record in self.steps
            if record.request is not None
        ]

    @computed_field
    @property
    def observations(self) -> list[ToolObservation]:
        """Every result this run saw, in order."""
        return [
            record.observation
            for record in self.steps
            if record.observation is not None
        ]
