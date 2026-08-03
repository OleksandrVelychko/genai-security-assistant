"""Frozen query vectors, so that repeated runs produce identical numbers.

The document side of this project has been frozen since HW2: the 264 chunk
vectors live in index/faiss.index and are read from disk, never recomputed.
The query side was not. Every run sent the test queries to the embeddings
API and used whatever came back.

Two runs four minutes apart, with no file changed in between, got slightly
different vectors for the same strings. The API does not promise identical
numbers for identical input. The gap was about one part in a thousand,
which sounds harmless, but chunks near the bottom of the top-5 sit closer
together than that, so the order changed:

    run A   rank 5   owasp_llm_governance_checklist / Page 19     0.5014
    run B   rank 5   owasp_llm02_... / Incorporate Differential   0.5000

HW3 measures whether a new pipeline ranks better than the old one. If the
ranking also moves on its own between runs, and by about as much, then a
better score proves nothing: it could just as easily be the noise. So query
vectors are fetched once, written to disk and committed, then read from
disk, the same way chunk vectors already are.

Two things follow, and both belong in the report:

- The numbers describe the pipeline given one fixed set of query vectors,
  not an average over everything the API might have returned. Comparing two
  pipelines is still fair, since both read the same file, but a number
  quoted on its own should be read with that in mind.
- Nothing in the search path calls the API once the file exists, so both
  reports can be regenerated from a fresh clone with no API key at all.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

from genai_security_assistant.retrieval.embeddings import EmbeddingProvider


class CachedQueryEmbedder:
    """Stands in for an embedding provider, answering from a file when it can.
    Carries the same attributes and the same encode() as the real providers
    in embeddings.py, so the calling code needs no special case. The one
    deliberate difference is 'name', which reports how the vector was
    obtained rather than which service produced it.
    """

    name = "cached_query"

    def __init__(
        self,
        path: Path,
        model: str,
        build_provider: Callable[[], EmbeddingProvider],
    ) -> None:
        self.path = path
        self.model = model

        # A function rather than a ready provider, and called only when
        # something is actually missing. Constructing the real provider
        # demands an API key, so building it here would demand one even when
        # every vector is already on disk. The docstring above promises the
        # reports can be regenerated without a key; this is the line that
        # keeps that promise.
        self._build_provider = build_provider
        self._provider: EmbeddingProvider | None = None

        self._vectors: dict[str, np.ndarray] = {}
        self._load()

    def _load(self) -> None:
        """Read the saved vectors, refusing anything from a different model."""
        if not self.path.exists():
            return

        with np.load(self.path, allow_pickle=False) as data:
            stored_model = str(data["model"])
            if stored_model != self.model:
                raise RuntimeError(
                    f"{self.path} holds vectors produced by {stored_model!r}, "
                    f"but configs/base.yaml now asks for {self.model!r}. "
                    "Vectors from two different models describe different "
                    "spaces and cannot be mixed. Delete the file to rebuild "
                    "it, and note that every measurement taken with the old "
                    "model stops being comparable at that moment."
                )
            queries = [str(query) for query in data["queries"]]
            vectors = data["vectors"]

        self._vectors = {query: vectors[row] for row, query in enumerate(queries)}

    def _save(self) -> None:
        """Write every known vector, ordered by query text.
        The file is a zip archive, so git can report that it changed but
        never which rows. Sorting is therefore not about reading the diff.
        It makes the bytes depend on which vectors are stored and nothing
        else: numpy stamps every entry with a fixed 1980 date, so the same
        set of vectors always produces the same file. Stored in arrival
        order, the same vectors fetched in a different sequence would
        rewrite the file and show up as a change that never happened.
        """
        queries = sorted(self._vectors)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            self.path,
            model=np.array(self.model),
            queries=np.array(queries),
            vectors=np.stack([self._vectors[query] for query in queries]),
        )

    def _ensure_provider(self) -> EmbeddingProvider:
        """Build the real provider on first need, and keep it."""
        if self._provider is None:
            self._provider = self._build_provider()
        return self._provider

    @property
    def dimension(self) -> int:
        """Vector length. Required by the provider interface, but the search
        path never asks for it: FaissVectorStore checks the query vector it
        is handed against the index metadata itself. Reading the length off
        a cached vector keeps this from becoming the one property that
        quietly needs an API key.
        """
        if self._vectors:
            return int(next(iter(self._vectors.values())).shape[0])
        return self._ensure_provider().dimension

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return one vector per text, fetching only what is not on disk."""
        missing = [text for text in texts if text not in self._vectors]
        if not texts:
            return np.empty((0, self.dimension), dtype="float32")
        if missing:
            # One request for everything absent, then one write: each request
            # costs money and time, and each save rewrites the whole file. The
            # same text can appear twice in one call, and paying twice for it
            # would be pointless, so duplicates go first.
            unique = list(dict.fromkeys(missing))
            fresh = self._ensure_provider().encode(unique)
            for text, vector in zip(unique, fresh):
                self._vectors[text] = vector.astype("float32")
            self._save()

        return np.stack([self._vectors[text] for text in texts])