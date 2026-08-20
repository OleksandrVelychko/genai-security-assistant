"""One goal, routed and then run step by step (HW6).

    goal
    -> route                 three workflows, chosen by rule
    -> triage                lookup -> inventory -> assess -> ... -> write
    -> or guidance           the HW4 pipeline, unchanged
    -> or clarification      a question back, and nothing else

The order of the steps lives here and the judgement lives in
triage_rules.py, so this module reads as the plan itself. Every step takes
the state, reads what earlier steps wrote and writes what later ones need.
None of them call each other.

A run stops as soon as a step can't go on: plan holds eight steps and a
run often completes three. Comparing the two is where the branching shows.
"""

from __future__ import annotations

from genai_security_assistant.config import Settings
from genai_security_assistant.generation.answering import RAGAnswerer
from genai_security_assistant.models.agent import AgentState, StepName, StepRecord
from genai_security_assistant.models.tools import (
    CveRecord,
    FindingRecord,
    ServiceExposure,
    ServiceOwner,
    ToolObservation,
    ToolRequest,
)
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

# Tuples, so a plan can't be edited through the state that copies it.
TRIAGE_PLAN: tuple[StepName, ...] = (
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure",
    "retrieve_guidance",
    "identify_owner",
    "propose_finding",
    "confirm_write",
    "record_finding",
)
GUIDANCE_PLAN: tuple[StepName, ...] = ("answer_from_documents",)
CLARIFICATION_PLAN: tuple[StepName, ...] = ("ask_for_clarification",)


def add_step(
    state: AgentState,
    step: StepName,
    note: str,
    request: ToolRequest | None = None,
    observation: ToolObservation | None = None,
) -> None:
    """Add one executed step to the trace."""
    state.steps.append(
        StepRecord(step=step, note=note, request=request, observation=observation)
    )


def severity_phrase(record: CveRecord) -> str:
    """State a score together with whoever produced it.
    A bare number is wrong here: on some records NVD and the reporting CNA
    disagree by more than a severity band, which is what HW5 turned on.
    """
    if record.cvss_score is None:
        return "no CVSS score"
    return f"CVSS {record.cvss_score} {record.cvss_severity} per {record.cvss_source}"


def exposed_lines(state: AgentState) -> list[str]:
    """The half of an answer that only an exposed run can produce."""
    lines = [f"Exposed: {exposed_summary(state.affected_services)}."]

    owner = state.owner
    if owner is not None:
        lines.append(f"Owner: {owner.team}, {owner.escalation_channel}.")

    guidance = state.guidance
    if guidance is not None and not guidance.abstained:
        lines.append(f"OWASP guidance: {guidance.answer_text}")

    finding = state.recorded_finding
    if finding is not None:
        lines.append(f"Finding recorded as {finding.finding_id}.")
    elif state.pending_confirmation:
        lines.append(
            "A finding is drafted and waiting for confirmation. "
            "Nothing has been written."
        )
    return lines


def triage_answer(state: AgentState) -> str:
    """Compose the triage answer from what the steps left behind."""
    if state.cve_record is None:
        return f"Triage stopped: {state.halt_reason}"

    record = state.cve_record
    lines = [
        f"{record.cve_id} is {record.vuln_status}, {severity_phrase(record)}, "
        f"retrieved {record.retrieved_at:%Y-%m-%d}."
    ]

    if state.halt_reason:
        lines.append(f"Triage stopped: {state.halt_reason}")
    elif state.exposure == "not_affected":
        lines.append("No deployed service runs the affected component.")
    elif state.exposure == "patched":
        lines.append("Every service running the component is already on the fix.")
    else:
        lines += exposed_lines(state)
    return "\n".join(lines)


def final_answer(state: AgentState) -> str:
    """Compose the answer for whichever route the run took."""
    if state.route == "clarification":
        return state.clarification_question or ""
    if state.route == "guidance":
        return state.guidance.answer_text if state.guidance else ""
    return triage_answer(state)


