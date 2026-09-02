"""Pydantic data contracts for the semantic retrieval layer.
Mirrors models/documents.py: types are declared here, the retrieval
package fills them in.
Two contracts:
  IndexMeta - descriptor of a built vector index (sidecar JSON)
  RetrievedChunk - one hit returned by top-k semantic search
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from genai_security_assistant.models.documents import ChunkMetadata

EmbeddingProviderName = Literal["openai", "sentence_transformers"]


def chunks_digest(chunk_ids: list[str]) -> str:
    """Order-sensitive fingerprint of the indexed chunk sequence.
    FAISS knows row numbers, not chunk ids. Reorder chunks.jsonl and every
    search result points at the wrong chunk, with no error to warn.
    The hash allows checking if the file still matches the index.
    """
    joined = "\n".join(chunk_ids).encode("utf-8")
    return hashlib.sha256(joined).hexdigest()


class IndexMeta(BaseModel):
    """Descriptor written to index/index_meta.json next to the FAISS file."""

    provider: EmbeddingProviderName
    model: str
    dimension: int = Field(gt=0)
    metric: str = "cosine"
    index_type: str = "IndexFlatIP"
    normalized: bool = True
    chunks_count: int = Field(gt=0)
    chunks_digest: str
    source_chunks_path: str
    built_at: datetime

    def assert_compatible(self, provider: str, model: str) -> None:
        """Fail fast when the query-time model differs from the indexed one.
        Chunk and query vectors must live in the same embedding space;
        otherwise scores are meaningless even though nothing crashes.
        """
        if self.provider != provider or self.model != model:
            raise RuntimeError(
                f"Index was built with {self.provider}/{self.model}, "
                f"but the current config selects {provider}/{model}. "
                "Rebuild the index: uv run python scripts/build_index.py"
            )


class RetrievedChunk(BaseModel):
    """A single top-k hit: score plus the full chunk it points to."""

    rank: int = Field(ge=1)
    score: float
    chunk_id: str
    text: str
    metadata: ChunkMetadata

    def preview(self, max_chars: int) -> str:
        """Single-line, length-capped text for reports and CLI output."""
        flattened = " ".join(self.text.split())
        if len(flattened) <= max_chars:
            return flattened
        return flattened[:max_chars].rstrip() + "..."
