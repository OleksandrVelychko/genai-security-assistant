"""Unit tests for the query vector cache."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from genai_security_assistant.retrieval.query_cache import CachedQueryEmbedder

MODEL = "test-model"


class RecordingProvider:
    """Stands in for the embeddings API and remembers what it was asked."""

    name = "recording"
    model = MODEL
    dimension = 4

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        # A different vector per text, so looking up the wrong one shows.
        return np.array(
            [[float(len(text)), 1.0, 2.0, 3.0] for text in texts],
            dtype="float32",
        )


def exploding_factory():
    """A provider factory for tests where nothing may reach the API."""
    raise AssertionError("the real provider was built, but nothing was missing")


def test_nothing_is_built_when_the_file_is_absent(tmp_path: Path):
    """Building a provider needs an API key, so construction must not."""
    CachedQueryEmbedder(tmp_path / "qv.npz", MODEL, exploding_factory)


def test_first_call_asks_the_provider_and_writes_the_file(tmp_path: Path):
    path = tmp_path / "qv.npz"
    provider = RecordingProvider()
    cache = CachedQueryEmbedder(path, MODEL, lambda: provider)

    vectors = cache.encode(["alpha", "beta beta"])

    assert vectors.shape == (2, 4)
    assert provider.calls == [["alpha", "beta beta"]]
    assert path.exists()


def test_a_later_run_reads_from_disk_with_no_provider(tmp_path: Path):
    """The claim the reports rest on: regenerating them needs no API key."""
    path = tmp_path / "qv.npz"
    first = CachedQueryEmbedder(path, MODEL, lambda: RecordingProvider())
    expected = first.encode(["alpha", "beta beta"])

    second = CachedQueryEmbedder(path, MODEL, exploding_factory)

    assert np.array_equal(second.encode(["alpha", "beta beta"]), expected)


def test_a_repeated_text_is_paid_for_once(tmp_path: Path):
    provider = RecordingProvider()
    cache = CachedQueryEmbedder(tmp_path / "qv.npz", MODEL, lambda: provider)

    vectors = cache.encode(["alpha", "gamma", "gamma"])

    assert vectors.shape == (3, 4)
    assert provider.calls == [["alpha", "gamma"]]


def test_the_same_vectors_always_produce_the_same_file(tmp_path: Path):
    """Row order must follow the queries, not the order they arrived in."""
    early = tmp_path / "early.npz"
    late = tmp_path / "late.npz"

    CachedQueryEmbedder(early, MODEL, lambda: RecordingProvider()).encode(
        ["zeta", "alpha"]
    )
    CachedQueryEmbedder(late, MODEL, lambda: RecordingProvider()).encode(
        ["alpha", "zeta"]
    )

    assert early.read_bytes() == late.read_bytes()


def test_dimension_is_read_from_the_file(tmp_path: Path):
    path = tmp_path / "qv.npz"
    CachedQueryEmbedder(path, MODEL, lambda: RecordingProvider()).encode(["alpha"])

    assert CachedQueryEmbedder(path, MODEL, exploding_factory).dimension == 4


def test_vectors_from_another_model_are_refused(tmp_path: Path):
    """Two embedding spaces mixed together would still produce numbers."""
    path = tmp_path / "qv.npz"
    CachedQueryEmbedder(path, MODEL, lambda: RecordingProvider()).encode(["alpha"])

    with pytest.raises(RuntimeError, match="cannot be mixed"):
        CachedQueryEmbedder(path, "another-model", exploding_factory)