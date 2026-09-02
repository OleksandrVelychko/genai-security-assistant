"""Data contracts for the answer-generation layer (HW4).
Same idea as models/retrieval.py: types are declared here, the
generation package fills them in.
Three contracts:
  AnswerStatus   - answered, or which of the two ways the pipeline refused
  Citation       - one source the answer points at, resolved to a chunk
  GroundedAnswer - everything one question produced
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from genai_security_assistant.models.retrieval import RetrievedChunk

# How the pipeline ended up, in three cases:
#   answered            - the model answered
#   abstained_by_gate   - score too low, LLM was never called
#   abstained_by_model  - LLM saw the context and said it was not enough
#
# The last two are separate because they fail on different questions.
# q9 ("how do I make sourdough bread") scores 0.13 and the gate catches it.
# q10 scores 0.5952 and the gate lets it through, so only the prompt rule
# stops the model from inventing an answer.
AnswerStatus = Literal["answered", "abstained_by_gate", "abstained_by_model"]

# Where the citations of an answered question ended up. Separate from
# AnswerStatus, which says whether the pipeline answered at all: an
# answer can be complete and still be hard to verify, and folding the two
# together would make abstained and is_grounded read a value that has
# nothing to do with either.
#
#   compliant      - every sentence carried its own citation on the first try
#   repaired       - a repair earned its place and replaced the first answer
#   unrepaired     - a repair was refused; what comes back is the first answer
#   not_applicable - an abstention cites nothing, so nothing is placed
CitationPlacement = Literal[
    "compliant", "repaired", "unrepaired", "not_applicable"
]


class Citation(BaseModel):
    """One source the answer points at.
    Always built from a chunk that was actually retrieved. If the model
    writes a chunk_id nobody gave it, there is no source_file or section
    to fill in - those ids go to GroundedAnswer.unsupported_citations as
    plain strings instead.
    """

    chunk_id: str
    document_id: str
    source_file: str
    section: str | None = None
    rank: int = Field(ge=1)
    score: float

    @classmethod
    def from_chunk(cls, chunk: RetrievedChunk) -> Citation:
        """Copy out the fields a citation needs to print."""
        return cls(
            chunk_id=chunk.chunk_id,
            document_id=chunk.metadata.document_id,
            source_file=chunk.metadata.source_file,
            section=chunk.metadata.section,
            rank=chunk.rank,
            score=chunk.score,
        )


class GroundedAnswer(BaseModel):
    """Everything one question produced: the answer plus its receipts.
    Keeps the retrieved chunks next to the answer, because checking
    whether an answer is grounded means seeing what the model was given.

    Nothing here raises on a bad answer. An answer with no citation is
    what prompt v1 is expected to produce, and that has to be measurable,
    not a crash. is_grounded reports the verdict.
    """

    question: str
    answer_text: str
    status: AnswerStatus
    prompt_version: str
    model: str
    citations: list[Citation] = Field(default_factory=list)
    unsupported_citations: list[str] = Field(default_factory=list)
    retrieved: list[RetrievedChunk] = Field(default_factory=list)
    # Over every call this answer cost, not only the first: a replayed
    # answer whose citation repair went out reads False.
    from_cache: bool = False
    citation_placement: CitationPlacement = "not_applicable"
    # Bounded at two by the pipeline: one answer, at most one repair.
    generation_attempts: int = Field(default=1, ge=1)
    # Why a repair was not taken. Absent when none was needed or when one
    # was accepted. A refusal nobody can read is not better than a silent
    # one, which is the whole reason this field exists rather than a bool.
    repair_note: str | None = None
    # Sentences in answer_text that do not end with a citation. Stored
    # rather than recomputed by the report: a later edit to SENTENCE_BREAK
    # would otherwise re-judge a finished run and quietly move its numbers.
    uncited_count: int = 0
    # The same count in the model's first answer. Equal to uncited_count
    # wherever no repair was taken, and the pair is what the before/after
    # table in FINAL_IMPROVEMENT.md is read from: one run carries both
    # columns, so nobody has to argue that two runs were otherwise equal.
    uncited_before_repair: int = 0

    @property
    def abstained(self) -> bool:
        return self.status != "answered"

    @property
    def best_score(self) -> float | None:
        """Highest score among the retrieved chunks.
        max(), not retrieved[0].score: hybrid mode reorders the list by
        RRF while the scores stay cosine, so the first chunk isn't
        always the closest one. metrics.py does the same, which keeps
        this number comparable with the HW3 margin.
        """
        if not self.retrieved:
            return None
        return max(chunk.score for chunk in self.retrieved)

    @property
    def retrieved_ids(self) -> list[str]:
        return [chunk.chunk_id for chunk in self.retrieved]

    @property
    def sources(self) -> list[str]:
        """Source files behind the citations, no repeats, in citation order.
        dict.fromkeys, not set(): several citations often share a document,
        and the report should list it once, in the order it was cited.
        """
        return list(dict.fromkeys(citation.source_file for citation in self.citations))

    @property
    def is_grounded(self) -> bool:
        """Answered, cited something real, invented nothing.
        An abstention is neither grounded nor ungrounded - it is a refusal,
        and status already says that.
        """
        return (
            self.status == "answered"
            and bool(self.citations)
            and not self.unsupported_citations
        )

    @property
    def citations_placed(self) -> bool:
        """Answered, and every sentence carries its own citation.
        Reads the count and not citation_placement: a repair is taken
        when it leaves fewer sentences uncited, which is not the same as
        leaving none.
        """
        return self.status == "answered" and self.uncited_count == 0
