"""Unit tests for the write tool and its confirmation gate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from genai_security_assistant.models.tools import ToolRequest
from genai_security_assistant.tools.findings import (
    FindingsLog,
    RecordFindingTool,
    finding_id,
)

FINDING = {
    "title": "LangChain deserialization flaw affects our agent",
    "severity": "high",
    "related_cve_id": "CVE-2025-68664",
    "summary": "The agent loads serialized prompts from user input.",
}


def make_tool(tmp_path: Path) -> RecordFindingTool:
    return RecordFindingTool(log=FindingsLog(tmp_path / "findings.jsonl"))


def write(
    tool: RecordFindingTool,
    confirmed: bool = True,
    proposed_by: str = "cli",
    **overrides: Any,
):
    """Propose a write the way the orchestration layer will."""
    return tool.run(
        ToolRequest(
            tool_name="record_security_finding",
            arguments={**FINDING, **overrides},
            confirmed=confirmed,
            proposed_by=proposed_by,
        )
    )


def lines(tmp_path: Path) -> list[str]:
    path = tmp_path / "findings.jsonl"
    if not path.exists():
        return []
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- the confirmation gate ------------------------------------------------


def test_an_unconfirmed_write_is_refused(tmp_path: Path):
    observation = write(make_tool(tmp_path), confirmed=False)

    assert not observation.success
    assert observation.error_code == "not_confirmed"


def test_an_unconfirmed_write_leaves_the_log_untouched(tmp_path: Path):
    """The claim that matters: a refusal is not a partial write."""
    write(make_tool(tmp_path), confirmed=False)

    assert lines(tmp_path) == []


def test_a_perfect_payload_does_not_buy_a_write(tmp_path: Path):
    """Confirmation is checked before the arguments, not after."""
    observation = write(make_tool(tmp_path), confirmed=False)

    assert observation.error_code == "not_confirmed"


# --- validation -----------------------------------------------------------


def test_a_short_title_is_refused(tmp_path: Path):
    observation = write(make_tool(tmp_path), title="bug")

    assert observation.error_code == "validation_error"
    assert lines(tmp_path) == []


def test_a_severity_outside_the_vocabulary_is_refused(tmp_path: Path):
    observation = write(make_tool(tmp_path), severity="catastrophic")

    assert observation.error_code == "validation_error"


def test_a_malformed_cve_reference_is_refused(tmp_path: Path):
    """The same pattern as the read tool, so a bad id has no back door."""
    observation = write(make_tool(tmp_path), related_cve_id="CVE-23-1")

    assert observation.error_code == "validation_error"


def test_an_argument_the_tool_does_not_declare_is_refused(tmp_path: Path):
    observation = write(make_tool(tmp_path), path="../../etc/passwd")

    assert observation.error_code == "validation_error"


# --- what a confirmed write does -----------------------------------------


def test_a_confirmed_write_appends_one_line(tmp_path: Path):
    observation = write(make_tool(tmp_path))

    assert observation.success
    assert observation.data["created"] is True
    assert len(lines(tmp_path)) == 1


def test_the_record_says_who_proposed_it(tmp_path: Path):
    observation = write(make_tool(tmp_path), proposed_by="llm_router")

    assert observation.data["proposed_by"] == "llm_router"
    assert observation.data["confirmed"] is True


def test_the_same_finding_is_stored_once(tmp_path: Path):
    """A retry after a timeout must not leave two copies behind."""
    tool = make_tool(tmp_path)
    first = write(tool)
    second = write(tool)

    assert len(lines(tmp_path)) == 1
    assert second.data["created"] is False
    assert second.data["finding_id"] == first.data["finding_id"]


def test_a_repeat_returns_the_original_timestamp(tmp_path: Path):
    """This is what keeps a regenerated report identical to the committed one."""
    tool = make_tool(tmp_path)
    first = write(tool)
    second = write(tool)

    assert second.data["recorded_at"] == first.data["recorded_at"]


def test_a_different_summary_is_a_different_finding(tmp_path: Path):
    tool = make_tool(tmp_path)
    write(tool)
    second = write(tool, summary="Something else entirely happened here.")

    assert len(lines(tmp_path)) == 2
    assert second.data["created"] is True


def test_the_identifier_ignores_the_order_of_the_arguments():
    """Derived from what the finding says, so key order cannot change it."""
    from genai_security_assistant.models.tools import SecurityFindingInput

    forward = SecurityFindingInput(**FINDING)
    backward = SecurityFindingInput(**dict(reversed(list(FINDING.items()))))

    assert finding_id(forward) == finding_id(backward)
