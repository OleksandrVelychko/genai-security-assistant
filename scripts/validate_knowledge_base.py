"""Validate data/processed/chunks.jsonl and report knowledge base quality.

Run from the project root:
    uv run python scripts/validate_knowledge_base.py
"""

from __future__ import annotations

import sys

from genai_security_assistant.config import Settings
from genai_security_assistant.ingestion.validation import load_chunks, validate_chunks


def main() -> int:
    settings = Settings()
    path = settings.path("chunks")
    if not path.exists():
        print(f"Missing {path}. Run scripts/prepare_knowledge_base.py first.")
        return 1

    chunks, parse_errors = load_chunks(path)
    report = validate_chunks(chunks, settings.chunking["min_chunk_size"])

    print("=" * 70)
    print("KNOWLEDGE BASE VALIDATION")
    print("=" * 70)
    print(f"File              : {path}")
    print(f"Chunks parsed     : {report['total']}")
    print(f"Parse errors      : {len(parse_errors)}")
    print(
        "Length min/avg/max: "
        f"{report['length_min']} / {report['length_avg']} / {report['length_max']}"
    )

    print("\nChunks per document:")
    for document_id, count in sorted(report["per_document"].items()):
        print(f"  {document_id:52} {count:4}")

    print("\nChunks per source type:")
    for source_type, count in sorted(report["per_source_type"].items()):
        print(f"  {source_type:10} {count:4}")

    print()
    issues = {
        "duplicate chunk_id": report["duplicate_ids"],
        "empty text": report["empty_text"],
        "below min_chunk_size": report["below_minimum"],
        "above 1000 characters": report["above_maximum"],
        "unmapped glyphs": report["suspicious_chars"],
    }
    for label, items in issues.items():
        print(f"{label:22}: {'OK' if not items else str(len(items)) + ' found'}")
        for item in items[:5]:
            print(f"    {item}")

    blocking = bool(parse_errors or report["duplicate_ids"] or report["empty_text"])
    print("\nRESULT:", "FAIL" if blocking else "PASS")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
