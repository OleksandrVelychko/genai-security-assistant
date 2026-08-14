"""Unit tests for the rule-based router."""

from __future__ import annotations

from genai_security_assistant.orchestration.router import RuleRouter


def route(question: str):
    return RuleRouter().route(question)


def test_a_question_naming_a_cve_goes_to_the_tool():
    decision = route("What is the status of CVE-2025-68664?")

    assert decision.route == "tool"
    assert decision.tool_request is not None
    assert decision.tool_request.tool_name == "lookup_cve"
    assert decision.tool_request.arguments == {"cve_id": "CVE-2025-68664"}


def test_a_lower_case_identifier_is_normalized():
    """The tool accepts one spelling, so the router supplies it."""
    decision = route("tell me about cve-2025-68664")

    assert decision.tool_request is not None
    assert decision.tool_request.arguments == {"cve_id": "CVE-2025-68664"}


def test_an_identifier_is_found_next_to_punctuation():
    decision = route("Is CVE-2025-68664, the LangChain one, still open?")

    assert decision.tool_request is not None
    assert decision.tool_request.arguments == {"cve_id": "CVE-2025-68664"}


def test_a_question_with_no_identifier_goes_to_retrieval():
    decision = route("How do I prevent prompt injection?")

    assert decision.route == "retrieval"
    assert decision.tool_request is None


def test_something_shaped_like_an_identifier_is_not_one():
    """A short number is a typo, and the corpus is the better guess."""
    decision = route("What about CVE-23-1?")

    assert decision.route == "retrieval"


def test_the_proposal_is_never_pre_confirmed():
    """A router proposes; approving a write is not its to give."""
    decision = route("Log a finding about CVE-2025-68664.")

    assert decision.tool_request is not None
    assert decision.tool_request.confirmed is False


def test_the_decision_records_who_made_it():
    for question in ["CVE-2025-68664", "how do I prevent prompt injection"]:
        assert route(question).decided_by == "rule_router"


def test_the_decision_carries_its_grounds():
    """Two routers reach the same route for different reasons."""
    assert "CVE-2025-68664" in route("about CVE-2025-68664").reason
    assert "no CVE" in route("prompt injection").reason


def test_the_first_identifier_wins_when_several_appear():
    """A known limitation, fixed here so a change to it is visible."""
    decision = route("Compare CVE-2025-68664 with CVE-2026-34070.")

    assert decision.tool_request is not None
    assert decision.tool_request.arguments == {"cve_id": "CVE-2025-68664"}
