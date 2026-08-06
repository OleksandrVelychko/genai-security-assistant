"""HTML loader: strip page chrome, extract readable text, split by headings."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup

from genai_security_assistant.ingestion.loaders.base import BaseLoader
from genai_security_assistant.models.documents import NormalizedSection

_NOISE_TAGS = [
    "script", "style", "nav", "header",
    "footer", "form", "aside", "noscript",
]
_NOISE_CLASS_RE = re.compile(
    r"(share|social|cookie|banner|breadcrumb|related|comment|newsletter)", re.IGNORECASE
)
_HEADING_TAGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4}
_TEXT_TAGS = ["p", "li"]


class HtmlLoader(BaseLoader):
    """Extract main-content sections from an HTML page."""

    source_type = "html"

    def load(self, file_path: Path) -> list[NormalizedSection]:
        html = file_path.read_text(encoding="utf-8", errors="ignore")
        soup = BeautifulSoup(html, "html.parser")

        # Drop non-content page chrome (menus, scripts, footers, forms).
        for tag in soup(_NOISE_TAGS):
            tag.decompose()

        for attribute in ("class", "id"):
            for tag in soup.find_all(attrs={attribute: _NOISE_CLASS_RE}):
                tag.decompose()

        root = soup.find("main") or soup.find("article") or soup.body or soup

        sections: list[NormalizedSection] = []
        heading_path: list[str] = []
        current_heading: str | None = None
        buffer: list[str] = []

        def flush() -> None:
            body = "\n".join(buffer).strip()
            if body:
                sections.append(
                    NormalizedSection(
                        heading_path=list(heading_path),
                        section=current_heading,
                        text=body,
                    )
                )

        for element in root.find_all(list(_HEADING_TAGS) + _TEXT_TAGS):
            content = element.get_text(" ", strip=True)
            if not content:
                continue
            if element.name in _HEADING_TAGS:
                flush()
                buffer = []
                level = _HEADING_TAGS[element.name]
                heading_path = heading_path[: level - 1]
                heading_path.append(content)
                current_heading = content
            else:
                buffer.append(content)

        flush()
        return sections
