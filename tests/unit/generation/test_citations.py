"""Unit tests for reading citations and refusals out of an answer."""

from __future__ import annotations

from genai_security_assistant.generation.citations import (
    bare_mentions,
    extract_citation_ids,
    split_citations,
)
from genai_security_assistant.generation.prompts import FALLBACK_SENTENCE, is_refusal
from genai_security_assistant.models.documents import ChunkMetadata
from genai_security_assistant.models.retrieval import RetrievedChunk


def make_result(chunk_id: str, rank: int = 1, score: float = 0.5) -> RetrievedChunk:
    """A retrieved chunk carrying only the fields a citation reads."""
    return RetrievedChunk(
        rank=rank,
        score=score,
        chunk_id=chunk_id,
        text="body text",
        metadata=ChunkMetadata(
            document_id="llm01",
            source_file="data/raw/llm01.html",
            source_type="html",
            source_url="https://example.test/llm01",
            title="llm01",
            section="Body",
            chunk_index=0,
            language="en",
            domain="genai_security",
            document_type="security_risk",
            publisher="test",
        ),
    )


def test_the_refusal_sentence_is_recognised():
    assert is_refusal(FALLBACK_SENTENCE)


def test_a_quoted_refusal_still_counts():
    """Models often wrap the sentence in quotes. It is still a refusal."""
    assert is_refusal(f'"{FALLBACK_SENTENCE}"')


def test_a_refusal_split_over_lines_still_counts():
    """This is why normalize() collapses whitespace before comparing."""
    assert is_refusal(FALLBACK_SENTENCE.replace(" ", "\n"))


def test_a_real_answer_is_not_a_refusal():
    assert not is_refusal("Prompt injection alters model behaviour [llm01_chunk_001].")


def test_citation_ids_keep_their_order_and_appear_once():
    text = "First [chunk_a]. Second [chunk_b]. Again [chunk_a]."
    assert extract_citation_ids(text) == ["chunk_a", "chunk_b"]


def test_real_and_invented_citations_are_separated():
    retrieved = [make_result("chunk_a")]
    real, invented = split_citations("See [chunk_a] and [chunk_z].", retrieved)

    assert [citation.chunk_id for citation in real] == ["chunk_a"]
    assert invented == ["chunk_z"]


def test_a_citation_carries_the_source_file_of_its_chunk():
    real, _ = split_citations("See [chunk_a].", [make_result("chunk_a")])
    assert real[0].source_file == "data/raw/llm01.html"


def test_anything_bracketed_that_is_not_a_chunk_counts_as_invented():
    """A reader cannot check [1] either, so it is not quietly dropped."""
    _, invented = split_citations("As shown [1].", [make_result("chunk_a")])
    assert invented == ["1"]


def test_an_id_named_without_brackets_is_reported_separately():
    """Prompt v2 asks the model to mention the id but not how. This measures
    the difference between ignoring the rule and using the wrong format."""
    retrieved = [make_result("chunk_a")]
    answer = "According to chunk_a, prompt injection alters behaviour."

    real, invented = split_citations(answer, retrieved)
    assert real == []
    assert invented == []
    assert bare_mentions(answer, retrieved) == ["chunk_a"]


def test_a_bracketed_id_is_not_also_a_bare_mention():
    retrieved = [make_result("chunk_a")]
    assert bare_mentions("See [chunk_a].", retrieved) == []
