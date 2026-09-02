"""Unit tests for the controlled agent workflow."""

from __future__ import annotations

from pathlib import Path

from genai_security_assistant.config import Settings
from genai_security_assistant.models.generation import AnswerStatus, GroundedAnswer
from genai_security_assistant.orchestration.agent_flow import ControlledAgentFlow
from genai_security_assistant.orchestration.agent_router import AgentRouter
from genai_security_assistant.tools.asset_inventory import build_asset_inventory_tools
from genai_security_assistant.tools.cve_lookup import build_cve_lookup_tool
from genai_security_assistant.tools.findings import FindingsLog, RecordFindingTool
from genai_security_assistant.tools.registry import ToolRegistry

EXPOSED = "Does CVE-2025-68664 affect us?"
PATCHED = "Does CVE-2025-67644 affect us?"
NOT_AFFECTED = "Does CVE-2024-5565 affect us?"
NO_RECORD = "Does CVE-2023-99999 affect us?"


class FakeRetrieval:
    """A retrieval layer that answers without a model or a key."""

    def __init__(self, status: AnswerStatus = "answered") -> None:
        self.status: AnswerStatus = status
        self.questions: list[str] = []

    def answer(self, question: str) -> GroundedAnswer:
        self.questions.append(question)
        return GroundedAnswer(
            question=question,
            answer_text="Limit what the extension may do.",
            status=self.status,
            prompt_version="v3",
            model="fake",
        )


def build_flow(log_path: Path, retrieval: FakeRetrieval | None = None):
    """A flow whose write tool points somewhere the tests may write."""
    settings = Settings()
    registry = ToolRegistry(
        [
            build_cve_lookup_tool(settings),
            RecordFindingTool(log=FindingsLog(log_path)),
            *build_asset_inventory_tools(settings),
        ]
    )
    return ControlledAgentFlow(
        router=AgentRouter(),
        registry=registry,
        retrieval=retrieval or FakeRetrieval(),
    )


# --- the exposed path -----------------------------------------------------


def test_a_confirmed_exposed_run_completes_every_planned_step(tmp_path):
    log = tmp_path / "findings.jsonl"
    state = build_flow(log).run(EXPOSED, confirmed=True)

    assert state.route == "triage"
    assert state.exposure == "exposed"
    assert state.completed_steps == list(state.plan)
    assert state.recorded_finding is not None
    assert log.read_text(encoding="utf-8").count("\n") == 1


def test_an_unconfirmed_run_stops_at_the_gate_and_writes_nothing(tmp_path):
    log = tmp_path / "findings.jsonl"
    state = build_flow(log).run(EXPOSED, confirmed=False)

    assert state.completed_steps[-1] == "confirm_write"
    assert state.pending_confirmation is True
    assert state.recorded_finding is None
    assert not log.exists()


def test_the_owner_is_looked_up_by_the_id_the_inventory_returned(tmp_path):
    """The second tool's input comes from the first tool, not from the goal."""
    state = build_flow(tmp_path / "f.jsonl").run(EXPOSED, confirmed=True)

    owner_calls = [
        call for call in state.tool_calls if call.tool_name == "get_service_owner"
    ]

    assert owner_calls[0].arguments == {"service_id": "svc-chat-gateway"}


# --- the paths that stop early -------------------------------------------


def test_a_patched_run_stops_before_the_model_is_ever_called(tmp_path):
    retrieval = FakeRetrieval()
    state = build_flow(tmp_path / "f.jsonl", retrieval).run(PATCHED)

    assert state.exposure == "patched"
    assert state.completed_steps == [
        "lookup_cve",
        "check_asset_inventory",
        "assess_exposure",
    ]
    assert retrieval.questions == []


def test_a_cve_nothing_runs_ends_as_not_affected(tmp_path):
    state = build_flow(tmp_path / "f.jsonl").run(NOT_AFFECTED)

    assert state.exposure == "not_affected"
    assert state.affected_services == []
    assert state.proposed_finding is None


def test_a_missing_record_stops_after_the_first_step(tmp_path):
    state = build_flow(tmp_path / "f.jsonl").run(NO_RECORD)

    assert state.completed_steps == ["lookup_cve"]
    assert state.halt_reason is not None
    assert state.exposure is None


def test_a_plan_is_longer_than_what_a_stopped_run_completed(tmp_path):
    """Plan against completed_steps is where the branching is visible."""
    state = build_flow(tmp_path / "f.jsonl").run(PATCHED)

    assert len(state.plan) == 8
    assert len(state.completed_steps) == 3


# --- the other two routes -------------------------------------------------


def test_the_guidance_route_asks_the_corpus_the_goal_as_written(tmp_path):
    retrieval = FakeRetrieval()
    goal = "How do I prevent prompt injection?"

    state = build_flow(tmp_path / "f.jsonl", retrieval).run(goal)

    assert state.route == "guidance"
    assert retrieval.questions == [goal]
    assert state.final_answer == "Limit what the extension may do."


def test_the_clarification_route_calls_nothing_at_all(tmp_path):
    retrieval = FakeRetrieval()

    state = build_flow(tmp_path / "f.jsonl", retrieval).run("Are we affected?")

    assert state.route == "clarification"
    assert state.tool_calls == []
    assert retrieval.questions == []
    assert "CVE" in (state.final_answer or "")


# --- what the trace carries ----------------------------------------------


def test_a_decision_step_is_recorded_even_though_it_calls_nothing(tmp_path):
    """Without it the trace would jump from a lookup to a conclusion."""
    state = build_flow(tmp_path / "f.jsonl").run(NOT_AFFECTED)

    assessment = [row for row in state.steps if row.step == "assess_exposure"][0]

    assert assessment.request is None
    assert assessment.observation is None
    assert assessment.note


def test_the_derived_views_stay_in_step_with_the_trace(tmp_path):
    state = build_flow(tmp_path / "f.jsonl").run(EXPOSED, confirmed=True)

    assert len(state.tool_calls) == len(state.observations)
    assert len(state.completed_steps) == len(state.steps)
