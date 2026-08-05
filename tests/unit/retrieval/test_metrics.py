"""Unit tests for the retrieval quality metrics.
Every expected value here is worked out by hand from the definition of the
metric, never copied from what the code printed. A test that repeats the
output of the code it tests will lock in a bug just as happily as it locks
in correct behaviour.

When adding a case, choose round inputs so the answer can still be derived
on paper. The scores below are the real q1, q7 and q9 figures rounded for
exactly that reason; the live ones are in outputs/retrieval_examples.md,
and the per-query grade counts come from scripts/check_labels.py.

Computed floats go through pytest.approx. 0.6 - 0.13 happens to land on
0.47 exactly while 0.59 - 0.61 misses -0.02, and there is no way to tell
which case you have without running it.
"""
from __future__ import annotations

import pytest

from genai_security_assistant.models.documents import Chunk, ChunkMetadata
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.labels import LabelRule, LabelSet, QueryLabels
from genai_security_assistant.retrieval.metrics import (
    QueryScore,
    gain,
    ndcg_at_k,
    precision_at_k,
    reciprocal_rank,
    score_query,
    score_run,
    separation_margin,
)

# A corpus shaped like q7: five chunks answer it, seven are on topic only.
# the rest are not about the question. Those counts come from
# scripts/check_labels.py, which prints them per query for the real
# knowledge base.
CORPUS_WITH_FIVE_ANSWERS = [2] * 5 + [1] * 7 + [0] * 252


def make_chunk(document_id: str, section: str, index: int = 0) -> Chunk:
    """A chunk with the fields the labels look at, and defaults elsewhere."""
    return Chunk(
        chunk_id=f"{document_id}_chunk_{index:03d}",
        text="text",
        metadata=ChunkMetadata(
            document_id=document_id,
            source_file=f"data/raw/{document_id}.html",
            source_type="html",
            source_url=f"https://example.test/{document_id}",
            title=document_id,
            section=section,
            chunk_index=index,
            language="en",
            domain="genai_security",
            document_type="security_risk",
            publisher="test",
        ),
    )


def make_result(chunk: Chunk, rank: int, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        rank=rank,
        score=score,
        chunk_id=chunk.chunk_id,
        text=chunk.text,
        metadata=chunk.metadata,
    )


def only(query: QueryLabels) -> LabelSet:
    """A label set holding one query and nothing globally irrelevant."""
    return LabelSet(queries=[query], always_irrelevant=set())


def test_only_grade_two_counts_as_a_hit():
    """The decision the binary metrics rest on: on-topic is not an answer."""
    assert precision_at_k([1, 1, 1], 3) == 0.0
    assert precision_at_k([2, 1, 1], 3) == pytest.approx(1 / 3)


def test_precision_divides_by_k_not_by_results_returned():
    assert precision_at_k([2], 5) == pytest.approx(0.2)


def test_reciprocal_rank_finds_the_first_answer():
    assert reciprocal_rank([0, 0, 2, 2]) == pytest.approx(1 / 3)


def test_reciprocal_rank_is_zero_when_no_answer_comes_back():
    assert reciprocal_rank([0, 1, 1]) == 0.0


def test_one_answer_outweighs_two_background_sections():
    """Why gain is 2**grade - 1 rather than the grade itself."""
    assert gain(2) > gain(1) + gain(1)


def test_the_best_possible_ranking_scores_one():
    assert ndcg_at_k([2, 2, 2, 2, 2], CORPUS_WITH_FIVE_ANSWERS, 5) == 1.0


def test_a_ranking_without_answers_scores_zero():
    assert ndcg_at_k([0, 0, 0, 0, 0], CORPUS_WITH_FIVE_ANSWERS, 5) == 0.0


def test_background_only_ranking_scores_a_third():
    """Five on-topic chunks earn a third of what five answers would.
    gain(1) / gain(2) is 1 / 3, and the position discounts cancel out
    because both rankings hold five results of a single grade each. So the
    number depends only on the grade weighting, which is what this checks.
    """
    assert ndcg_at_k(
        [1, 1, 1, 1, 1], CORPUS_WITH_FIVE_ANSWERS, 5
    ) == pytest.approx(1 / 3)


def test_ndcg_refuses_a_query_nothing_can_answer():
    with pytest.raises(ValueError, match="no relevant chunk"):
        ndcg_at_k([0, 0], [0] * 264, 5)


def test_an_abstain_query_is_measured_by_its_top_score_alone():
    query = QueryLabels(id="q10", query="unbounded consumption?", abstain=True)
    chunk = make_chunk("owasp_llm01", "LLM09:2025 Misinformation")

    score = score_query(query, [make_result(chunk, 1, 0.5952)], only(query), [])

    assert score.abstain
    assert score.best_score == pytest.approx(0.5952)
    assert score.mrr is None
    assert score.ndcg_at_5 is None


def test_results_are_graded_against_the_labels_of_their_own_query():
    """The answer sits at rank 2 behind a background section, and it shows."""
    answer = make_chunk("owasp_llm01", "Prevention", 1)
    background = make_chunk("owasp_llm01", "Introduction", 2)
    query = QueryLabels(
        id="q1",
        query="how do I prevent it?",
        relevant=[
            LabelRule(document_id="owasp_llm01", section="Prevention", grade=2),
            LabelRule(document_id="owasp_llm01", section="Introduction", grade=1),
        ],
    )
    results = [make_result(background, 1, 0.6), make_result(answer, 2, 0.5)]

    score = score_query(query, results, only(query), [answer, background])

    assert score.precision_at_1 == 0.0
    assert score.mrr == pytest.approx(0.5)


def test_score_query_refuses_an_empty_result_list():
    query = QueryLabels(id="q1", query="anything")
    with pytest.raises(ValueError, match="no results"):
        score_query(query, [], only(query), [])


def test_the_margin_is_negative_when_the_two_groups_overlap():
    """A negative margin is the answer, not a failure: no threshold works."""
    scores = [
        QueryScore("q7", False, 0.59, 1.0, 1.0, 1.0, 1.0, 1.0),
        QueryScore("q10", True, 0.61),
    ]
    # The query with no answer outscores the one with an answer, so the
    # gap runs the wrong way: 0.59 - 0.61.
    assert separation_margin(scores) == pytest.approx(-0.02)


def test_averages_leave_out_the_queries_that_have_no_answer():
    scores = [
        QueryScore("q1", False, 0.7, 1.0, 1.0, 1.0, 1.0, 1.0),
        QueryScore("q7", False, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0),
        QueryScore("q9", True, 0.13),
    ]

    run = score_run(scores)

    # (1.0 + 0.0) / 2 over the two answerable queries. Letting q9 in would
    # not drag the average down, it would raise TypeError: its precision
    # is None, because the figure does not exist for it.
    assert run.mean_precision_at_1 == 0.5
    assert len(run.per_query) == 3
    # Weakest answerable (0.60) minus loudest hopeless (0.13).
    assert run.separation_margin == pytest.approx(0.47)