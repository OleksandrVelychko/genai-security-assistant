"""Unit tests for the fusion of semantic and keyword rankings."""

from __future__ import annotations

from genai_security_assistant.models.documents import Chunk, ChunkMetadata
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.hybrid import HybridRetriever
from genai_security_assistant.retrieval.lexical import LexicalIndex

# The value configs/base.yaml uses, repeated here rather than read from it:
# this test should not change behavior when config file is changed.
RRF_K = 60


def make_chunk(chunk_id: str, section: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        metadata=ChunkMetadata(
            document_id="doc",
            source_file="data/raw/doc.html",
            source_type="html",
            source_url="https://example.test/doc",
            title="doc",
            section=section,
            chunk_index=0,
            language="en",
            domain="genai_security",
            document_type="security_risk",
            publisher="test",
        ),
    )


def corpus() -> list[Chunk]:
    return [
        make_chunk("c0", "Least Privilege", "grant minimal permissions to tools"),
        make_chunk("c1", "Output Validation", "validate the output format"),
        make_chunk("c2", "Introduction", "an overview of the subject"),
        make_chunk("c3", "Monitoring", "watch the logs and alert on anomalies"),
        make_chunk("c4", "Encoding", "attackers hide payloads in base64"),
    ]


class FakeBase:
    """Semantic search with a ranking fixed by the test."""

    def __init__(self, chunks: list[Chunk], order: list[str]) -> None:
        self._chunks = chunks
        self.order = order

    @property
    def chunks(self) -> list[Chunk]:
        return self._chunks

    @property
    def default_top_k(self) -> int:
        return 3

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        by_id = {chunk.chunk_id: chunk for chunk in self._chunks}
        k = top_k or self.default_top_k
        return [
            RetrievedChunk(
                rank=rank,
                score=1.0 - rank / 100,
                chunk_id=chunk_id,
                text=by_id[chunk_id].text,
                metadata=by_id[chunk_id].metadata,
            )
            for rank, chunk_id in enumerate(self.order[:k], start=1)
        ]


def build(order: list[str], depth: int = 20) -> HybridRetriever:
    chunks = corpus()
    return HybridRetriever(
        base=FakeBase(chunks, order),
        lexical=LexicalIndex(chunks),
        depth=depth,
        rrf_k=RRF_K,
    )


def test_appearing_in_both_rankings_beats_appearing_in_one():
    retriever = build(["c0", "c1", "c2", "c3", "c4"])

    fused = retriever.fuse([["a", "b"], ["b", "c"]])

    assert fused["b"] > fused["a"]
    assert fused["b"] > fused["c"]


def test_second_in_both_beats_first_in_only_one():
    """The trade-off this method makes, written down as a number.

    q1 loses its correct first result to exactly this: a chunk both
    rankers merely like outscores one that a single ranker is sure of.
    """
    retriever = build(["c0", "c1", "c2", "c3", "c4"])

    fused = retriever.fuse([["sure", "steady"], ["steady", "sure"]])
    lopsided = retriever.fuse([["sure"] + [f"x{n}" for n in range(29)] + ["sure"]])

    assert fused["steady"] == fused["sure"]
    assert fused["sure"] > lopsided["sure"]


def test_a_missing_chunk_simply_collects_nothing():
    retriever = build(["c0", "c1", "c2", "c3", "c4"])

    fused = retriever.fuse([["a"], ["b"]])

    assert fused["a"] == fused["b"] == 1.0 / (RRF_K + 1)


def test_the_score_reported_is_the_cosine_not_the_fusion_score():
    """Fusion scores come from positions and are not similarities."""
    retriever = build(["c0", "c1", "c2", "c3", "c4"])

    results = retriever.search("validate output format", top_k=3)

    assert all(result.score > 0.9 for result in results)


def test_keyword_matches_can_overtake_the_semantic_order():
    """c1 is last for the semantic ranker and first for the keyword one."""
    retriever = build(["c0", "c2", "c3", "c4", "c1"])

    results = retriever.search("validate output format", top_k=3)

    assert results[0].chunk_id == "c1"
    assert [result.rank for result in results] == [1, 2, 3]


def test_it_passes_the_wrapped_pipeline_through():
    retriever = build(["c0", "c1", "c2", "c3", "c4"])

    assert retriever.default_top_k == 3
    assert len(retriever.chunks) == 5