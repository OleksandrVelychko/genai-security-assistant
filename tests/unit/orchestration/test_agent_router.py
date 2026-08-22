"""Unit tests for the three-way agent router."""

from __future__ import annotations

from genai_security_assistant.orchestration.agent_router import AgentRouter


def route(user_goal: str):
    return AgentRouter().route(user_goal)


# --- triage ---------------------------------------------------------------


def test_a_goal_naming_a_cve_goes_to_triage():
    decision = route("Does CVE-2025-68664 affect us?")

    assert decision.route == "triage"
    assert decision.cve_id == "CVE-2025-68664"


def test_a_lower_case_identifier_is_normalized_for_the_tools():
    """Both triage tools accept one spelling, so the router supplies it."""
    decision = route("check cve-2025-68664 for us")

    assert decision.cve_id == "CVE-2025-68664"


def test_an_identifier_is_found_next_to_punctuation():
    decision = route("Is CVE-2025-68664, the LangChain one, our problem?")

    assert decision.cve_id == "CVE-2025-68664"


def test_an_identifier_wins_over_the_wording():
    """The phrase alone would ask for an id the goal already carries."""
    decision = route("Record a finding: we are exposed to CVE-2025-68664.")

    assert decision.route == "triage"


# --- clarification --------------------------------------------------------


def test_a_goal_about_us_with_no_identifier_asks_for_one():
    decision = route("Are we affected by that LangChain deserialization bug?")

    assert decision.route == "clarification"
    assert decision.question is not None
    assert decision.cve_id is None


def test_a_write_request_with_nothing_to_write_about_asks_for_one():
    decision = route("Record a finding about our chat gateway.")

    assert decision.route == "clarification"


# --- guidance -------------------------------------------------------------


def test_a_class_of_risk_goes_to_the_documents():
    decision = route("How do I prevent prompt injection?")

    assert decision.route == "guidance"
    assert decision.cve_id is None
    assert decision.question is None


def test_the_first_person_plural_alone_is_not_a_question_about_us():
    """"do we" on its own would send a guidance question to clarification."""
    decision = route("How do we prevent prompt injection?")

    assert decision.route == "guidance"


def test_an_off_topic_goal_still_goes_to_the_documents():
    """The HW4 score gate refuses it there; the router has no opinion."""
    decision = route("How do I make sourdough bread?")

    assert decision.route == "guidance"


# --- what a decision carries ---------------------------------------------


def test_every_decision_says_who_made_it_and_why():
    for goal in ("CVE-2025-68664", "are we exposed", "what is LLM01"):
        decision = route(goal)

        assert decision.decided_by == "agent_router"
        assert decision.reason
