"""Build the vector index: data/processed/chunks.jsonl -> index/.
Run from the project root:
    uv run python scripts/build_index.py
"""

from __future__ import annotations

from genai_security_assistant.retrieval.indexing import build_index


def main() -> None:
    print("=" * 70)
    print("VECTOR INDEX BUILD")
    print("=" * 70)
    print("Encoding chunks, this may take some time...")

    result = build_index()

    print()
    print(f"Provider   : {result['provider']}")
    print(f"Model      : {result['model']}")
    print(f"Dimension  : {result['dimension']}")
    print(f"Documents  : {result['documents']}")
    print(f"Chunks     : {result['chunks']}")
    print()
    print(f"Index      : {result['index_path']} ({result['index_size_mb']:.2f} MB)")
    print(f"Metadata   : {result['meta_path']}")
    print(f"Chunks copy: {result['snapshot_path']}")


if __name__ == "__main__":
    main()
