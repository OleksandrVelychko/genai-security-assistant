"""Integration test: the generated knowledge base is structurally valid."""

from __future__ import annotations

import pytest

from genai_security_assistant.config import Settings
from genai_security_assistant.ingestion.validation import load_chunks, validate_chunks


def test_generated_knowledge_base_is_valid():
    settings = Settings()
    path = settings.path("chunks")
    if not path.exists():
        pytest.skip("Run scripts/prepare_knowledge_base.py first")

    chunks, errors = load_chunks(path)
    report = validate_chunks(chunks, settings.chunking["min_chunk_size"])

    assert not errors
    assert report["total"] > 0
    assert not report["duplicate_ids"]
    assert not report["empty_text"]
    assert not report["above_maximum"]
