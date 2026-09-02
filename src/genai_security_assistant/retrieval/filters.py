"""Deciding which chunks are worth searching at all.

Two kinds of chunk answer nothing, whatever the question was.
The first is boilerplate. Each OWASP risk page ends with short summaries of
the other risks, and the same summary is copied onto several pages word for
word. The knowledge base therefore holds fifteen chunks that are five
paragraphs repeated three times each. Semantic search likes them: they read
like clean definitions, so they score well and crowd out the pages that
actually answer the question. This is what pushed the real answer out of the
top five for q7, and what made q10 - a question the corpus cannot answer -
score as high as questions it can.

The second is link lists. "Reference Links" and its neighbors hold article
titles and URLs. They are on topic and contain nothing.

The two are found differently, and the difference is worth keeping. A
duplicate can be recognized from the data alone: the same text in two
documents is a copy, and no judgement is needed to say so. A link list
can't - its text is unique, and only a reader can tell that a list of
titles is not an answer. So duplicates are computed and link lists are
listed by name in configs/base.yaml, and the code does not pretend the
second kind is as automatic as the first.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from genai_security_assistant.models.documents import Chunk, ChunkMetadata

SectionType = Literal["body", "duplicate", "reference_links"]

# Only body chunks are searched. The other two are the subject of this file.
SEARCHABLE: SectionType = "body"


def text_key(text: str) -> str:
    """A comparison key for chunk text that ignores layout.
    Line breaks and capitalization differ between an HTML page and a PDF of
    the same paragraph, and neither difference changes what the text says.
    """
    normalised = " ".join(text.split()).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def duplicate_chunk_ids(chunks: Iterable[Chunk]) -> set[str]:
    """Chunks whose text appears word for word in more than one document.
    Repetition inside one document is left alone: a page may legitimately
    restate itself, and dropping part of a document because of how it was
    written is not this filter's business. Across documents the same text
    is a copy, and every copy is dropped rather than one kept, because
    there is no reason to prefer the page it happens to sit on.
    """
    by_text: dict[str, list[Chunk]] = defaultdict(list)
    for chunk in chunks:
        by_text[text_key(chunk.text)].append(chunk)

    duplicates: set[str] = set()
    for group in by_text.values():
        documents = {chunk.metadata.document_id for chunk in group}
        if len(documents) > 1:
            duplicates.update(chunk.chunk_id for chunk in group)
    return duplicates


def classify_sections(
    chunks: Sequence[Chunk],
    reference_sections: str | Iterable[str],
) -> dict[str, SectionType]:
    """Give every chunk one of the three section types, by chunk id."""
    duplicates = duplicate_chunk_ids(chunks)
    # A single name in the config is a list of one, not a list of letters.
    listed = (
        {reference_sections}
        if isinstance(reference_sections, str)
        else set(reference_sections)
    )

    types: dict[str, SectionType] = {}
    for chunk in chunks:
        if chunk.chunk_id in duplicates:
            types[chunk.chunk_id] = "duplicate"
        elif chunk.metadata.section in listed:
            types[chunk.chunk_id] = "reference_links"
        else:
            types[chunk.chunk_id] = SEARCHABLE
    return types


@dataclass(frozen=True)
class MetadataFilter:
    """Conditions a chunk has to satisfy to be worth returning.
    Built from the 'filter:' block of a query in configs/eval_queries.yaml,
    where each entry names a metadata field and the values allowed for it.
    All conditions have to hold at once.
    """

    conditions: Mapping[str, frozenset[str]]

    @classmethod
    def from_config(
        cls,
        raw: Mapping[str, str | Sequence[str]] | None,
    ) -> MetadataFilter | None:
        """Read a 'filter:' block, or return None when a query has none."""
        if not raw:
            return None

        conditions: dict[str, frozenset[str]] = {}
        for field, value in raw.items():
            if field not in ChunkMetadata.model_fields:
                raise ValueError(
                    f"Cannot filter on {field!r}: chunks have no such field. "
                    f"Available: {', '.join(sorted(ChunkMetadata.model_fields))}"
                )
            values = [value] if isinstance(value, str) else list(value)
            conditions[field] = frozenset(str(item) for item in values)
        return cls(conditions=conditions)

    def matches(self, metadata: ChunkMetadata) -> bool:
        """True when every condition holds for this chunk."""
        for field, allowed in self.conditions.items():
            value = getattr(metadata, field)
            if value is None or str(value) not in allowed:
                return False
        return True

    def describe(self) -> str:
        """The filter as one line, for the comparison report."""
        return ", ".join(
            f"{field}={'|'.join(sorted(allowed))}"
            for field, allowed in sorted(self.conditions.items())
        )
