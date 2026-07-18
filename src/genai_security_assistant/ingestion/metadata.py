"""Chunk identity and metadata assembly."""

from __future__ import annotations

from genai_security_assistant.models.documents import (
    ChunkMetadata,
    NormalizedDocument,
    NormalizedSection,
)


def build_chunk_id(document_id: str, chunk_index: int) -> str:
    """Stable, sortable, human-readable chunk identifier."""
    return f"{document_id}_chunk_{chunk_index:03d}"


def build_chunk_metadata(
    document: NormalizedDocument,
    section: NormalizedSection,
    chunk_index: int,
) -> ChunkMetadata:
    """Flatten document- and section-level provenance onto a single chunk."""
    return ChunkMetadata(
        document_id=document.document_id,
        source_file=document.source_file,
        source_type=document.source_type,
        source_url=document.metadata.source_url,
        title=document.title,
        section=section.section,
        heading_path=section.heading_path,
        chunk_index=chunk_index,
        language=document.metadata.language,
        domain=document.metadata.domain,
        document_type=document.metadata.document_type,
        risk_category=document.metadata.risk_category,
        publisher=document.metadata.publisher,
        doc_version=document.metadata.doc_version,
        retrieved_at=document.metadata.retrieved_at,
        content_hash=document.metadata.content_hash,
    )