class ControlledAgentFlow:
    """Run one goal through the workflow its route names."""

    def __init__(
        self, router: AgentRouter, registry: ToolRegistry, retrieval: Answerer
    ) -> None:
        self.router = router
        self.registry = registry
        self.retrieval = retrieval

    @classmethod
    def from_settings(
        cls, settings: Settings | None = None, live: bool = False
    ) -> ControlledAgentFlow:
        """Build everything from configs/base.yaml."""
        resolved = settings or Settings()
        return cls(
            router=AgentRouter(),
            # build_agent_registry, not build_registry: two more tools would
            # change the schemas LlmRouter hashes into its cache key.
            registry=build_agent_registry(resolved, live=live),
            retrieval=RAGAnswerer.from_settings(resolved, live=live),
        )

    def run(self, user_goal: str, confirmed: bool = False) -> AgentState:
        """Route one goal, run the plan its route names, then answer."""
        state = AgentState(user_goal=user_goal, confirmed=confirmed)
        decision = self.router.route(user_goal)
        state.route = decision.route
        state.route_reason = decision.reason
        state.cve_id = decision.cve_id
        state.clarification_question = decision.question

        if decision.route == "triage":
            state.plan = list(TRIAGE_PLAN)
            self.run_triage(state)
        elif decision.route == "guidance":
            state.plan = list(GUIDANCE_PLAN)
            self.answer_from_documents(state)
        else:
            state.plan = list(CLARIFICATION_PLAN)
            self.ask_for_clarification(state)

        state.final_answer = final_answer(state)
        return state

    def run_triage(self, state: AgentState) -> None:
        """Run the triage plan, stopping at the first step that cannot go on."""
        if not self.lookup_cve(state):
            return
        if not self.check_asset_inventory(state):
            return
        self.assess_exposure(state)
        if state.exposure != "exposed":
            return
        self.retrieve_guidance(state)
        self.identify_owner(state)
        self.propose_finding(state)
        if not self.confirm_write(state):
            return
        self.record_finding(state)

    def lookup_cve(self, state: AgentState) -> bool:
        """Read the CVE record. False when there is nothing to triage."""
        request = ToolRequest(
            tool_name="lookup_cve",
            arguments={"cve_id": state.cve_id},
            proposed_by=self.router.name,
        )
        observation = self.registry.run(request)

        if not observation.success:
            state.halt_reason = observation.error_message
            add_step(state, "lookup_cve", "No record to triage.", request, observation)
            return False

        record = CveRecord.model_validate(observation.data)
        state.cve_record = record
        add_step(
            state,
            "lookup_cve",
            f"{record.cve_id} is {record.vuln_status}.",
            request,
            observation,
        )
        return True

    def check_asset_inventory(self, state: AgentState) -> bool:
        """Read which deployed services this CVE reaches.
        False when the inventory did not answer. A failed call is not an
        empty one, and reading it as "nothing runs this" would report a
        safety the inventory never claimed.
        """
        request = ToolRequest(
            tool_name="check_asset_inventory",
            arguments={"cve_id": state.cve_id},
            proposed_by="agent_flow",
        )
        observation = self.registry.run(request)

        if not observation.success:
            state.halt_reason = observation.error_message
            add_step(
                state,
                "check_asset_inventory",
                "The inventory did not answer.",
                request,
                observation,
            )
            return False

        state.affected_services = [
            ServiceExposure.model_validate(row)
            for row in observation.data["services"]
        ]
        add_step(
            state,
            "check_asset_inventory",
            f"Services running the component: {len(state.affected_services)}.",
            request,
            observation,
        )
        return True

    def assess_exposure(self, state: AgentState) -> None:
        """Decide what the two lookups mean together. Calls nothing."""
        exposure = exposure_of(state.affected_services)
        state.exposure = exposure
        notes = {
            "not_affected": "Nothing deployed runs the affected component.",
            "patched": "Every affected service is already on the fix.",
            "exposed": f"{exposed_summary(state.affected_services)}.",
        }
        add_step(state, "assess_exposure", notes[exposure])

    def retrieve_guidance(self, state: AgentState) -> None:
        """Ask the corpus how this class of flaw is mitigated.
        Reached only when a service is exposed, so a patched run spends no
        model call at all.
        """
        assert state.cve_record is not None
        guidance = self.retrieval.answer(guidance_question(state.cve_record))
        state.guidance = guidance
        add_step(
            state,
            "retrieve_guidance",
            f"{guidance.status}, {len(guidance.citations)} citations.",
        )

    def identify_owner(self, state: AgentState) -> None:
        """Read who to notify. A missing owner does not stop the run."""
        exposed = exposed_services(state.affected_services)
        request = ToolRequest(
            tool_name="get_service_owner",
            # From the previous observation, never from the goal's wording.
            arguments={"service_id": exposed[0].service_id},
            proposed_by="agent_flow",
        )
        observation = self.registry.run(request)
        owner = (
            ServiceOwner.model_validate(observation.data)
            if observation.success
            else None
        )
        state.owner = owner

        note = (
            f"Notify {owner.team}."
            if owner is not None
            else "No owner recorded; the finding is still worth writing."
        )
        add_step(state, "identify_owner", note, request, observation)

    def propose_finding(self, state: AgentState) -> None:
        """Draft the finding the assessment justifies. Writes nothing."""
        assert state.cve_record is not None
        finding = build_finding(state.cve_record, state.affected_services)
        state.proposed_finding = finding
        add_step(state, "propose_finding", f"Severity {finding.severity}.")

    def confirm_write(self, state: AgentState) -> bool:
        """The gate in front of the only step that changes anything.
        Nothing here sets confirmed. It arrives on the state from the
        caller, the way it arrives on ToolRequest in HW5.
        """
        if not state.confirmed:
            state.pending_confirmation = True
            add_step(state, "confirm_write", "Not confirmed; nothing written.")
            return False
        add_step(state, "confirm_write", "Confirmed by the caller.")
        return True

    def record_finding(self, state: AgentState) -> None:
        """Write the finding, now that a human has approved it."""
        assert state.proposed_finding is not None
        request = ToolRequest(
            tool_name="record_security_finding",
            arguments=state.proposed_finding.model_dump(),
            confirmed=True,
            proposed_by="agent_flow",
        )
        observation = self.registry.run(request)

        if observation.success:
            stored = FindingRecord.model_validate(observation.data)
            state.recorded_finding = stored
            note = f"Stored as {stored.finding_id}."
        else:
            state.halt_reason = observation.error_message
            note = "The write was refused."
        add_step(state, "record_finding", note, request, observation)

    def answer_from_documents(self, state: AgentState) -> None:
        """Answer from the indexed corpus. This is the HW4 pipeline."""
        guidance = self.retrieval.answer(state.user_goal)
        state.guidance = guidance
        add_step(
            state,
            "answer_from_documents",
            f"{guidance.status}, {len(guidance.citations)} citations.",
        )

    def ask_for_clarification(self, state: AgentState) -> None:
        """Put the missing piece back to the user. Calls nothing."""
        add_step(state, "ask_for_clarification", "Asked for a CVE identifier.")
