"""Unit tests for the router that asks the model which tool to call."""

from __future__ import annotations

from typing import Any

from genai_security_assistant.models.orchestration import ToolChoice
from genai_security_assistant.models.tools import (
    CveLookupInput,
    CveRecord,
    ToolObservation,
    ToolRequest,
    ToolSpec,
)
from genai_security_assistant.orchestration.llm_router import (
    ROUTER_SYSTEM,
    LlmRouter,
)
from genai_security_assistant.tools.registry import ToolRegistry

QUESTION = "What is the status of CVE-2025-68664?"


class StubTool:
    """Registered so the registry has a schema to render."""

    def __init__(self, name: str = "lookup_cve") -> None:
        self.spec = ToolSpec(
            name=name,
            tool_type="read",
            purpose="Return something.",
            source="test",
            when_to_use=["the question names a thing"],
            when_not_to_use=["the question is general"],
            input_model=CveLookupInput,
            output_model=CveRecord,
        )

    def run(self, request: ToolRequest) -> ToolObservation:
        return ToolObservation.ok(self.spec.name, {})


class ChoosingModel:
    """Answers with a fixed choice, and remembers what it was shown."""

    model = "test-model"

    def __init__(self, choice: ToolChoice) -> None:
        self.choice = choice
        self.calls: list[tuple[str, str, list[dict[str, Any]]]] = []

    def choose(
        self, system: str, question: str, tools: list[dict[str, Any]]
    ) -> ToolChoice:
        self.calls.append((system, question, tools))
        return self.choice


def build(choice: ToolChoice, tools: list[Any] | None = None) -> LlmRouter:
    return LlmRouter(
        chooser=ChoosingModel(choice),
        registry=ToolRegistry(tools or [StubTool()]),
    )


# --- what the model is asked ---------------------------------------------


def test_the_model_is_shown_the_schemas_the_registry_renders():
    """Nothing is offered that the tool layer would not also accept."""
    model = ChoosingModel(ToolChoice())
    LlmRouter(model, ToolRegistry([StubTool("alpha"), StubTool("beta")])).route(
        QUESTION
    )

    _, _, tools = model.calls[0]
    assert [tool["function"]["name"] for tool in tools] == ["alpha", "beta"]


def test_the_model_is_told_when_not_to_call_anything():
    model = ChoosingModel(ToolChoice())
    LlmRouter(model, ToolRegistry([StubTool()])).route(QUESTION)

    system, question, _ = model.calls[0]
    assert system == ROUTER_SYSTEM
    assert question == QUESTION


# --- what comes back ------------------------------------------------------


def test_a_proposal_becomes_a_tool_route():
    decision = build(
        ToolChoice(
            tool_name="lookup_cve",
            arguments={"cve_id": "CVE-2025-68664"},
            raw_arguments='{"cve_id": "CVE-2025-68664"}',
        )
    ).route(QUESTION)

    assert decision.route == "tool"
    assert decision.tool_request is not None
    assert decision.tool_request.tool_name == "lookup_cve"
    assert decision.tool_request.arguments == {"cve_id": "CVE-2025-68664"}


def test_no_proposal_means_the_indexed_documents():
    decision = build(ToolChoice()).route("How do I prevent prompt injection?")

    assert decision.route == "retrieval"
    assert decision.tool_request is None


def test_the_proposal_is_never_pre_confirmed():
    """A model approving its own write is the thing this layer prevents."""
    decision = build(
        ToolChoice(tool_name="record_security_finding", arguments={"title": "x"})
    ).route(QUESTION)

    assert decision.tool_request is not None
    assert decision.tool_request.confirmed is False


def test_the_request_says_the_model_proposed_it():
    """The report distinguishes a tool the model chose from one a regex did."""
    decision = build(
        ToolChoice(tool_name="lookup_cve", arguments={"cve_id": "CVE-2025-68664"})
    ).route(QUESTION)

    assert decision.decided_by == "llm_router"
    assert decision.tool_request is not None
    assert decision.tool_request.proposed_by == "llm_router"


def test_a_tool_the_registry_does_not_know_is_passed_through():
    """Dispatch reports an invented name; hiding it here would lose that."""
    decision = build(ToolChoice(tool_name="drop_tables", arguments={})).route(
        QUESTION
    )

    assert decision.route == "tool"
    assert decision.tool_request is not None
    assert decision.tool_request.tool_name == "drop_tables"


# --- arguments that cannot be read ---------------------------------------


def test_arguments_that_are_not_json_send_the_question_to_retrieval():
    """The SDK warns the model does not always write valid JSON."""
    decision = build(
        ToolChoice(
            tool_name="lookup_cve",
            raw_arguments='{"cve_id": ',
            unreadable=True,
        )
    ).route(QUESTION)

    assert decision.route == "retrieval"
    assert decision.tool_request is None


def test_unreadable_arguments_are_reported_rather_than_swallowed():
    decision = build(
        ToolChoice(tool_name="lookup_cve", raw_arguments="{", unreadable=True)
    ).route(QUESTION)

    assert "lookup_cve" in decision.reason
    assert "not valid JSON" in decision.reason
