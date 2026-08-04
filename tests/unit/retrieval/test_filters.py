"""Unit tests for the chunk filters."""

from __future__ import annotations

import pytest

from genai_security_assistant.models.documents import (
    Chunk,
    ChunkMetadata,
    DocumentType,
    RiskCategory,
)
from genai_security_assistant.retrieval.filters import (
    MetadataFilter,
    classify_sections,
    duplicate_chunk_ids,
    text_key,
)

REFERENCE_SECTIONS = ["Reference Links", "References"]


def build_filter(raw: dict[str, str | list[str]]) -> MetadataFilter:
    """from_config returns None for an empty block; no test below wants that."""
    metadata_filter = MetadataFilter.from_config(raw)
    assert metadata_filter is not None
    return metadata_filter

def make_chunk(
    document_id: str,
    text: str,
    section: str = "Body",
    index: int = 0,
    document_type: DocumentType = "security_risk",
    risk_category: RiskCategory | None = None,
) -> Chunk:
    """A chunk carrying only the fields the filters look at."""
    return Chunk(
        chunk_id=f"{document_id}_chunk_{index:03d}",
        text=text,
        metadata=ChunkMetadata(
            document_id=document_id,
            source_file=f"data/raw/{document_id}.html",
            source_type="html",
            source_url=f"https://example.test/{document_id}",
            title=document_id,
            section=section,
            chunk_index=index,
            language="en",
            domain="genai_security",
            document_type=document_type,
            risk_category=risk_category,
            publisher="test",
        ),
    )


def test_a_single_section_name_is_not_read_as_a_list_of_letters():
    """A string is iterable, so this typo would otherwise pass in silence."""
    chunk = make_chunk("llm01", "titles and urls", section="R")
    assert classify_sections([chunk], "Reference Links") == {
        chunk.chunk_id: "body"
    }
    
def test_layout_differences_do_not_make_two_texts_different():
    """The same paragraph from a PDF and from HTML has to compare equal."""
    assert text_key("One  two\nthree") == text_key("one two three")


def test_the_same_text_in_two_documents_is_a_duplicate():
    chunks = [
        make_chunk("llm01", "shared summary", index=1),
        make_chunk("llm02", "shared summary", index=1),
    ]
    assert duplicate_chunk_ids(chunks) == {
        "llm01_chunk_001",
        "llm02_chunk_001",
    }


def test_every_copy_is_dropped_rather_than_all_but_one():
    """There is no reason to prefer the page a copy happens to sit on."""
    chunks = [make_chunk(f"doc{n}", "shared summary", index=1) for n in range(3)]
    assert len(duplicate_chunk_ids(chunks)) == 3


def test_a_document_repeating_itself_is_left_alone():
    chunks = [
        make_chunk("llm01", "same words", index=1),
        make_chunk("llm01", "same words", index=2),
    ]
    assert duplicate_chunk_ids(chunks) == set()


def test_reference_sections_are_matched_by_exact_name():
    """"2. Reference ... Best Practices" is real guidance, not a link list."""
    listed = make_chunk("llm01", "titles and urls", section="Reference Links")
    trap = make_chunk(
        "llm02",
        "real guidance",
        section="2. Reference Security Misconfiguration Best Practices",
    )

    types = classify_sections([listed, trap], REFERENCE_SECTIONS)

    assert types[listed.chunk_id] == "reference_links"
    assert types[trap.chunk_id] == "body"


def test_a_duplicated_link_list_is_reported_as_a_duplicate():
    """Both labels fit; the computed one wins, because it is the stronger claim."""
    chunks = [
        make_chunk("llm01", "same titles", section="Reference Links"),
        make_chunk("llm02", "same titles", section="Reference Links"),
    ]
    types = classify_sections(chunks, REFERENCE_SECTIONS)
    assert set(types.values()) == {"duplicate"}


def test_ordinary_chunks_stay_searchable():
    chunk = make_chunk("llm01", "how to prevent it", section="Prevention")
    assert classify_sections([chunk], REFERENCE_SECTIONS) == {
        chunk.chunk_id: "body"
    }


def test_a_query_without_a_filter_block_gets_no_filter():
    assert MetadataFilter.from_config(None) is None
    assert MetadataFilter.from_config({}) is None


def test_a_filter_accepts_one_value_or_several():
    one = build_filter({"document_type": "checklist"})
    several = build_filter({"document_type": ["checklist", "cheat_sheet"]})
    checklist = make_chunk("c", "t", document_type="checklist").metadata
    risk = make_chunk("r", "t", document_type="security_risk").metadata

    assert one.matches(checklist)
    assert not one.matches(risk)
    assert several.matches(checklist)


def test_all_conditions_have_to_hold_at_once():
    metadata_filter = build_filter(
        {"document_type": "security_risk", "risk_category": "prompt_injection"}
    )
    right = make_chunk(
        "a", "t", risk_category="prompt_injection"
    ).metadata
    wrong_category = make_chunk(
        "b", "t", risk_category="excessive_agency"
    ).metadata

    assert metadata_filter.matches(right)
    assert not metadata_filter.matches(wrong_category)


def test_a_chunk_missing_the_field_never_matches():
    """risk_category is optional, and absent is not the same as allowed."""
    metadata_filter = build_filter({"risk_category": "governance"})
    assert not metadata_filter.matches(make_chunk("a", "t").metadata)


def test_filtering_on_a_field_chunks_do_not_have_is_refused():
    with pytest.raises(ValueError, match="no such field"):
        MetadataFilter.from_config({"document_typ": "checklist"})


def test_describe_reads_as_one_line():
    metadata_filter = build_filter(
        {"document_type": ["checklist", "cheat_sheet"]}
    )
    assert metadata_filter.describe() == "document_type=cheat_sheet|checklist"