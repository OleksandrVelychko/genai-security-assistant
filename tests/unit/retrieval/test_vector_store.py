"""Unit tests for the FAISS vector store."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from genai_security_assistant.models.retrieval import IndexMeta, chunks_digest
from genai_security_assistant.retrieval.vector_store import FaissVectorStore, normalize


def make_meta(count, dim):
    return IndexMeta(
        provider="openai",
        model="test-model",
        dimension=dim,
        chunks_count=count,
        chunks_digest=chunks_digest([f"c{i}" for i in range(count)]),
        source_chunks_path="data/processed/chunks.jsonl",
        built_at=datetime.now(timezone.utc),
    )


def sample_vectors(count=5, dim=8, seed=42):
    rng = np.random.default_rng(seed)
    return rng.normal(size=(count, dim)).astype("float32")


def test_normalize_returns_unit_vectors():
    norms = np.linalg.norm(normalize(sample_vectors()), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-6)


def test_normalize_does_not_mutate_input():
    """faiss.normalize_L2 works in place; normalize() must copy first."""
    vectors = sample_vectors()
    before = vectors.copy()
    normalize(vectors)
    assert np.array_equal(vectors, before)


def test_build_rejects_wrong_vector_count():
    with pytest.raises(ValueError, match="does not match"):
        FaissVectorStore.build(
            sample_vectors(count=5, dim=8), make_meta(count=4, dim=8)
        )


def test_build_rejects_wrong_dimension():
    with pytest.raises(ValueError, match="dimension"):
        FaissVectorStore.build(
            sample_vectors(count=5, dim=8), make_meta(count=5, dim=16)
        )


def test_chunk_finds_itself_first():
    """A vector searched against its own index must rank first with score ~1."""
    vectors = sample_vectors()
    store = FaissVectorStore.build(vectors, make_meta(count=5, dim=8))
    top_row, top_score = store.search(vectors[2], top_k=3)[0]
    assert top_row == 2
    assert top_score > 0.999


def test_search_caps_k_to_index_size():
    vectors = sample_vectors(count=3, dim=8)
    store = FaissVectorStore.build(vectors, make_meta(count=3, dim=8))
    assert len(store.search(vectors[0], top_k=10)) == 3


def test_save_and_load_round_trip(tmp_path: Path):
    vectors = sample_vectors()
    store = FaissVectorStore.build(vectors, make_meta(count=5, dim=8))
    index_path = tmp_path / "faiss.index"
    meta_path = tmp_path / "meta.json"
    store.save(index_path, meta_path)

    reloaded = FaissVectorStore.load(index_path, meta_path)
    assert reloaded.index.ntotal == 5
    assert reloaded.meta.model == "test-model"
    assert reloaded.search(vectors[2], top_k=1)[0][0] == 2


def test_load_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        FaissVectorStore.load(tmp_path / "nope.index", tmp_path / "nope.json")