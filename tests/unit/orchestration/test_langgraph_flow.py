"""The graph, against the workflow it was ported from.

Every test here runs both implementations and compares them, which is the
one thing neither file can assert about itself. What the two share - the
router, the triage rules, the tools, the answer composer - is already
covered by test_agent_flow.py and test_triage_rules.py, so nothing below
tests any of it a second time.

FakeRetrieval is copied from test_agent_flow.py rather than shared through
a conftest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genai_security_assistant.config import Settings
from genai_security_assistant.models.generation import AnswerStatus, GroundedAnswer
from genai_security_assistant.models.graph import executed_nodes, initial_state
from genai_security_assistant.orchestration.agent_flow import ControlledAgentFlow
from genai_security_assistant.orchestration.agent_router import AgentRouter
from genai_security_assistant.orchestration.langgraph_flow import (
    LangGraphTriageFlow,
    after_confirmation,
)
from genai_security_assistant.tools.asset_inventory import build_asset_inventory_tools
from genai_security_assistant.tools.cve_lookup import build_cve_lookup_tool
from genai_security_assistant.tools.findings import FindingsLog, RecordFindingTool
from genai_security_assistant.tools.registry import ToolRegistry

EXPOSED = "Does CVE-2025-68664 affect us?"
PATCHED = "Does CVE-2025-67644 affect us?"
NOT_AFFECTED = "Does CVE-2024-5565 affect us?"
NO_RECORD = "Does CVE-2023-99999 affect us?"
GUIDANCE = "How do I prevent prompt injection?"
CLARIFICATION = "Are we affected by that LangChain bug?"

# Every outcome the workflow can reach. Comparing two implementations on
# one goal proves little: a port that only matched on the exposed path
# would pass one of these seven and fail the rest.
EVERY_PATH = [
    pytest.param(EXPOSED, True, id="exposed-confirmed"),
    pytest.param(EXPOSED, False, id="exposed-unconfirmed"),
    pytest.param(PATCHED, False, id="patched"),
    pytest.param(NOT_AFFECTED, False, id="not-affected"),
    pytest.param(NO_RECORD, False, id="no-record"),
    pytest.param(GUIDANCE, False, id="guidance"),
    pytest.param(CLARIFICATION, False, id="clarification"),
]


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


def build_both(
    log_path: Path,
) -> tuple[ControlledAgentFlow, LangGraphTriageFlow]:
    """One imperative flow and one graph, wired identically.

    The same router, the same tools and the same retrieval object, so a
    difference in what they answer can only have come from the
    orchestration - which is the only thing that differs between them.
    """
    settings = Settings()
    retrieval = FakeRetrieval()

    def registry() -> ToolRegistry:
        # One registry each, both writing to the same file. A tool holds a
        # handle to that file and is not written to be shared by two
        # callers; the file is what the two runs are meant to share.
        return ToolRegistry(
            [
                build_cve_lookup_tool(settings),
                RecordFindingTool(log=FindingsLog(log_path)),
                *build_asset_inventory_tools(settings),
            ]
        )

    return (
        ControlledAgentFlow(
            router=AgentRouter(), registry=registry(), retrieval=retrieval
        ),
        LangGraphTriageFlow(
            router=AgentRouter(), registry=registry(), retrieval=retrieval
        ),
    )


# --- the two implementations, compared ------------------------------------


@pytest.mark.parametrize("goal,confirmed", EVERY_PATH)
def test_both_implementations_answer_one_goal_identically(goal, confirmed, tmp_path):
    imperative, graph = build_both(tmp_path / "findings.jsonl")

    before = imperative.run(goal, confirmed=confirmed)
    after = graph.run(goal, confirmed=confirmed)

    assert after["route"] == before.route
    assert after["exposure"] == before.exposure
    assert after["final_answer"] == before.final_answer


@pytest.mark.parametrize("goal,confirmed", EVERY_PATH)
def test_the_graph_runs_the_same_steps_with_two_added_around_them(
    goal, confirmed, tmp_path
):
    """The whole port, in one assertion.

    HW6 routed before its plan started and composed the answer after it
    ended, so neither showed up in completed_steps. A graph has no outside,
    and both became nodes. Everything between them is the HW6 trace, in the
    HW6 order.
    """
    imperative, graph = build_both(tmp_path / "findings.jsonl")

    before = imperative.run(goal, confirmed=confirmed)
    after = graph.run(goal, confirmed=confirmed)

    assert executed_nodes(after) == [
        "classify_request",
        *before.completed_steps,
        "build_answer",
    ]


def test_the_same_finding_is_written_once_whichever_ran_first(tmp_path):
    """A finding id is a hash of the finding, not of what proposed it.

    Both runs confirm a write of the same finding. The second gets the id
    the first stored and appends nothing, which is why running the HW7
    report over a repository that already ran the HW6 one leaves
    data/findings.jsonl alone.
    """
    log = tmp_path / "findings.jsonl"
    imperative, graph = build_both(log)

    before = imperative.run(EXPOSED, confirmed=True)
    after = graph.run(EXPOSED, confirmed=True)

    assert before.recorded_finding is not None
    assert after["recorded_finding"].finding_id == before.recorded_finding.finding_id
    assert log.read_text(encoding="utf-8").count("\n") == 1


# --- the write gate -------------------------------------------------------


def test_the_write_edge_refuses_a_state_its_gate_never_wrote_to():
    """The failure that gave confirm_write's conclusion a field of its own.

    write_authorized is None on a state no gate has touched, and None is
    not approval. An edge reading pending_confirmation instead would answer
    "confirmed" here, because False is that field's default - so a graph
    with its gate removed would have written anyway.
    """
    assert after_confirmation(initial_state(EXPOSED, confirmed=True)) == "blocked"


def test_an_unconfirmed_run_stops_at_the_gate_and_writes_nothing(tmp_path):
    log = tmp_path / "findings.jsonl"
    _, graph = build_both(log)

    state = graph.run(EXPOSED, confirmed=False)

    assert executed_nodes(state)[-2:] == ["confirm_write", "build_answer"]
    assert state["pending_confirmation"] is True
    assert state["write_authorized"] is False
    assert state["recorded_finding"] is None
    assert not log.exists()


# --- what the state carries -----------------------------------------------


def test_a_run_that_stops_early_still_comes_back_with_every_field(tmp_path):
    """What initial_state is for: a halted run has holes, not missing keys."""
    _, graph = build_both(tmp_path / "findings.jsonl")

    state = graph.run(NO_RECORD)

    assert set(state) == set(initial_state("any goal"))
    assert state["halt_reason"] is not None
    assert state["exposure"] is None


def test_a_node_that_calls_nothing_still_leaves_a_record(tmp_path):
    """Without it the trace would jump from a lookup to a conclusion."""
    _, graph = build_both(tmp_path / "findings.jsonl")

    state = graph.run(NOT_AFFECTED)

    assessment = [row for row in state["nodes"] if row.node == "assess_exposure"][0]

    assert assessment.request is None
    assert assessment.observation is None
    assert assessment.note
