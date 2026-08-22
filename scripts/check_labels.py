"""Validate the relevance labels against the indexed chunk snapshot.
Run from the project root:
    uv run python scripts/check_labels.py
"""

from __future__ import annotations

import collections

from genai_security_assistant.config import Settings
from genai_security_assistant.retrieval.indexing import load_chunks
from genai_security_assistant.retrieval.labels import LabelSet


def main() -> None:
    settings = Settings()

    chunks = load_chunks(settings.path("index_chunks"))
    labels = LabelSet.load(settings.path("eval_queries"))
    labels.validate(chunks)   # stops here if any label points nowhere

    print(f"OK  {len(chunks)} chunks, {len(labels.queries)} queries, "
          f"{len(labels.always_irrelevant)} always-irrelevant sections\n")

    for query in labels.queries:
        if query.abstain:
            print(f"  {query.id:<32} abstain (no relevant chunks expected)")
            continue

        graded = collections.Counter(
            labels.grade_of(chunk.metadata, query) for chunk in chunks
        )
        print(
            f"  {query.id:<32} grade2={graded[2]:>3}  "
            f"grade1={graded[1]:>3}  grade0={graded[0]:>3}"
        )


if __name__ == "__main__":
    main()
