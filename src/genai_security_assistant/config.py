"""Configuration loading: base settings and the source manifest."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# config.py lives at src/genai_security_assistant/config.py,
# so the repository root is three levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "base.yaml"


def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file into a plain dictionary."""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


class Settings:
    """Runtime settings resolved from configs/base.yaml."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        raw = load_yaml(config_path)
        self.project: dict[str, Any] = raw.get("project", {})
        self.paths: dict[str, str] = raw.get("paths", {})
        self.chunking: dict[str, Any] = raw.get("chunking", {})

    def path(self, key: str) -> Path:
        """Resolve a configured relative path against the project root."""
        return PROJECT_ROOT / self.paths[key]


def load_sources(manifest_path: Path) -> list[dict[str, Any]]:
    """Load the source manifest, merging `defaults` into every entry.
    Per-source values win over defaults, so a cheat sheet can override
    `publisher` while still inheriting language, domain and license.
    """
    raw = load_yaml(manifest_path)
    defaults = raw.get("defaults", {})
    return [{**defaults, **entry} for entry in raw.get("sources", [])]