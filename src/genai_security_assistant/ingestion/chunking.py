"""Structure-aware chunking: split normalized documents into readable chunks.
Unlike naive fixed-width slicing, this never cuts a word or a sentence, and
never mixes two document sections into one chunk.
"""

from __future__ import annotations

import re

from genai_security_assistant.ingestion.metadata import build_chunk_id, build_chunk_metadata
from genai_security_assistant.models.documents import Chunk, NormalizedDocument, NormalizedSection

_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

_FENCE_RE = re.compile(r"^\s*```")


def split_blocks(text: str) -> list[str]:
    """Split section text into blocks, keeping fenced code blocks atomic.

    A code example is useless once split across chunks, so everything between
    ``` fences is emitted as a single block.
    """
    blocks: list[str] = []
    fence: list[str] | None = None

    for line in text.split("\n"):
        if _FENCE_RE.match(line):
            if fence is None:
                fence = [line]
            else:
                fence.append(line)
                blocks.append("\n".join(fence))
                fence = None
            continue
        if fence is not None:
            fence.append(line)
        elif line.strip():
            blocks.append(line.strip())

    if fence:  # unterminated fence - keep what we collected
        blocks.append("\n".join(fence))

    return blocks



def split_sentences(text: str) -> list[str]:
    """Split a block into sentences, keeping terminators attached."""
    return [part.strip() for part in _SENTENCE_RE.split(text) if part.strip()]


def force_split(text: str, chunk_size: int) -> list[str]:
    """Last resort for an over-long sentence: split on word boundaries."""
    parts: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > chunk_size and current:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def build_overlap(text: str, overlap: int) -> str:
    """Take the last complete sentences of `text`, up to `overlap` characters.

    If even the final sentence is longer than `overlap`, fall back to its last
    words, so carried context never blows past the budget.
    """
    if overlap <= 0:
        return ""
    sentences = split_sentences(text)
    if not sentences:
        return ""

    tail: list[str] = []
    length = 0
    for sentence in reversed(sentences):
        if tail and length + len(sentence) > overlap:
            break
        tail.insert(0, sentence)
        length += len(sentence) + 1

    carry = " ".join(tail)
    if len(carry) <= overlap:
        return carry

    # A single over-long sentence: keep only its trailing words.
    trimmed: list[str] = []
    size = 0
    for word in reversed(carry.split()):
        if trimmed and size + len(word) + 1 > overlap:
            break
        trimmed.insert(0, word)
        size += len(word) + 1
    return " ".join(trimmed)


def force_split_lines(text: str, chunk_size: int) -> list[str]:
    """Split an over-long code block on line boundaries, never mid-line."""
    parts: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.split("\n"):
        if current and size + len(line) + 1 > chunk_size:
            parts.append("\n".join(current))
            current = []
            size = 0
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return parts

def chunk_section_text(
    text: str,
    chunk_size: int,
    overlap: int,
    min_chunk_size: int,
) -> list[str]:
    """Chunk the text of a single section, respecting natural boundaries."""
    units: list[str] = []
    for block in split_blocks(text):
        if len(block) <= chunk_size:
            units.append(block)
            continue
        if block.lstrip().startswith("```"):
            units.extend(force_split_lines(block, chunk_size))
            continue
        for sentence in split_sentences(block):
            if len(sentence) <= chunk_size:
                units.append(sentence)
            else:
                units.extend(force_split(sentence, chunk_size))

    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n{unit}".strip() if current else unit
        if not current or len(candidate) <= chunk_size or len(current) < min_chunk_size:
            current = candidate
        else:
            chunks.append(current)
            carry = build_overlap(current, overlap)
            current = f"{carry}\n{unit}".strip() if carry else unit
    if current:
        chunks.append(current)

    # A tiny trailing fragment reads poorly on its own - fold it back.
    if len(chunks) > 1 and len(chunks[-1]) < min_chunk_size:
        chunks[-2] = f"{chunks[-2]}\n{chunks[-1]}".strip()
        chunks.pop()

    return chunks


def coalesce_sections(
    sections: list[NormalizedSection],
    min_chunk_size: int,
) -> list[NormalizedSection]:
    """Merge undersized sections forward, keeping the earlier heading.

    A heading followed by a single lead-in line ("The following actions can
    prevent Excessive Agency:") belongs with the content after it, not alone.
    """
    merged: list[NormalizedSection] = []
    pending: NormalizedSection | None = None

    for section in sections:
        if pending is not None:
            pending = pending.model_copy(
                update={"text": f"{pending.text}\n{section.text}".strip()}
            )
            if len(pending.text) >= min_chunk_size:
                merged.append(pending)
                pending = None
            continue
        if len(section.text) < min_chunk_size:
            pending = section
            continue
        merged.append(section)

    if pending is not None:
        if merged:
            merged[-1] = merged[-1].model_copy(
                update={"text": f"{merged[-1].text}\n{pending.text}".strip()}
            )
        else:
            merged.append(pending)

    return merged


def chunk_document(
    document: NormalizedDocument,
    chunk_size: int,
    overlap: int,
    min_chunk_size: int,
) -> list[Chunk]:
    """Split one normalized document into metadata-rich chunks."""
    chunks: list[Chunk] = []
    index = 0

    for section in coalesce_sections(document.sections, min_chunk_size):
        for text in chunk_section_text(section.text, chunk_size, overlap, min_chunk_size):
            index += 1
            chunks.append(
                Chunk(
                    chunk_id=build_chunk_id(document.document_id, index),
                    text=text,
                    metadata=build_chunk_metadata(document, section, index),
                )
            )

    return chunks