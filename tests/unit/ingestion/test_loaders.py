"""Unit tests for format loaders and PDF text repair."""

from __future__ import annotations

from genai_security_assistant.ingestion.loaders.markdown import MarkdownLoader
from genai_security_assistant.ingestion.loaders.pdf import (
    is_table_of_contents,
    repair_pdf_text,
)
from genai_security_assistant.ingestion.metadata import build_chunk_id


def test_markdown_loader_tracks_heading_hierarchy(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text("# Top\nIntro.\n## Child\nBody.\n", encoding="utf-8")

    sections = MarkdownLoader().load(path)

    assert [section.heading_path for section in sections] == [["Top"], ["Top", "Child"]]
    assert sections[1].section == "Child"


def test_repair_recovers_fi_ligature():
    assert repair_pdf_text("arti\uffffcial") == "artificial"


def test_repair_drops_unrecoverable_digits():
    assert repair_pdf_text("\uffff.\uffff Overview") == ". Overview"


def test_table_of_contents_detected_by_dot_leaders():
    assert is_table_of_contents("Overview . . . . . . . . . . . . . . . 5")
    assert not is_table_of_contents("A normal paragraph of prose without leaders.")


def test_chunk_id_is_zero_padded():
    assert build_chunk_id("owasp_llm01", 1) == "owasp_llm01_chunk_001"
    assert build_chunk_id("owasp_llm01", 42) == "owasp_llm01_chunk_042"