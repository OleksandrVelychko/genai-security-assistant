"""Loader interface: a raw source file -> list of normalized sections.
Each concrete loader handles exactly one source_type (markdown, html, pdf)
and only does format parsing. Assembling the NormalizedDocument (attaching
manifest metadata) is the part of the pipeline's job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from genai_security_assistant.models.documents import NormalizedSection


class BaseLoader(ABC):
    """Base class for all format loaders."""

    #: source_type handled by this loader; set by each subclass.
    source_type: str

    @abstractmethod
    def load(self, file_path: Path) -> list[NormalizedSection]:
        """Parse a raw file into a list of NormalizedSection objects."""
        raise NotImplementedError
