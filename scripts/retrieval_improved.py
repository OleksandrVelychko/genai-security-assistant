"""Search the knowledge base with the HW3 pipeline.
Run from the project root:

    uv run python scripts/retrieval_improved.py -q "How do I validate LLM output?"
    uv run python scripts/retrieval_improved.py -q "excessive agency" --mode baseline
    uv run python scripts/retrieval_improved.py -q "what to check before deploying" \
        --filter document_type=checklist

--mode selects how much of HW3 is switched on, so the same script prints
the before and the after. scripts/retrieval.py still runs plain HW2 search.

Modes
-----
baseline  Neither change. The same results scripts/retrieval.py gives, and
          the column everything else is measured against.
filtered  Drops the chunks that answer nothing whatever the question was:
          boilerplate copied word for word across pages, and lists of
          links. retrieval/filters.py explains how those are recognized.
hybrid    Adds BM25 keyword search and merges the two rankings by
          position. Finds sections whose wording matches the question even
          when their meaning did not rank highly, and gives up some
          precision at rank one in exchange. See retrieval/hybrid.py.
full      Both, and what outputs/retrieval_comparison.md reports as the
          improved pipeline.

Filtering by metadata
---------------------
--filter keeps only chunks whose metadata matches, and may be repeated to
require several conditions at once:

    --filter risk_category=prompt_injection --filter document_type=cheat_sheet

Any field of ChunkMetadata works: document_type, risk_category, language,
domain, source_file and the rest. A name that is not a field stops the run
and prints the ones that are.

Queries and the API key
-----------------------
The chunk vectors are committed in index/faiss.index, and the vectors for
the eleven test queries in configs/eval_queries.yaml are committed in
index/query_vectors.npz. Those eleven run with no network and no
credentials, which is what lets the reports be regenerated from a clone.


Any other question has no vector yet, so it goes to the embeddings API and
needs OPENAI_API_KEY in .env. Its answer is then written into the cache,
which means index/query_vectors.npz turns up as modified in git after an
afternoon of trying questions out. Throw those away with

    git checkout -- index/query_vectors.npz

unless the question is one being added to configs/eval_queries.yaml. The
stray entries break nothing, since lookups go by exact text, but the file
is meant to hold the test queries and nothing else.

Reading versus measuring
------------------------
This script prints one query at a time. The figures behind the report
come from scripts/run_metrics.py, which scores every query in every
configuration in one go.
"""

from __future__ import annotations

import argparse

from genai_security_assistant.config import Settings
from genai_security_assistant.retrieval.filters import MetadataFilter
from genai_security_assistant.retrieval.improved import ImprovedRetriever

# Everything HW3 added can be switched on separately, because the report
# has to show what each part did rather than only the finished pipeline.
MODES = {
    "baseline": {"drop_boilerplate": False, "use_hybrid": False},
    "filtered": {"drop_boilerplate": True, "use_hybrid": False},
    "hybrid": {"drop_boilerplate": False, "use_hybrid": True},
    "full": {"drop_boilerplate": True, "use_hybrid": True},
}


def parse_filter(pairs: list[str]) -> MetadataFilter | None:
    """Turn --filter field=value arguments into one filter."""
    conditions: dict[str, str | list[str]] = {}
    for pair in pairs:
        field, separator, value = pair.partition("=")
        if not separator or not value:
            raise SystemExit(
                f"--filter expects field=value, got {pair!r}. "
                "For example: --filter risk_category=prompt_injection"
            )
        conditions[field] = value
    return MetadataFilter.from_config(conditions)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Filtered and hybrid search over the GenAI security corpus."
    )
    parser.add_argument("--query", "-q", required=True, help="User question.")
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=None,
        help="Number of chunks to return (defaults to configs/base.yaml).",
    )
    parser.add_argument(
        "--mode",
        "-m",
        choices=sorted(MODES),
        default="full",
        help="How much of the HW3 pipeline to switch on (default: full).",
    )
    parser.add_argument(
        "--filter",
        "-f",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="Keep only chunks whose metadata matches. May be repeated.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings()
    preview_chars = settings.retrieval.get("preview_chars", 300)

    metadata_filter = parse_filter(args.filter)
    retriever = ImprovedRetriever.from_settings(settings, **MODES[args.mode])
    results = retriever.search(
        args.query, top_k=args.top_k, metadata_filter=metadata_filter
    )

    print("=" * 78)
    print(f"Query: {args.query}")
    print(f"Mode:  {args.mode}")
    print(f"Filter: {metadata_filter.describe() if metadata_filter else 'none'}")
    print("=" * 78)

    if not results:
        print("No results. The filter may be narrower than the corpus.")
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
