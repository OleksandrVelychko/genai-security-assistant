"""Unit tests for the keyword half of the search."""

from __future__ import annotations

import pytest

from genai_security_assistant.models.documents import Chunk, ChunkMetadata
from genai_security_assistant.retrieval.lexical import LexicalIndex, tokenize


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


def test_case_and_punctuation_are_ignored():
    assert tokenize("Output, Validation!") == ["output", "validation"]


def test_digits_are_words_too():
    """LLM01:2025 has to survive as something searchable."""
    assert tokenize("LLM01:2025") == ["llm01", "2025"]


# BM25 weighs a word by how rare it is across the corpus, so a corpus of
# two says nothing: every word appears in half of it. These fixtures are
# five chunks for that reason, not for realism.
def corpus() -> list[Chunk]:
    return [
        make_chunk("c0", "Least Privilege", "grant minimal permissions to tools"),
        make_chunk("c1", "Output Validation", "validate the output format"),
        make_chunk("c2", "Introduction", "an overview of the subject"),
        make_chunk("c3", "Monitoring", "watch the logs and alert on anomalies"),
        make_chunk("c4", "Encoding", "attackers hide payloads in base64"),
    ]


def test_the_chunk_holding_the_query_words_ranks_first():
    assert LexicalIndex(corpus()).rank("validate output format", top_k=3)[0] == "c1"


def test_a_word_only_in_the_heading_is_still_findable():
    """The heading is indexed too, which is why it can decide the ranking."""
    named = make_chunk("named", "Typoglycemia Attacks", "unrelated wording here")

    index = LexicalIndex([*corpus(), named])

    assert index.rank("typoglycemia", top_k=3)[0] == "named"


def test_only_top_k_come_back():
    """Three chunks share a word with this query; only two are asked for."""
    assert len(LexicalIndex(corpus()).rank("output permissions logs", top_k=2)) == 2


def test_chunks_sharing_no_word_with_the_query_are_left_out():
    """Silence is not an opinion: a chunk BM25 scores at zero gets no place.

    Positions are what fusion pays for, so a ranker that has nothing to say
    about a chunk must not hand it one.
    """
    ranked = LexicalIndex(corpus()).rank("typoglycemia", top_k=5)

    assert ranked == []


def test_an_empty_query_is_refused():
    with pytest.raises(ValueError, match="empty"):
        LexicalIndex(corpus()).rank("   ", top_k=1)
