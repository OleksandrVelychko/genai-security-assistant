"""Unit tests for the improved retrieval pipeline."""

from __future__ import annotations

from genai_security_assistant.models.documents import (
    Chunk,
    ChunkMetadata,
    DocumentType,
)
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.filters import MetadataFilter, SectionType
from genai_security_assistant.retrieval.improved import ImprovedRetriever


def make_chunk(
    chunk_id: str,
    document_type: DocumentType = "security_risk",
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        text=chunk_id,
        metadata=ChunkMetadata(
            document_id="doc",
            source_file="data/raw/doc.html",
            source_type="html",
            source_url="https://example.test/doc",
            title="doc",
            section=chunk_id,
            chunk_index=0,
            language="en",
            domain="genai_security",
            document_type=document_type,
            publisher="test",
        ),
    )


class FakeBase:
    """A SemanticRetriever stand-in returning a fixed ranking."""

    default_top_k = 5

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.asked_for: list[int] = []

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        k = top_k or self.default_top_k
        self.asked_for.append(k)
        return [
            RetrievedChunk(
                rank=rank,
                score=1.0 - rank / 100,
                chunk_id=chunk.chunk_id,
                text=chunk.text,
                metadata=chunk.metadata,
            )
            for rank, chunk in enumerate(self.chunks[:k], start=1)
        ]


def build(
    chunks: list[Chunk],
    types: dict[str, SectionType],
    drop_boilerplate: bool = True,
    candidate_multiplier: int = 4,
) -> tuple[ImprovedRetriever, FakeBase]:
    base = FakeBase(chunks)
    retriever = ImprovedRetriever(
        base=base,
        section_types=types,
        candidate_multiplier=candidate_multiplier,
        drop_boilerplate=drop_boilerplate,
    )
    return retriever, base


def ten_body_chunks() -> tuple[list[Chunk], dict[str, SectionType]]:
    chunks = [make_chunk(f"c{n:02d}") for n in range(10)]
    return chunks, {c.chunk_id: "body" for c in chunks}


def test_with_both_switches_off_it_returns_what_hw2_returned():
    """The baseline column of the report has to be the earlier pipeline."""
    chunks, types = ten_body_chunks()
    retriever, base = build(chunks, types, drop_boilerplate=False)

    improved = retriever.search("q")
    hw2 = base.search("q", top_k=5)

    assert [r.chunk_id for r in improved] == [r.chunk_id for r in hw2]
    assert [r.rank for r in improved] == [1, 2, 3, 4, 5]


def test_boilerplate_is_dropped_and_the_rest_moves_up():
    chunks, types = ten_body_chunks()
    types["c00"] = "duplicate"
    types["c02"] = "reference_links"
    retriever, _ = build(chunks, types)

    results = retriever.search("q")

    assert [r.chunk_id for r in results] == ["c01", "c03", "c04", "c05", "c06"]
    assert [r.rank for r in results] == [1, 2, 3, 4, 5]


def test_keeping_boilerplate_is_a_switch_not_a_rewrite():
    chunks, types = ten_body_chunks()
    types["c00"] = "duplicate"
    retriever, _ = build(chunks, types, drop_boilerplate=False)

    assert retriever.search("q")[0].chunk_id == "c00"


def test_a_metadata_filter_removes_what_it_does_not_allow():
    chunks = [make_chunk("c0", "checklist")] + [
        make_chunk(f"c{n}") for n in range(1, 10)
    ]
    types: dict[str, SectionType] = {c.chunk_id: "body" for c in chunks}
    retriever, _ = build(chunks, types)

    results = retriever.search(
        "q", metadata_filter=MetadataFilter.from_config({"document_type": "checklist"})
    )

    assert [r.chunk_id for r in results] == ["c0"]


def test_a_short_first_pass_widens_to_the_whole_index():
    """The multiplier is a guess; a wrong guess must not shorten the answer."""
    chunks, types = ten_body_chunks()
    for chunk_id in ("c00", "c01", "c02", "c03", "c04"):
        types[chunk_id] = "duplicate"
    retriever, base = build(chunks, types, candidate_multiplier=1)

    results = retriever.search("q")

    assert [r.chunk_id for r in results] == ["c05", "c06", "c07", "c08", "c09"]
    assert base.asked_for == [5, 10]


def test_a_wide_enough_first_pass_is_not_repeated():
    chunks, types = ten_body_chunks()
    retriever, base = build(chunks, types, candidate_multiplier=1)

    retriever.search("q")

    assert base.asked_for == [5]


def test_fewer_survivors_than_asked_for_is_returned_as_it_is():
    """When the corpus really holds less, a short list is the honest answer."""
    chunks, types = ten_body_chunks()
    for chunk in chunks[2:]:
        types[chunk.chunk_id] = "duplicate"
    retriever, _ = build(chunks, types)

    assert [r.chunk_id for r in retriever.search("q")] == ["c00", "c01"]
