"""Semantic and keyword rankings, combined by reciprocal rank fusion.

The two rankers disagree usefully. On q7 keyword search finds a section
that semantic search never returned, and on q5 semantic search finds one
that keyword search ranks nowhere near the top. Fusion is a way of taking
both without deciding in advance which to trust.

Reciprocal rank fusion adds up 1/(k + position) across the rankings a chunk
appears in. Adding the two scores directly is not an option: cosine
similarity lives between 0 and 1, BM25 runs from 0 upwards with no ceiling,
and normalizing either one would make a chunk's score depend on which other
chunks happened to come back with it. Positions have none of those
problems.

The cost is that positions are all fusion keeps. A chunk ranked third by
both rankers beats one ranked first by one and thirtieth by the other,
because 1/63 + 1/63 is more than 1/61 + 1/90. That is visible in the
report: q1 loses its correct first result this way.
"""

from __future__ import annotations

from collections.abc import Sequence

from genai_security_assistant.models.documents import Chunk
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.lexical import LexicalIndex
from genai_security_assistant.retrieval.search import BaseRetriever


class HybridRetriever:
    """Semantic search and BM25, fused. Usable anywhere the semantic one is.
    Carries the same three members ImprovedRetriever asks of a base, so the
    filtering layer wraps either without knowing which it has.
    """

    def __init__(
        self,
        base: BaseRetriever,
        lexical: LexicalIndex,
        depth: int,
        rrf_k: int,
    ) -> None:
        self.base = base
        self.lexical = lexical
        self.depth = depth
        self.rrf_k = rrf_k

    @property
    def chunks(self) -> Sequence[Chunk]:
        return self.base.chunks

    @property
    def default_top_k(self) -> int:
        return self.base.default_top_k

    def fuse(self, rankings: Sequence[Sequence[str]]) -> dict[str, float]:
        """Add 1/(rrf_k + position) for every ranking a chunk appears in.
        A chunk missing from one ranking simply collects nothing from it,
        which is what makes fusion work on rankings of different lengths.
        """
        fused: dict[str, float] = {}
        for ranking in rankings:
            for position, chunk_id in enumerate(ranking, start=1):
                weight = 1.0 / (self.rrf_k + position)
                fused[chunk_id] = fused.get(chunk_id, 0.0) + weight
        return fused

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        """Return chunks ordered by fused rank, scored by cosine as before.
        The score reported is the semantic similarity, not the fusion score.
        Fusion scores are built from positions and say nothing about how
        well a chunk matches - 1/61 + 1/70 is not a similarity. Keeping
        cosine here leaves every configuration in the report on one scale.
        """
        k = top_k or self.default_top_k
        read = max(self.depth, k)

        # One pass over the whole index gives the cosine of every candidate,
        # including those only keyword search found. On this corpus that
        # costs no more than a partial pass and no API call, since the query
        # vector is cached.
        semantic = self.base.search(query, top_k=len(self.chunks))
        by_id = {result.chunk_id: result for result in semantic}

        rankings = [
            [result.chunk_id for result in semantic[:read]],
            self.lexical.rank(query, top_k=read),
        ]
        fused = self.fuse(rankings)

        # Ties broken by cosine, so the order never depends on dictionary
        # insertion or on which ranker happened to be read first.
        order = sorted(
            fused,
            key=lambda chunk_id: (-fused[chunk_id], -by_id[chunk_id].score),
        )

        return [
            by_id[chunk_id].model_copy(update={"rank": rank})
            for rank, chunk_id in enumerate(order[:k], start=1)
        ]