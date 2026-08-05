"""Pydantic data contracts for the knowledge base ingestion pipeline.

Every raw source (Markdown, HTML, PDF) is normalized into these models,
which also define the shape of the final chunks in data/processed/chunks.jsonl.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- Controlled vocabularies (mirror the comments in configs/sources.yaml) ---

DocumentType = Literal[
    "security_risk",
    "cheat_sheet",
    "checklist",
]

RiskCategory = Literal[
    "prompt_injection",
    "sensitive_information_disclosure",
    "supply_chain",
    "data_and_model_poisoning",
    "improper_output_handling",
    "excessive_agency",
    "system_prompt_leakage",
    "vector_and_embedding_weaknesses",
    "misinformation",
    "unbounded_consumption",
    "governance",
    "general",
]

SourceType = Literal["markdown", "html", "pdf"]


class SourceMetadata(BaseModel):
    """Provenance of a source document.
    Authored fields come from configs/sources.yaml.
    retrieved_at and content_hash are filled by the pipeline at ingestion.
    """

    source_url: str
    publisher: str
    language: str = "en"
    domain: str = "genai_security"
    document_type: DocumentType
    risk_category: RiskCategory | None = None
    license: str | None = None
    doc_version: str | None = None
    retrieved_at: datetime | None = None
    content_hash: str | None = None


class NormalizedSection(BaseModel):
    """A logical section of a normalized document, tied to a heading."""

    heading_path: list[str] = Field(default_factory=list)
    section: str | None = None
    text: str


class NormalizedDocument(BaseModel):
    """Single internal representation of any source after normalization."""

    document_id: str
    source_file: str
    source_type: SourceType
    title: str
    sections: list[NormalizedSection]
    metadata: SourceMetadata


class ChunkMetadata(BaseModel):
    """Metadata carried by every chunk (denormalized for retrieval/filtering)."""

    document_id: str
    source_file: str
    source_type: SourceType
    source_url: str
    title: str
    section: str | None = None
    heading_path: list[str] = Field(default_factory=list)
    chunk_index: int
    language: str
    domain: str
    document_type: DocumentType
    risk_category: RiskCategory | None = None
    publisher: str
    doc_version: str | None = None
    retrieved_at: datetime | None = None
    content_hash: str | None = None


class Chunk(BaseModel):
    """Final unit written as one JSONL line in data/processed/chunks.jsonl."""

    chunk_id: str
    text: str
    metadata: ChunkMetadata
