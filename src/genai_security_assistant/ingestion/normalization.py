"""Assemble NormalizedDocument objects from raw files + manifest entries."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from genai_security_assistant.config import PROJECT_ROOT
from genai_security_assistant.ingestion.loaders.base import BaseLoader
from genai_security_assistant.ingestion.loaders.html import HtmlLoader
from genai_security_assistant.ingestion.loaders.markdown import MarkdownLoader
from genai_security_assistant.ingestion.loaders.pdf import PdfLoader
from genai_security_assistant.models.documents import NormalizedDocument, SourceMetadata


def compute_content_hash(file_path: Path) -> str:
    """SHA-256 of the raw file, used to detect upstream changes on re-ingestion."""
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def build_loader(entry: dict[str, Any]) -> BaseLoader:
    """Pick the loader for a source, passing per-document options."""
    source_type = entry["source_type"]
    if source_type == "markdown":
        return MarkdownLoader()
    if source_type == "html":
        return HtmlLoader()
    if source_type == "pdf":
        return PdfLoader(skip_pages=entry.get("skip_pages", 0))
    raise ValueError(f"Unsupported source_type: {source_type}")


def normalize_source(entry: dict[str, Any], raw_dir: Path) -> NormalizedDocument:
    """Convert one manifest entry + its raw file into a NormalizedDocument."""
    file_path = raw_dir / entry["source_file"]
    if not file_path.exists():
        raise FileNotFoundError(f"Raw file listed in manifest is missing: {file_path}")

    sections = build_loader(entry).load(file_path)

    metadata = SourceMetadata(
        source_url=entry["source_url"],
        publisher=entry["publisher"],
        language=entry.get("language", "en"),
        domain=entry.get("domain", "genai_security"),
        document_type=entry["document_type"],
        risk_category=entry.get("risk_category"),
        license=entry.get("license"),
        doc_version=entry.get("doc_version"),
        # Machine-generated provenance, not authored in the manifest:
        retrieved_at=datetime.now(timezone.utc),
        content_hash=compute_content_hash(file_path),
    )

    return NormalizedDocument(
        document_id=entry["document_id"],
        source_file=file_path.relative_to(PROJECT_ROOT).as_posix(),
        source_type=entry["source_type"],
        title=entry["title"],
        sections=sections,
        metadata=metadata,
    )
