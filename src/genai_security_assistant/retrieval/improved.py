"""The HW2 retriever with the HW3 improvements layered on top.
Composed rather than modified: SemanticRetriever still does exactly what it
did in HW2, so the baseline in outputs/retrieval_comparison.md is the real
earlier pipeline and not a special case of the newer code. Every difference
between the two columns of that table comes from this file.
"""

from __future__ import annotations

from collections.abc import Mapping

from genai_security_assistant.config import Settings
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.filters import (
    SEARCHABLE,
    MetadataFilter,
    SectionType,
    classify_sections,
)
from genai_security_assistant.retrieval.hybrid import HybridRetriever
from genai_security_assistant.retrieval.lexical import LexicalIndex
from genai_security_assistant.retrieval.search import BaseRetriever, SemanticRetriever


class ImprovedRetriever:
    """Semantic search, then drop what doesn't answer, then take the top k."""

    def __init__(
        self,
        base: BaseRetriever,
        section_types: Mapping[str, SectionType],
        candidate_multiplier: int,
        drop_boilerplate: bool,
    ) -> None:
        """from_settings builds parts from config.
        drop_boilerplate removes the sections filters.py classifies as
        copies or link lists - the chunks that answer nothing whatever the
        question was.
        """
        self.base = base
        self.section_types = section_types
        self.candidate_multiplier = candidate_multiplier
        self.drop_boilerplate = drop_boilerplate

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        drop_boilerplate: bool = True,
        use_hybrid: bool = False,
    ) -> ImprovedRetriever:
        settings = settings or Settings()
        base: BaseRetriever = SemanticRetriever.from_settings(settings)
        top_k = settings.retrieval.get("top_k", 5)
        multiplier = settings.retrieval.get("candidate_multiplier", 4)
        if use_hybrid:
            base = HybridRetriever(
                base=base,
                lexical=LexicalIndex(base.chunks),
                # Fusion reads as deep as filtering does, so both layers see
                # the same pool of candidates.
                depth=top_k * multiplier,
                rrf_k=settings.retrieval["rrf_k"],
            )
        # base.yaml is the only source for this list. A missing key has to
        # stop the run: silently switching the filter off would change every
        # figure in the report without saying so.
        reference_sections: list[str] = settings.retrieval["reference_sections"]
        return cls(
            base=base,
            section_types=classify_sections(base.chunks, reference_sections),
            candidate_multiplier=multiplier,
            drop_boilerplate=drop_boilerplate,
        )

    def keeps(
        self,
        result: RetrievedChunk,
        metadata_filter: MetadataFilter | None,
    ) -> bool:
        """Whether one result survives both filters."""
        if self.drop_boilerplate and self.section_types[result.chunk_id] != SEARCHABLE:
            return False
        return metadata_filter is None or metadata_filter.matches(result.metadata)

    def survivors(
        self,
        results: list[RetrievedChunk],
        metadata_filter: MetadataFilter | None,
    ) -> list[RetrievedChunk]:
        return [r for r in results if self.keeps(r, metadata_filter)]

    def search(
        self,
        query: str,
        top_k: int | None = None,
        metadata_filter: MetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        """Return the top k results that survive filtering, ranked from 1."""
        k = top_k or self.base.default_top_k
        corpus = len(self.base.chunks)

        # Filtering can only remove what the search already returned, so ask
        # for more than k and cut down afterwards. The multiplier is a guess
        # at how much will be dropped.
        wanted = min(k * self.candidate_multiplier, corpus)
        kept = self.survivors(self.base.search(query, top_k=wanted), metadata_filter)

        if len(kept) < k and wanted < corpus:
            # The guess was too low. Widening to the whole index costs one
            # more pass over the vectors already in memory and no API call,
            # since the query vector is cached - cheaper than returning a
            # short list and leaving the reader to wonder why.
            kept = self.survivors(
                self.base.search(query, top_k=corpus), metadata_filter
            )

        return [
            result.model_copy(update={"rank": rank})
            for rank, result in enumerate(kept[:k], start=1)
        ]
