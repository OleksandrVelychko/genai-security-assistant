"""Markdown loader: split a .md file into sections by headings."""

from __future__ import annotations

import re
from pathlib import Path

from genai_security_assistant.ingestion.loaders.base import BaseLoader
from genai_security_assistant.models.documents import NormalizedSection

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


class MarkdownLoader(BaseLoader):
    """Parse Markdown, preserving the heading hierarchy for each section."""

    source_type = "markdown"

    def load(self, file_path: Path) -> list[NormalizedSection]:
        text = file_path.read_text(encoding="utf-8")
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

        for line in text.splitlines():
            match = _HEADING_RE.match(line.strip())
            if match:
                flush()
                buffer = []
                level = len(match.group(1))
                heading = match.group(2).strip()
                heading_path = heading_path[: level - 1]
                heading_path.append(heading)
                current_heading = heading
            else:
                buffer.append(line)

        flush()
        return sections
