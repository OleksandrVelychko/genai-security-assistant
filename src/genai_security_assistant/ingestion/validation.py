"""Quality checks for the generated knowledge base."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from genai_security_assistant.models.documents import Chunk

# Glyphs that signal a broken source extraction (see PdfLoader font repair).
SUSPICIOUS_CHARS = ("\uffff", "\ufffd")
HARD_MAX_LENGTH = 1000  # assignment upper bound


def load_chunks(path: Path) -> tuple[list[Chunk], list[str]]:
    """Read chunks.jsonl, returning parsed chunks and per-line errors."""
    chunks: list[Chunk] = []
    errors: list[str] = []

    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                chunks.append(Chunk.model_validate_json(line))
            except ValidationError as error:
                errors.append(f"line {line_number}: {error.error_count()} schema error(s)")
            except json.JSONDecodeError as error:
                errors.append(f"line {line_number}: invalid JSON ({error.msg})")

    return chunks, errors


def validate_chunks(chunks: list[Chunk], min_chunk_size: int) -> dict[str, Any]:
    """Collect quality metrics and rule violations for a set of chunks."""
    lengths = [len(chunk.text) for chunk in chunks]
    identifier_counts = Counter(chunk.chunk_id for chunk in chunks)

    return {
        "total": len(chunks),
        "length_min": min(lengths) if lengths else 0,
        "length_avg": sum(lengths) // len(lengths) if lengths else 0,
        "length_max": max(lengths) if lengths else 0,
        "duplicate_ids": [cid for cid, n in identifier_counts.items() if n > 1],
        "empty_text": [c.chunk_id for c in chunks if not c.text.strip()],
        "below_minimum": [c.chunk_id for c in chunks if len(c.text) < min_chunk_size],
        "above_maximum": [c.chunk_id for c in chunks if len(c.text) > HARD_MAX_LENGTH],
        "suspicious_chars": [
            c.chunk_id for c in chunks if any(ch in c.text for ch in SUSPICIOUS_CHARS)
        ],
        "per_document": dict(Counter(c.metadata.document_id for c in chunks)),
        "per_source_type": dict(Counter(c.metadata.source_type for c in chunks)),
    }