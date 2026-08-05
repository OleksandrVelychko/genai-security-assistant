"""FAISS index wrapper: build, save, load, search.
Keeps the vector side of retrieval in one place.
Chunk texts and metadata live in a separate JSONL file.
The index only knows row numbers.
"""

from __future__ import annotations

from pathlib import Path

import faiss
import numpy as np

from genai_security_assistant.models.retrieval import IndexMeta


def normalize(vectors: np.ndarray) -> np.ndarray:
    """Scale every row to unit length.
    With unit vectors the inner product is the cosine, which is needed for text.
    Vector length tracks chunk length, not meaning.
    Returns a copy, because faiss.normalize_L2 rewrites its argument.
    """
    prepared = np.array(vectors, dtype="float32", copy=True, order="C")
    faiss.normalize_L2(prepared)
    return prepared


class FaissVectorStore:
    """A FAISS index plus the metadata describing how it was built."""

    def __init__(self, index: faiss.Index, meta: IndexMeta) -> None:
        self.index = index
        self.meta = meta

    @classmethod
    def build(cls, vectors: np.ndarray, meta: IndexMeta) -> FaissVectorStore:
        """Normalize the vectors and load them into a flat inner-product index."""
        if vectors.ndim != 2:
            raise ValueError(f"Expected a 2D array, got shape {vectors.shape}.")
        if vectors.shape[0] != meta.chunks_count:
            raise ValueError(
                f"Vector count {vectors.shape[0]} does not match "
                f"chunks_count {meta.chunks_count} in the index metadata."
            )
        if vectors.shape[1] != meta.dimension:
            raise ValueError(
                f"Vector dimension {vectors.shape[1]} does not match "
                f"dimension {meta.dimension} in the index metadata."
            )

        normalized = normalize(vectors)
        index = faiss.IndexFlatIP(meta.dimension)
        index.add(normalized)
        return cls(index=index, meta=meta)

    def save(self, index_path: Path, meta_path: Path) -> None:
        """Write the index and its sidecar descriptor."""
        index_path.parent.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(index_path))
        meta_path.write_text(
            self.meta.model_dump_json(indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, index_path: Path, meta_path: Path) -> FaissVectorStore:
        """Read an index built by a previous run."""
        for path in (index_path, meta_path):
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} not found. Build the index first: "
                    "uv run python scripts/build_index.py"
                )

        meta = IndexMeta.model_validate_json(
            meta_path.read_text(encoding="utf-8")
        )
        index = faiss.read_index(str(index_path))

        if index.ntotal != meta.chunks_count:
            raise RuntimeError(
                f"Index holds {index.ntotal} vectors but its metadata claims "
                f"{meta.chunks_count}. The index directory is inconsistent."
            )
        return cls(index=index, meta=meta)

    def search(self, query_vector: np.ndarray, top_k: int) -> list[tuple[int, float]]:
        """Return (row, score) pairs, best first.

        The query is normalized the same way the chunks were, so scores come
        back as cosine similarity.
        """
        query = normalize(query_vector.reshape(1, -1))
        if query.shape[1] != self.meta.dimension:
            raise ValueError(
                f"Query dimension {query.shape[1]} does not match index "
                f"dimension {self.meta.dimension}."
            )

        effective_k = min(top_k, self.index.ntotal)
        scores, rows = self.index.search(query, effective_k)

        # FAISS pads with -1 when it finds fewer neighbours than requested.
        return [
            (int(row), float(score))
            for row, score in zip(rows[0], scores[0])
            if row != -1
        ]
