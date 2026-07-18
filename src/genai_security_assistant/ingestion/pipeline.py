"""Ingestion pipeline: raw sources -> normalized documents -> chunks -> JSONL."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel

from genai_security_assistant.config import Settings, load_sources
from genai_security_assistant.ingestion.chunking import chunk_document
from genai_security_assistant.ingestion.normalization import normalize_source
from genai_security_assistant.models.documents import Chunk, NormalizedDocument


def write_jsonl(records: Iterable[BaseModel], output_path: Path) -> int:
    """Write pydantic models as JSONL: one JSON object per line."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json() + "\n")
            count += 1
    return count


def build_knowledge_base(settings: Settings | None = None) -> dict[str, Any]:
    """Run the full pipeline and persist both intermediate and final artifacts."""
    settings = settings or Settings()
    raw_dir = settings.path("raw_dir")
    sources = load_sources(settings.path("sources_manifest"))

    documents: list[NormalizedDocument] = [
        normalize_source(entry, raw_dir) for entry in sources
    ]

    chunking = settings.chunking
    chunks: list[Chunk] = []
    for document in documents:
        chunks.extend(
            chunk_document(
                document,
                chunk_size=chunking["chunk_size"],
                overlap=chunking["chunk_overlap"],
                min_chunk_size=chunking["min_chunk_size"],
            )
        )

    return {
        "sources": len(sources),
        "documents": write_jsonl(documents, settings.path("normalized_documents")),
        "chunks": write_jsonl(chunks, settings.path("chunks")),
        "normalized_path": settings.path("normalized_documents"),
        "chunks_path": settings.path("chunks"),
    }