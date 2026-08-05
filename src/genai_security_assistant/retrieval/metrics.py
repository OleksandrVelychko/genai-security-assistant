"""Retrieval quality in numbers: how well a ranking answers each query.
configs/eval_queries.yaml records which chunks answer which query and how
well (2 = the answer, 1 = right topic but no answer in it, 0 = not it).
This module turns those judgements, plus a ranked list of results, into
figures that can be compared between two pipelines.

Three of the eleven test queries have no answer anywhere in the corpus.
Ranking quality is undefined for them - there is nothing that should have
been ranked first - so they are measured differently: by how confident the
pipeline sounds about a question it cannot answer. separation_margin()
below turns that into a single number.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from genai_security_assistant.models.documents import Chunk
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.labels import LabelSet, QueryLabels

# A result counts as a hit only when it is labeled 2, the actual answer.
# Grade 1 means "right topic, but no answer in it" - introductions, general
# definitions, background. Counting those as hits would let a pipeline score
# well while returning exactly the material HW3 sets out to push aside. The
# binary measures below therefore ignore them; ndcg_at_k() does not, and
# that is where the middle grade earns its place.
HIT = 2


def precision_at_k(grades: Sequence[int], k: int) -> float:
    """Share of the first k results that are the answer.
    Divided by k rather than by however many results came back, so a
    pipeline that returns three chunks when five were asked for gains
    nothing from returning less.
    """
    if k <= 0:
        raise ValueError("k must be positive.")
    return sum(1 for grade in grades[:k] if grade >= HIT) / k


def reciprocal_rank(grades: Sequence[int]) -> float:
    """One over the position of the first answer, or zero if none appears.
    Rewards getting one right chunk to the top far more than getting
    several right chunks somewhere in the list, which is what matters when
    a person reads the results from the top down and stops early.
    """
    for position, grade in enumerate(grades, start=1):
        if grade >= HIT:
            return 1.0 / position
    return 0.0


def gain(grade: int) -> float:
    """What one result is worth at its grade: 0, 1 and 3.
    The obvious alternative is to use the grade itself - 0, 1 and 2 - but
    that makes one answer worth exactly as much as two background sections.
    A pipeline could then drop the answer, put two background chunks where
    it was, and score the same. 2**grade - 1 keeps the answer ahead: 3
    against 1 + 1. It is also the usual formulation for graded nDCG, so
    these figures can be read next to published ones.
    """
    return float(2**grade - 1)


def discounted_gain(grades: Sequence[int]) -> float:
    """Total gain, with each result divided by the log of its position.
    The discount is what makes this a ranking measure rather than a set
    measure: the same chunk is worth less the further down it sits.
    """
    return sum(
        gain(grade) / math.log2(position + 1)
        for position, grade in enumerate(grades, start=1)
    )


def ndcg_at_k(grades: Sequence[int], ideal: Sequence[int], k: int) -> float:
    """This ranking's gain against the best ranking the corpus allows.
    The raw gain of a ranking grows with the number of good chunks a query
    has, so q6 with its 38 would beat q7 with its 5 whatever either
    pipeline did. Dividing by the best possible ranking for that same query
    turns the figure into a share of what was available: 1.0 means nothing
    better could have been returned, and every query ends up on one scale.
    """
    best = discounted_gain(sorted(ideal, reverse=True)[:k])
    if best == 0:
        raise ValueError("no relevant chunk exists for this query")
    return discounted_gain(grades[:k]) / best


def ideal_grades(
    labels: LabelSet,
    query: QueryLabels,
    chunks: Sequence[Chunk],
) -> list[int]:
    """Every grade this query could award, best first: the ceiling for nDCG."""
    return sorted(
        (labels.grade_of(chunk.metadata, query) for chunk in chunks),
        reverse=True,
    )


@dataclass(frozen=True)
class QueryScore:
    """Every figure for one query. None where a figure has no meaning."""

    query_id: str
    abstain: bool
    best_score: float
    precision_at_1: float | None = None
    precision_at_3: float | None = None
    precision_at_5: float | None = None
    mrr: float | None = None
    ndcg_at_5: float | None = None


def score_query(
    query: QueryLabels,
    results: Sequence[RetrievedChunk],
    labels: LabelSet,
    chunks: Sequence[Chunk],
) -> QueryScore:
    """Measure one ranked list of results against the labels for its query."""
    if not results:
        raise ValueError(f"{query.id}: no results to score.")

    # The best semantic match among the results actually handed over. Not
    # the score of whatever ended up first: once a ranking is reordered by
    # fusion, position one is no longer the closest match, and a threshold
    # would be applied to what the caller can see, not to what stayed
    # behind in the index.
    best_score = max(result.score for result in results)

    if query.abstain:
        # Nothing in the corpus answers this, so there is no correct order
        # to compare against. The score is what can be judged: sounding
        # certain about a question you cannot answer is the failure here.
        return QueryScore(query_id=query.id, abstain=True, best_score=best_score)

    grades = [labels.grade_of(result.metadata, query) for result in results]

    return QueryScore(
        query_id=query.id,
        abstain=False,
        best_score=best_score,
        precision_at_1=precision_at_k(grades, 1),
        precision_at_3=precision_at_k(grades, 3),
        precision_at_5=precision_at_k(grades, 5),
        mrr=reciprocal_rank(grades),
        ndcg_at_5=ndcg_at_k(grades, ideal_grades(labels, query, chunks), 5),
    )


def separation_margin(scores: Sequence[QueryScore]) -> float:
    """Gap between the weakest answerable query and the loudest hopeless one.

    Every query returns five chunks with a score; nothing ever abstains. So
    the only way a caller could tell "here is your answer" from "there is
    no answer" would be a score threshold, and a threshold only exists if
    the two groups do not overlap. This measures the room such a threshold
    would have. Negative means the groups overlap and no threshold works.
    """
    answerable = [score.best_score for score in scores if not score.abstain]
    hopeless = [score.best_score for score in scores if score.abstain]
    if not answerable or not hopeless:
        raise ValueError("a margin needs queries of both kinds.")
    return min(answerable) - max(hopeless)


@dataclass(frozen=True)
class RunScore:
    """One whole run, reduced to the row that goes in the comparison table."""

    per_query: tuple[QueryScore, ...]
    mean_precision_at_1: float
    mean_precision_at_3: float
    mean_precision_at_5: float
    mean_mrr: float
    mean_ndcg_at_5: float
    separation_margin: float


def score_run(scores: Sequence[QueryScore]) -> RunScore:
    """Average the answerable queries and measure the gap to the rest.

    Averages cover only the queries that have an answer. Folding the other
    three in would mean averaging a number that does not exist for them.
    """
    answerable = [score for score in scores if not score.abstain]
    if not answerable:
        raise ValueError("no answerable query to average over.")

    def mean(values: list[float | None]) -> float:
        """Average one figure, refusing to guess at a missing one.
        Every value here comes from an answerable query, where score_query
        always fills the figure in. The check is for the day that stops
        being true: a None silently read as zero would drag the average
        down and look like the pipeline got worse.
        """
        present = [value for value in values if value is not None]
        if len(present) != len(values):
            raise ValueError("an answerable query is missing a figure.")
        return sum(present) / len(present)

    return RunScore(
        per_query=tuple(scores),
        mean_precision_at_1=mean([s.precision_at_1 for s in answerable]),
        mean_precision_at_3=mean([s.precision_at_3 for s in answerable]),
        mean_precision_at_5=mean([s.precision_at_5 for s in answerable]),
        mean_mrr=mean([s.mrr for s in answerable]),
        mean_ndcg_at_5=mean([s.ndcg_at_5 for s in answerable]),
        separation_margin=separation_margin(scores),
    )