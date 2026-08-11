"""Deterministic routing between tool execution and document retrieval.

The rule-based router classifies a question with regular expressions and
needs neither model access nor a network connection, which is what lets
the evaluation reports be regenerated offline.

Routing is decision-only. The router selects a proposed execution path but
never executes a tool and never confirms a state-changing operation. The
registry validates and dispatches the call, and a write waits for explicit
human confirmation.
"""

from __future__ import annotations

import re
from typing import Protocol

from genai_security_assistant.models.orchestration import RouteDecision
from genai_security_assistant.models.tools import ToolRequest


class Router(Protocol):
    """What the pipeline needs from a router."""

    name: str

    def route(self, question: str) -> RouteDecision:
        """Decide where one question goes. Never executes anything."""
        ...


# Matches the identifier as it appears in a sentence, punctuation and all.
# The four-digit year and the four-or-more-digit number are what keep an
# ordinary phrase from being read as an id.
CVE_IN_TEXT = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)


class RuleRouter:
    """Route by what the question literally says."""

    name = "rule_router"


    def route(self, question: str) -> RouteDecision:
        """Decide where one question goes. Never executes anything."""
        match = CVE_IN_TEXT.search(question)
        if match is None:
            return RouteDecision(
                route="retrieval",
                reason="The question names no CVE identifier.",
                decided_by=self.name,
            )

        # Upper-cased here rather than loosened in CveLookupInput: the tool
        # accepts one spelling, and normalizing is the router's job.
        cve_id = match.group(0).upper()
        return RouteDecision(
            route="tool",
            reason=f"The question names {cve_id}, which the corpus cannot hold.",
            decided_by=self.name,
            tool_request=ToolRequest(
                tool_name="lookup_cve",
                arguments={"cve_id": cve_id},
                proposed_by=self.name,
            ),
        )
