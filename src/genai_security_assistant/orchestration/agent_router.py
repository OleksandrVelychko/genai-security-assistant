"""Deterministic routing between the three workflows (HW6).

    the goal names a CVE      -> triage        look it up, then check exposure
    the goal is about us      -> clarification nothing can answer it yet
    anything else             -> guidance      the HW4 pipeline, unchanged

No model is involved, and no network: the rules read the goal and nothing
else, which is what lets outputs/agent_flow_examples.md rebuild from a
fresh clone.

Routing is decision-only, the same as in orchestration/router.py. This
picks a workflow; the flow that runs it is what calls a tool.
"""

from __future__ import annotations

from genai_security_assistant.models.agent import AgentDecision
from genai_security_assistant.orchestration.router import CVE_IN_TEXT

# Phrases that make a goal about this deployment rather than about a class
# of risk. Deliberately narrow: a bare "do we" would catch "how do we
# prevent prompt injection", which the indexed documents answer well.
INTERNAL_PHRASES = (
    "affect us",
    "affects us",
    "affect our",
    "affects our",
    "are we affected",
    "are we exposed",
    "are we vulnerable",
    "do we run",
    "do we use",
    "our deployment",
    "our services",
    "record a finding",
    "log a finding",
    "file a finding",
)

CLARIFICATION_QUESTION = (
    "Which CVE do you mean? Checking whether something affects this "
    "organization needs an identifier, for example CVE-2025-68664."
)


def asks_about_this_organization(user_goal: str) -> bool:
    """Say whether the goal is about this deployment rather than a topic."""
    lowered = user_goal.lower()
    return any(phrase in lowered for phrase in INTERNAL_PHRASES)


class AgentRouter:
    """Send one goal to the workflow that can answer it."""

    name = "agent_router"

    def route(self, user_goal: str) -> AgentDecision:
        """Choose a workflow. Reads the goal and executes nothing."""
        match = CVE_IN_TEXT.search(user_goal)
        if match is not None:
            return AgentDecision(
                route="triage",
                reason="The goal names a CVE, so exposure can be checked.",
                decided_by=self.name,
                # Upper-cased here rather than loosened in the input models.
                # lookup_cve and check_asset_inventory both accept one
                # spelling, and HW5 already made normalizing the router's job.
                cve_id=match.group(0).upper(),
            )

        if asks_about_this_organization(user_goal):
            return AgentDecision(
                route="clarification",
                reason=(
                    "The goal asks about this deployment but names no "
                    "identifier, and the documents hold no deployment facts."
                ),
                decided_by=self.name,
                question=CLARIFICATION_QUESTION,
            )

        return AgentDecision(
            route="guidance",
            reason="The goal asks about a class of risk, which the corpus covers.",
            decided_by=self.name,
        )
