"""Unit tests for the labels one executed run is read into."""

from __future__ import annotations

from typing import Any, get_args

from genai_security_assistant.evaluation.harness import MeasuredRun, cache_flag
from genai_security_assistant.evaluation.labels import (
    detect_errors,
    groundedness_of,
    reached_network,
    route_or_mode,
)
from genai_security_assistant.models.evaluation import (
    DETECTED_ERRORS,
    JUDGED_ERRORS,
    EvalCase,
    EvalError,
    NodeTiming,
)
from genai_security_assistant.models.generation import (
    AnswerStatus,
    Citation,
    GroundedAnswer,
)
from genai_security_assistant.models.graph import (
    NodeName,
    NodeRecord,
    TriageState,
    initial_state,
)
from genai_security_assistant.models.tools import ToolObservation, ToolRequest


def citation(chunk_id: str = "chunk_001") -> Citation:
    return Citation(
        chunk_id=chunk_id,
        document_id="owasp_llm06_excessive_agency",
        source_file="data/raw/owasp_llm06_excessive_agency.html",
        section="LLM06:2025 Excessive Agency",
        rank=1,
        score=0.74,
    )


def answer(
    status: AnswerStatus = "answered",
    citations: list[Citation] | None = None,
    unsupported: list[str] | None = None,
    from_cache: bool = True,
) -> GroundedAnswer:
    return GroundedAnswer(
        question="What is excessive agency?",
        answer_text="An answer.",
        status=status,
        prompt_version="v3",
        model="gpt-4.1-mini",
        citations=[citation()] if citations is None else citations,
        unsupported_citations=unsupported or [],
        from_cache=from_cache,
    )


def state(**fields: Any) -> TriageState:
    """A fully seeded state with only the fields a test cares about set."""
    seeded = initial_state("Does CVE-2025-68664 affect us?")
    seeded.update(fields)
    return seeded


def case(**fields: Any) -> EvalCase:
    defaults: dict[str, Any] = {
        "id": "e01_case",
        "question": "What is excessive agency?",
        "kind": "kb_simple",
        "expected_route": "guidance",
        "expected_mode": "RAG",
        "expected_behavior": "Answer from the knowledge base.",
    }
    return EvalCase.model_validate({**defaults, **fields})


def record(node: NodeName, observation: ToolObservation | None = None) -> NodeRecord:
    return NodeRecord(node=node, note="", observation=observation)


def timing(node: NodeName, from_cache: bool | None) -> NodeTiming:
    return NodeTiming(
        run_mode="cached",
        case_id="e01_case",
        sequence=1,
        node=node,
        duration_ms=1.0,
        from_cache=from_cache,
    )


def run(*rows: NodeTiming) -> MeasuredRun:
    return MeasuredRun(state=state(), nodes=list(rows), latency_ms=1)


# --- route_or_mode --------------------------------------------------------


def test_clarification_is_its_own_mode():
    assert route_or_mode(state(route="clarification")) == "clarification"


def test_triage_that_ran_to_the_end_is_a_tool_run():
    assert route_or_mode(state(route="triage")) == "tool"


def test_triage_that_halted_is_a_fallback():
    """Why the two columns exist: the route stays triage either way."""
    halted = state(route="triage", halt_reason="NVD holds no record.")
    assert route_or_mode(halted) == "fallback"


def test_guidance_that_answered_is_a_rag_run():
    assert route_or_mode(state(route="guidance", guidance=answer())) == "RAG"


def test_guidance_that_refused_is_a_fallback():
    refused = state(route="guidance", guidance=answer(status="abstained_by_gate"))
    assert route_or_mode(refused) == "fallback"


# --- groundedness ---------------------------------------------------------


def test_a_run_with_no_answerer_is_not_scored():
    assert groundedness_of(None) == "not_applicable"


def test_a_refusal_is_not_scored():
    """A refusal makes no claim, so there is nothing for a context to hold up."""
    assert groundedness_of(answer(status="abstained_by_model")) == "not_applicable"


def test_citations_that_all_resolve_are_good():
    assert groundedness_of(answer()) == "good"


def test_one_invented_citation_makes_it_partial():
    assert groundedness_of(answer(unsupported=["chunk_999"])) == "partial"


def test_an_answer_with_no_citation_at_all_is_bad():
    assert groundedness_of(answer(citations=[])) == "bad"


# --- detected errors ------------------------------------------------------


def test_a_clean_run_detects_nothing():
    clean = state(route="guidance", guidance=answer())
    assert detect_errors(case(), clean, "RAG") == []


def test_the_wrong_branch_is_detected():
    assert "wrong_route" in detect_errors(case(), state(route="triage"), "tool")


def test_the_wrong_mode_is_detected():
    refused = state(route="guidance", guidance=answer(status="abstained_by_gate"))
    assert "wrong_mode" in detect_errors(case(), refused, "fallback")


def test_a_failed_call_is_detected():
    failed = state(
        route="guidance",
        guidance=answer(),
        nodes=[
            NodeRecord(
                node="lookup_cve",
                note="No record to triage.",
                request=ToolRequest(tool_name="lookup_cve"),
                observation=ToolObservation.fail(
                    "lookup_cve", "not_found", "NVD holds no record."
                ),
            )
        ],
    )
    assert "tool_error" in detect_errors(case(), failed, "RAG")


def test_the_error_types_split_in_two_and_do_not_overlap():
    """A new error type cannot be added without deciding who detects it."""
    assert set(DETECTED_ERRORS) | set(JUDGED_ERRORS) == set(get_args(EvalError))
    assert not set(DETECTED_ERRORS) & set(JUDGED_ERRORS)
    assert "none" not in get_args(EvalError)


# --- cache flags ----------------------------------------------------------


def test_a_node_that_called_nothing_has_no_flag():
    assert cache_flag(record("assess_exposure"), state()) is None


def test_a_tool_call_carries_the_flag_from_its_observation():
    replayed = ToolObservation.ok("lookup_cve", {}, from_cache=True)
    assert cache_flag(record("lookup_cve", replayed), state()) is True


def test_an_answering_node_reads_the_flag_off_the_answer():
    replayed = state(guidance=answer(from_cache=True))
    assert cache_flag(record("answer_from_documents"), replayed) is True


def test_an_answer_stopped_by_the_gate_made_no_call():
    """RAGAnswerer returns before the model and leaves from_cache False.
    Reading that False as a miss reports a request that never went out,
    which is what the replay rate said before this case existed.
    """
    gated = state(guidance=answer(status="abstained_by_gate", from_cache=False))
    assert cache_flag(record("answer_from_documents"), gated) is None


def test_a_local_tool_is_not_a_cache_miss():
    """Three of the four tools read a file and have no cache to hit."""
    assert reached_network(run(timing("check_asset_inventory", False))) is False


def test_a_cacheable_call_that_was_not_replayed_counts():
    assert reached_network(run(timing("lookup_cve", False))) is True


def test_a_fully_replayed_run_reached_nothing():
    assert reached_network(run(timing("lookup_cve", True))) is False

