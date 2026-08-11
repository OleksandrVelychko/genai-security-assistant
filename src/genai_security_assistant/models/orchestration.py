"""Data contracts for the orchestration layer (HW5).

Declared here, filled in by the orchestration package, the same way the
other model modules work. The layer sits above retrieval rather than
inside it: on the tool route the indexed documents are not consulted.

Two contracts:
  RouteDecision   - the execution path chosen, and the grounds for it
  AssistantAnswer - the response returned, whichever path produced it
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from genai_security_assistant.models.generation import GroundedAnswer
from genai_security_assistant.models.tools import ToolObservation, ToolRequest

# Where a question goes. "retrieval" is the HW4 pipeline, unchanged.
Route = Literal["tool", "retrieval"]


class RouteDecision(BaseModel):
    """Which way a question was sent, and why.

    The reason is recorded rather than inferred later, because a rule and
    a model reach the same route for different grounds, and the report has
    to be able to tell them apart.
    """

    route: Route
    reason: str
    decided_by: str
    # Present only on the tool route, and always unconfirmed here: a router
    # proposes the call, it does not approve it.
    tool_request: ToolRequest | None = None


class AssistantAnswer(BaseModel):
    """What one question produced, whichever route it took.

    One shape for both routes, so a report can print them side by side.
    Exactly one of observation and grounded is filled in.
    """

    question: str
    decision: RouteDecision
    answer_text: str
    observation: ToolObservation | None = None
    grounded: GroundedAnswer | None = None

    @property
    def used_tool(self) -> bool:
        return self.decision.route == "tool"
