"""Unit tests for tool dispatch and the schemas a model is shown."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from genai_security_assistant.models.tools import (
    CveLookupInput,
    CveRecord,
    ToolObservation,
    ToolRequest,
    ToolSpec,
)
from genai_security_assistant.tools.findings import FindingsLog, RecordFindingTool
from genai_security_assistant.tools.registry import ToolRegistry, describe


class RecordingTool:
    """A tool that runs nothing and remembers being asked."""

    def __init__(self, name: str) -> None:
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
        self.requests: list[ToolRequest] = []

    def run(self, request: ToolRequest) -> ToolObservation:
        self.requests.append(request)
        return ToolObservation.ok(self.spec.name, {"called": True})


def function_named(schemas: list[dict[str, Any]], name: str) -> dict[str, Any]:
    """Pick one rendered function schema out of the list by name."""
    return next(
        schema["function"]
        for schema in schemas
        if schema["function"]["name"] == name
    )


# --- dispatch -------------------------------------------------------------


def test_a_request_reaches_the_tool_it_names():
    first, second = RecordingTool("alpha"), RecordingTool("beta")
    registry = ToolRegistry([first, second])

    registry.run(ToolRequest(tool_name="beta"))

    assert first.requests == []
    assert len(second.requests) == 1


def test_the_whole_request_is_handed_over_untouched():
    """Confirmation and provenance must survive dispatch."""
    tool = RecordingTool("alpha")
    registry = ToolRegistry([tool])

    registry.run(
        ToolRequest(
            tool_name="alpha",
            arguments={"cve_id": "CVE-2025-11111"},
            confirmed=True,
            proposed_by="llm_router",
        )
    )

    handed_over = tool.requests[0]
    assert handed_over.confirmed is True
    assert handed_over.proposed_by == "llm_router"
    assert handed_over.arguments == {"cve_id": "CVE-2025-11111"}


def test_an_unknown_tool_is_reported_rather_than_raised():
    """A model can invent a name, and the report has to be able to show it."""
    registry = ToolRegistry([RecordingTool("alpha")])

    observation = registry.run(ToolRequest(tool_name="drop_tables"))

    assert not observation.success
    assert observation.error_code == "unknown_tool"
    assert "alpha" in (observation.error_message or "")


def test_names_are_sorted_so_schemas_render_in_a_stable_order():
    registry = ToolRegistry([RecordingTool("zeta"), RecordingTool("alpha")])

    assert registry.names == ["alpha", "zeta"]


# --- what the model is shown ---------------------------------------------


def test_the_description_carries_both_halves_of_the_advice():
    """Without the negative half a model calls the tool on general questions."""
    text = describe(RecordingTool("alpha").spec)

    assert "the question names a thing" in text
    assert "the question is general" in text


def test_a_schema_is_rendered_for_every_registered_tool():
    registry = ToolRegistry([RecordingTool("alpha"), RecordingTool("zeta")])

    rendered = [schema["function"]["name"] for schema in registry.openai_tools()]

    assert rendered == ["alpha", "zeta"]


def test_the_schema_declares_the_field_the_tool_validates():
    """One ToolSpec feeds both, so the two cannot describe different tools."""
    registry = ToolRegistry([RecordingTool("alpha")])

    schema = function_named(registry.openai_tools(), "alpha")["parameters"]

    assert "cve_id" in schema["properties"]
    assert schema["required"] == ["cve_id"]


def test_every_schema_forbids_arguments_the_tool_would_reject():
    registry = ToolRegistry([RecordingTool("alpha")])

    schema = function_named(registry.openai_tools(), "alpha")["parameters"]

    assert schema["additionalProperties"] is False


def test_the_schema_offers_no_way_to_confirm_a_write():
    """Confirmation lives on the request, so no tool can be shown it."""
    registry = ToolRegistry([RecordFindingTool(FindingsLog(Path("unused.jsonl")))])

    schema = function_named(registry.openai_tools(), "record_security_finding")

    assert "confirmed" not in schema["parameters"]["properties"]
