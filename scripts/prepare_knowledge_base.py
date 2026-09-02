"""Build the knowledge base: raw sources -> data/processed/chunks.jsonl.
Run from the project root:
    uv run python scripts/prepare_knowledge_base.py
"""

from __future__ import annotations

from genai_security_assistant.ingestion.pipeline import build_knowledge_base


def main() -> None:
    result = build_knowledge_base()
    print("=" * 70)
    print("KNOWLEDGE BASE BUILD")
    print("=" * 70)
    print(f"Sources in manifest : {result['sources']}")
    print(f"Normalized documents: {result['documents']} -> {result['normalized_path']}")
    print(f"Chunks              : {result['chunks']} -> {result['chunks_path']}")


if __name__ == "__main__":
    main()
