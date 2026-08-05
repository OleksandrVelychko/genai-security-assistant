"""Keyword search over the same chunks the vector index holds.

Semantic search matches meaning, which is what it is for, but it has no
special regard for the words themselves. q7 shows the cost: the section
called "Output Monitoring and Validation" repeats almost every word of the
question, and semantic search never returned it in any configuration.

BM25 is the other half of that trade. It scores a chunk by how many of the
query's words it contains, weighted so that rare words count for more and
long chunks are not rewarded for length alone. It knows nothing about
meaning and will miss a paraphrase entirely, which is why neither method
replaces the other.

Nothing here needs an API or a model, so it stays deterministic by
construction: the same chunks and the same query always give the same
ranking.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from rank_bm25 import BM25Okapi

from genai_security_assistant.models.documents import Chunk

WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Split text into the words BM25 counts.
    Lowercased, punctuation dropped, no stemming. Stemming was left out
    after checking that it changes nothing here: the one query where a
    plural meets a singular ("output formats" against "output format")
    matches on its other words anyway.
    """
    return WORD.findall(text.lower())


class LexicalIndex:
    """BM25 over the chunk texts, with their section headings prepended.
    The heading is included because it is the densest description a chunk
    has: "Output Monitoring and Validation" says more about what the chunk
    answers than any single sentence inside it.
    """

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunk_ids = [chunk.chunk_id for chunk in chunks]
        self.bm25 = BM25Okapi(
            [
                tokenize(f"{chunk.metadata.section or ''} {chunk.text}")
                for chunk in chunks
            ]
        )

    def rank(self, query: str, top_k: int) -> list[str]:
        """Chunk ids for the best keyword matches, best first."""
        if not query.strip():
            raise ValueError("Query is empty.")
        scores = self.bm25.get_scores(tokenize(query))
        # Chunks scoring zero share no word with the query, so this ranker
        # has no opinion about them. Leaving them in the list would still
        # hand them a position, and fusion pays for position.
        rows = [row for row in range(len(self.chunk_ids)) if scores[row] > 0]
        rows.sort(key=lambda row: -scores[row])
        return [self.chunk_ids[row] for row in rows[:top_k]]