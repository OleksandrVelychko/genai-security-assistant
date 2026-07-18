"""Unit tests for the structure-aware chunker."""

from __future__ import annotations

from genai_security_assistant.ingestion.chunking import (
    build_overlap,
    chunk_section_text,
    force_split,
    split_blocks,
)

CHUNK_SIZE = 700
OVERLAP = 150
MIN_CHUNK = 200


def test_split_blocks_keeps_code_fences_atomic():
    text = "Intro line.\n```python\nx = 1\ny = 2\n```\nAfter the code."
    blocks = split_blocks(text)
    assert "```python\nx = 1\ny = 2\n```" in blocks
    assert "Intro line." in blocks


def test_force_split_never_breaks_a_word():
    text = " ".join(["alpha"] * 200)
    parts = force_split(text, 100)
    assert all(len(part) <= 100 for part in parts)
    assert all(token == "alpha" for part in parts for token in part.split())


def test_build_overlap_is_sentence_aligned():
    text = "First sentence here. Second sentence here. Third sentence here."
    carry = build_overlap(text, OVERLAP)
    assert len(carry) <= OVERLAP
    assert carry.endswith("Third sentence here.")


def test_build_overlap_caps_a_single_long_sentence():
    """Regression: an over-long final sentence used to blow the size budget."""
    carry = build_overlap("word " * 500, OVERLAP)
    assert len(carry) <= OVERLAP


def test_chunks_respect_the_upper_bound():
    paragraph = "This is a sentence with enough words to matter. " * 40
    chunks = chunk_section_text(paragraph, CHUNK_SIZE, OVERLAP, MIN_CHUNK)
    assert chunks
    assert all(len(chunk) <= CHUNK_SIZE + OVERLAP for chunk in chunks)


def test_short_section_stays_one_chunk():
    text = "Short but complete sentence."
    assert chunk_section_text(text, CHUNK_SIZE, OVERLAP, MIN_CHUNK) == [text]