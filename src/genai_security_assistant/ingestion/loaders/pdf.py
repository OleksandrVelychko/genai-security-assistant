"""PDF loader: extract text page by page, repairing broken font encoding."""

from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from genai_security_assistant.ingestion.loaders.base import BaseLoader
from genai_security_assistant.models.documents import NormalizedSection

# The embedded font has no ToUnicode map for ligature and some digit glyphs,
# so pdfminer emits U+FFFF. We recover what we can and drop what we cannot:
# lost digits in section numbers are unrecoverable.
_REPLACEMENT = "\uffff"

# Known 'fl' ligature words, fixed before the generic 'fi' rule below.
_FL_FIXES = [
    (re.compile(_REPLACEMENT + "aw"), "flaw"),
    (re.compile(_REPLACEMENT + "ow"), "flow"),
    (re.compile(_REPLACEMENT + "ex"), "flex"),
    (re.compile("con" + _REPLACEMENT + "ict"), "conflict"),
    (re.compile("in" + _REPLACEMENT + "uence"), "influence"),
    (re.compile("re" + _REPLACEMENT + "ect"), "reflect"),
]

# U+FFFF touching a letter is a lost 'fi' ligature (the dominant case here).
_FI_RE = re.compile(
    _REPLACEMENT + r"(?=[A-Za-z])|(?<=[A-Za-z])" + _REPLACEMENT
)


def repair_pdf_text(text: str) -> str:
    """Recover ligatures lost to a missing font encoding; drop the rest."""
    for pattern, replacement in _FL_FIXES:
        text = pattern.sub(replacement, text)
    text = _FI_RE.sub("fi", text)
    # Anything left is an unmapped digit (section numbers, dates) - not recoverable.
    return text.replace(_REPLACEMENT, "")

def is_table_of_contents(text: str) -> bool:
    """Detect TOC-style pages: dot leaders ("Section . . . . 12") dominate.

    Such pages answer no user question, so they are excluded from the KB.
    """
    if not text:
        return True
    return text.count(".") / len(text) > 0.15

class PdfLoader(BaseLoader):
    """Extract text from a PDF, one section per page.

    PDFs carry no reliable heading structure, so page-level sectioning is the
    honest baseline; the chunker splits further. Front matter (cover, revision
    history, table of contents) is skipped because it holds no answerable content.
    """

    source_type = "pdf"

    def __init__(self, skip_pages: int = 0, x_tolerance: float = 1.0) -> None:
        self.skip_pages = skip_pages
        self.x_tolerance = x_tolerance

    def load(self, file_path: Path) -> list[NormalizedSection]:
        sections: list[NormalizedSection] = []
        with pdfplumber.open(file_path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                if page_number <= self.skip_pages:
                    continue
                raw = page.extract_text(x_tolerance=self.x_tolerance) or ""
                text = repair_pdf_text(raw).strip()
                if is_table_of_contents(text):
                    continue
                if text:
                    sections.append(
                        NormalizedSection(
                            heading_path=[f"Page {page_number}"],
                            section=f"Page {page_number}",
                            text=text,
                        )
                    )
        return sections