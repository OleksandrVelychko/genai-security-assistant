"""Relevance labels: which chunks count as a correct answer to which query.

Retrieval quality cannot be measured without deciding, in advance, what a
good answer looks like. configs/eval_queries.yaml holds that decision: for
every test query it lists the document sections that answer it, and how
well they answer it. This module reads that file, applies those labels to
retrieved chunks, and refuses to run if a label points at a section that
does not exist in the knowledge base.

The refusal matters more than it looks. A misspelled section name raises
no error by itself - the label simply never matches, the chunk it was
meant to mark scores zero, and every metric comes out too low with nothing
to explain why. validate() turns that silent drift into a loud failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from genai_security_assistant.models.documents import Chunk, ChunkMetadata

# How well a chunk answers a query:
#   0 - not about the question
#   1 - right topic, but contains no actual answer (background, link lists)
#   2 - this is the answer
# Declared as a Literal so that a typo like grade: 3 is rejected while the
# YAML file is being read, not later while metrics are being computed.
Grade = Literal[0, 1, 2]


class LabelRule(BaseModel):
    """One judgement about how well some chunks answer a query.
    Leaving out `section` makes the rule cover the whole document, which is
    how a query says that everything in it is at least on topic.
    """

    document_id: str
    section: str | None = None
    grade: Grade


class SectionRef(BaseModel):
    """Points at sections that are worthless for every query, not just one.
    Written two ways in the YAML file - one `section` per entry, or a list
    of `sections` - because link lists come one at a time while the OWASP
    cross-reference footers come in groups. Both forms end up the same.
    """

    document_id: str
    section: str | None = None
    sections: list[str] = Field(default_factory=list)

    def pairs(self) -> list[tuple[str, str]]:
        """Flatten either form into (document_id, section) pairs."""
        names = list(self.sections)
        if self.section is not None:
            names.append(self.section)
        return [(self.document_id, name) for name in names]


class QueryLabels(BaseModel):
    """One test query together with the judgements about its answers.
    `expected_docs`, `note` and `comment` are carried over from HW2 and are
    still used by scripts/run_retrieval_examples.py. `relevant` and
    `abstain` are new: they are what the metrics actually read.
    """

    id: str
    query: str
    expected_docs: list[str] = Field(default_factory=list)
    metadata_filter: dict[str, str | list[str]] | None = None
    relevant: list[LabelRule] = Field(default_factory=list)
    abstain: bool = False
    note: str | None = None
    comment: str | None = None


class LabelSet:
    """Everything in configs/eval_queries.yaml, ready to be asked questions.
    A plain class rather than a Pydantic model, because it holds a lookup
    set assembled from two separate parts of the file - a shape that has no
    direct equivalent in the YAML. Parsing stays in the models above.
    """

    def __init__(
        self,
        queries: list[QueryLabels],
        always_irrelevant: set[tuple[str, str]],
    ) -> None:
        self.queries = queries
        self.always_irrelevant = always_irrelevant

    @classmethod
    def load(cls, path: Path) -> LabelSet:
        """Read the YAML file into validated objects."""
        if not path.exists():
            raise FileNotFoundError(f"{path} not found.")

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        queries = [
            QueryLabels.model_validate(item)
            for item in raw.get("queries", [])
        ]
        if not queries:
            raise ValueError(
                f"{path} declares no queries. Check that the top-level "
                "'queries:' key is present and not indented."
            )

        # Two kinds of worthless section, kept apart in the file because they
        # are worthless for different reasons - one is a bare list of links,
        # the other is a stub about a different risk copied onto every page.
        # Scoring treats them identically, so they merge into one lookup.
        always_irrelevant: set[tuple[str, str]] = set()
        for block in ("noise_sections", "cross_reference_sections"):
            for entry in raw.get(block, []):
                always_irrelevant.update(
                    SectionRef.model_validate(entry).pairs()
                )

        return cls(queries=queries, always_irrelevant=always_irrelevant)

    def grade_of(self, metadata: ChunkMetadata, labels: QueryLabels) -> int:
        """Decide how well one retrieved chunk answers one query.
        Several labels can apply to the same chunk at once: one naming its
        exact section, another covering its whole document. The narrower
        statement always wins, the way a rule about one street overrides a
        rule about the whole city.
        """
        key = (metadata.document_id, metadata.section)

        # Narrowest: this query has an opinion about this exact section.
        for rule in labels.relevant:
            if rule.section is not None and (rule.document_id, rule.section) == key:
                return rule.grade

        # Sections that answer nothing, no matter what was asked. Checked
        # before the document-wide label below on purpose: without this, a
        # "Reference Links" chunk would inherit "on topic" from the document
        # around it, and a bare list of article titles would score as useful.
        if key in self.always_irrelevant:
            return 0

        # Widest: the query says something about the document as a whole.
        for rule in labels.relevant:
            if rule.section is None and rule.document_id == metadata.document_id:
                return rule.grade

        # This query never mentions the chunk, so it answers nothing.
        return 0

    def validate(self, chunks: list[Chunk]) -> None:
        """Refuse to run when a label points at something that is not there.
        Serves the same purpose as IndexMeta.assert_compatible() in HW2:
        both catch a mistake that would otherwise produce plausible-looking
        numbers instead of an error.
        """
        known_documents = {c.metadata.document_id for c in chunks}
        known_sections = {
            (c.metadata.document_id, c.metadata.section) for c in chunks
        }
        problems: list[str] = []

        for document_id, section in sorted(self.always_irrelevant):
            if (document_id, section) not in known_sections:
                problems.append(
                    f"always-irrelevant {document_id} / {section!r} "
                    "matches no chunk"
                )

        for query in self.queries:
            for rule in query.relevant:
                if rule.section is None:
                    if rule.document_id not in known_documents:
                        problems.append(
                            f"{query.id}: no document called "
                            f"{rule.document_id!r}"
                        )
                elif (rule.document_id, rule.section) not in known_sections:
                    problems.append(
                        f"{query.id}: {rule.document_id} has no section "
                        f"{rule.section!r}"
                    )

            # A query with no grade-2 label has no ideal answer to look for,
            # which leaves the strictest measurements undefined for it.
            if not query.abstain and not any(r.grade == 2 for r in query.relevant):
                problems.append(f"{query.id}: no chunk is labelled as the answer")

        # Every problem is collected before raising, rather than failing on
        # the first one: whole list of mistakes arrives at once
        # to correct hand-written labels faster.
        if problems:
            raise ValueError(
                "Label validation failed:\n  - " + "\n  - ".join(problems)
            )