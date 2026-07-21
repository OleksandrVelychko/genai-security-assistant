"""Semantic search over the knowledge base index.
Run from the project root:
    uv run python scripts/retrieval.py --query "How do I prevent prompt injection?"
    uv run python scripts/retrieval.py --query "excessive agency" --top-k 3
"""

from __future__ import annotations

import argparse

from genai_security_assistant.config import Settings
from genai_security_assistant.retrieval.search import SemanticRetriever


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Top-k semantic search over the GenAI security knowledge base."
    )
    parser.add_argument(
        "--query",
        "-q",
        required=True,
        help="User question to search for.",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=None,
        help="Number of chunks to return (defaults to configs/base.yaml).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings()
    preview_chars = settings.retrieval.get("preview_chars", 300)

    retriever = SemanticRetriever.from_settings(settings)
    results = retriever.search(args.query, top_k=args.top_k)

    print("=" * 78)
    print(f"Query: {args.query}")
    print(f"Model: {retriever.store.meta.provider}/{retriever.store.meta.model}")
    print("=" * 78)

    if not results:
        print("No results.")
        return

    for result in results:
        meta = result.metadata
        print()
        print(f"Top-{result.rank}: {result.chunk_id} | score: {result.score:.4f}")
        print(f"  Source: {meta.source_file}")
        print(f"  Document: {meta.document_id} | Section: {meta.section or '-'}")
        print(f"  Text: {result.preview(preview_chars)}")


if __name__ == "__main__":
    main()