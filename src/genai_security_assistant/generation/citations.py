"""Reading the sources out of an answer, and checking they are real.
Prompt v3 asks for [chunk_id] in square brackets. That format exists so
this file can check it. A citation written in prose - "according to the
prompt injection document" - reads fine and can't be verified against
anything.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from genai_security_assistant.models.generation import Citation
from genai_security_assistant.models.retrieval import RetrievedChunk

# Anything in square brackets. The model sometimes puts two ids in one
# pair, separated by a comma, and the earlier pattern required no spaces
# inside the brackets, so that whole citation vanished without a trace.
CITATION_PATTERN = re.compile(r"\[([^\[\]]+)\]")


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
