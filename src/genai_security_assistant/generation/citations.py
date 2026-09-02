"""Reading the sources out of an answer, and checking them.
Prompt v3 asks for [chunk_id] in square brackets after the sentence that
used it. That format exists so this file can check it, and there are two
things to check: whether an id resolves to a chunk the answer was given,
and whether it sits on the sentence it supports. A citation written in
prose - "according to the prompt injection document" - fails both and
can't be verified against anything.

rejection_reason() judges a repair rather than an answer: it decides
whether a second model call is allowed to replace the first.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Sequence

from genai_security_assistant.models.generation import Citation
from genai_security_assistant.models.retrieval import RetrievedChunk

# Anything in square brackets. The model sometimes puts two ids in one
# pair, separated by a comma, and the earlier pattern required no spaces
# inside the brackets, so that whole citation vanished without a trace.
CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")
# Sentence boundaries, without a sentence splitter in the dependency
# tree. Terminal punctuation, whitespace, then an opening character:
# "1.2.9" and "nvd@nist.gov" keep their periods because no space follows
# them. An abbreviation before a capitalised word - "U.S. Government" -
# would split, and none appears in this corpus.
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\"'\[])")

# One citation with the space in front of it, so that removing it leaves
# "approved." rather than "approved ." and two answers differing only in
# where the citations sit compare equal. The group is what decides
# whether the bracket is a citation at all.
CITATION_MARKER = re.compile(r"\s*\[([^\[\]]+)\]")

# The last bracket of a sentence, for the placement check.
TRAILING_BRACKET = re.compile(r"\[([^\[\]]+)\]$")


def extract_citation_ids(answer_text: str) -> list[str]:
    """Every bracketed id, in the order it appears, without repeats.
    A bracket may hold several ids separated by commas. Parts containing
    a space are dropped: those are prose in brackets, not an attempt at a
    citation. A single odd word like [1] is kept, because a reader can't
    check that one either,and it belongs in the unsupported list.
    """
    ids: list[str] = []
    for group in CITATION_PATTERN.findall(answer_text):
        for part in group.split(","):
            part = part.strip()
            if part and " " not in part:
                ids.append(part)
    return list(dict.fromkeys(ids))


def split_citations(
    answer_text: str,
    retrieved: Sequence[RetrievedChunk],
) -> tuple[list[Citation], list[str]]:
    """Sort the cited ids into real ones and invented ones.
    Real means the id was among the chunks this answer was given. An id
    from elsewhere in the corpus counts as invented too: the model did not
    read that chunk, so it can't be the source.
    """
    by_id = {chunk.chunk_id: chunk for chunk in retrieved}

    real: list[Citation] = []
    invented: list[str] = []
    for chunk_id in extract_citation_ids(answer_text):
        chunk = by_id.get(chunk_id)
        if chunk is None:
            invented.append(chunk_id)
        else:
            real.append(Citation.from_chunk(chunk))
    return real, invented


def bare_mentions(
    answer_text: str,
    retrieved: Sequence[RetrievedChunk],
) -> list[str]:
    """Chunk ids named in the text but not put in brackets.
    Not used by the pipeline. It answers one question for the report: when
    an answer has no citations, did the model ignore the rule, or did it
    name the source in a format the code can't read? Prompt v2 asks the
    model to "mention the chunk id" without saying how, and this is how
    that difference gets measured instead of guessed.
    """
    bracketed = set(extract_citation_ids(answer_text))
    return [
        chunk.chunk_id
        for chunk in retrieved
        if chunk.chunk_id in answer_text and chunk.chunk_id not in bracketed
    ]


def sentences(answer_text: str) -> list[str]:
    """Split an answer into sentences, one per returned string."""
    parts = SENTENCE_BREAK.split(answer_text.strip())
    return [part.strip() for part in parts if part.strip()]


def _cites(group: str, known: Collection[str]) -> bool:
    """Whether one bracket points at a chunk the answer was given.
    A bracket alone is not a citation. This corpus writes ranges as
    "[0,1]" and prose ends "[above]", and reading either as a source
    would report a sentence as cited when nothing cited it.
    """
    return any(part.strip() in known for part in group.split(","))


def ends_with_citation(sentence: str, known: Collection[str]) -> bool:
    """Say whether a sentence closes with a citation to a retrieved chunk.
    Trailing punctuation is stripped first: the model writes
    "...from an LLM [chunk_003]." with the period outside the bracket,
    and that is the format prompt v3 asks for.
    """
    trimmed = sentence.rstrip().rstrip(".!?\"')")
    match = TRAILING_BRACKET.search(trimmed)
    return match is not None and _cites(match.group(1), known)


def uncited_sentences(answer_text: str, known: Collection[str]) -> list[int]:
    """Positions of the sentences that do not end with a citation.
    Positions rather than a count, so a report can name the sentence
    instead of only saying how many were wrong.
    """
    return [
        number
        for number, sentence in enumerate(sentences(answer_text), start=1)
        if not ends_with_citation(sentence, known)
    ]


def claims(answer_text: str, known: Collection[str]) -> list[str]:
    """The sentences of an answer with every citation removed.
    This is what a citation repair must leave untouched. Brackets that
    cite nothing stay in: a repair that deleted "[0,1]" from a sentence
    changed what the sentence says, and stripping it here would hide
    exactly that.
    """

    def drop(match: re.Match[str]) -> str:
        return "" if _cites(match.group(1), known) else match.group(0)

    return [
        " ".join(CITATION_MARKER.sub(drop, sentence).split())
        for sentence in sentences(answer_text)
    ]


def rejection_reason(
    original: str,
    candidate: str,
    retrieved: Sequence[RetrievedChunk],
) -> str | None:
    """Why a repair must not replace the answer, or None to take it.
    Three ways a repair fails, in order of how bad they are, and two were
    produced by real runs: it cited an id nobody supplied, it rewrote the
    answer instead of the brackets, or it reformatted the citations
    without moving any of them onto a sentence.
    """
    known = {chunk.chunk_id for chunk in retrieved}

    # Checked first, not last. An invented id is also an unknown bracket,
    # so claims() leaves it in place and would report a rewrite instead.
    _, invented = split_citations(candidate, retrieved)
    if invented:
        return f"invented ids: {', '.join(invented)}"

    if claims(candidate, known) != claims(original, known):
        return "the claims changed"

    # Not "any uncited remain": a repair that fixes two of three
    # sentences is still worth taking, and citation_placement records
    # that the result is repaired rather than clean.
    if len(uncited_sentences(candidate, known)) >= len(
        uncited_sentences(original, known)
    ):
        return "no fewer uncited sentences"

    return None
