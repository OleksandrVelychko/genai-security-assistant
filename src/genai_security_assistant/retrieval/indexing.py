"""Build the vector index from data/processed/chunks.jsonl.
Reads chunks, encodes them, writes index/ with three files:
the FAISS index, a snapshot of the chunks in index order, and a metadata sidecar.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from genai_security_assistant.config import Settings
from genai_security_assistant.models.documents import Chunk
from genai_security_assistant.models.retrieval import IndexMeta, chunks_digest
from genai_security_assistant.retrieval.embeddings import build_embedding_provider
from genai_security_assistant.retrieval.vector_store import FaissVectorStore


def load_chunks(path: Path) -> list[Chunk]:
    """Read chunks.jsonl into validated models, keeping file order."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Build the knowledge base first: "
            "uv run python scripts/prepare_knowledge_base.py"
        )

    chunks: list[Chunk] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                chunks.append(Chunk.model_validate_json(stripped))
            except ValueError as error:
                raise ValueError(
                    f"Invalid chunk at {path}:{line_number} - {error}"
                ) from error

    if not chunks:
        raise ValueError(f"{path} contains no chunks.")
    return chunks


def save_chunks(chunks: list[Chunk], path: Path) -> None:
    """Write the chunks that were indexed, in index order.
    Row N of the FAISS index is line N of this file. Keeping a copy next
    to the index means a later rebuild of data/processed cannot quietly
    change what the index points at.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(chunk.model_dump_json() + "\n")


def build_index(settings: Settings | None = None) -> dict[str, Any]:
    """Run the full chunks -> index pipeline and return a summary."""
    settings = settings or Settings()

    source_path = settings.path("chunks")
    chunks = load_chunks(source_path)

    embedding_config = settings.embedding_config()
    provider = build_embedding_provider(embedding_config)

    vectors = provider.encode([chunk.text for chunk in chunks])

    meta = IndexMeta(
        provider=provider.name,
        model=provider.model,
        dimension=int(vectors.shape[1]),
        chunks_count=len(chunks),
        chunks_digest=chunks_digest([chunk.chunk_id for chunk in chunks]),
        source_chunks_path=settings.paths["chunks"],
        built_at=datetime.now(timezone.utc),
    )

    store = FaissVectorStore.build(vectors, meta)

    index_path = settings.path("faiss_index")
    meta_path = settings.path("index_meta")
    snapshot_path = settings.path("index_chunks")

    store.save(index_path, meta_path)
    save_chunks(chunks, snapshot_path)

    return {
        "provider": provider.name,
        "model": provider.model,
        "dimension": meta.dimension,
        "chunks": meta.chunks_count,
        "documents": len({chunk.metadata.document_id for chunk in chunks}),
        "index_path": index_path,
        "meta_path": meta_path,
        "snapshot_path": snapshot_path,
        "index_size_mb": index_path.stat().st_size / 1024 / 1024,
    }
