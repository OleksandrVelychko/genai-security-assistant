"""Unit tests for the retrieval data contracts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from genai_security_assistant.models.documents import ChunkMetadata
from genai_security_assistant.models.retrieval import (
    IndexMeta,
    RetrievedChunk,
    chunks_digest,
)


def make_meta(**overrides):
    base = {
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "chunks_count": 3,
        "chunks_digest": chunks_digest(["a", "b", "c"]),
        "source_chunks_path": "data/processed/chunks.jsonl",
        "built_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return IndexMeta(**base)


def test_digest_is_stable_for_same_order():
    assert chunks_digest(["a", "b", "c"]) == chunks_digest(["a", "b", "c"])


def test_digest_changes_when_order_changes():
    """Order matters: FAISS maps rows by position, so a reorder must be visible."""
    assert chunks_digest(["a", "b", "c"]) != chunks_digest(["b", "a", "c"])


def test_assert_compatible_passes_for_same_model():
    make_meta().assert_compatible(provider="openai", model="text-embedding-3-small")


def test_assert_compatible_fails_for_different_model():
    with pytest.raises(RuntimeError, match="Rebuild the index"):
        make_meta().assert_compatible(provider="openai", model="text-embedding-3-large")


def test_assert_compatible_fails_for_different_provider():
    with pytest.raises(RuntimeError):
        make_meta().assert_compatible(
            provider="sentence_transformers", model="text-embedding-3-small"
        )


def test_index_meta_rejects_zero_dimension():
    with pytest.raises(ValueError):
        make_meta(dimension=0)


def make_retrieved(text):
    return RetrievedChunk(
        rank=1,
        score=0.5,
        chunk_id="c1",
        text=text,
        metadata=ChunkMetadata(
            document_id="doc1",
            source_file="data/raw/doc1.md",
            source_type="markdown",
            source_url="https://example.org",
            title="Doc 1",
            chunk_index=1,
            language="en",
            domain="genai_security",
            document_type="cheat_sheet",
            publisher="OWASP",
        ),
    )


def test_preview_collapses_whitespace():
    assert make_retrieved("line one\n\n   line two").preview(100) == "line one line two"


def test_preview_truncates_long_text():
    preview = make_retrieved("word " * 100).preview(20)
    assert len(preview) <= 23  # 20 chars + "..."
    assert preview.endswith("...")