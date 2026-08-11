"""Configuration loading: base settings and the source manifest."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# config.py lives at src/genai_security_assistant/config.py,
# so the repository root is three levels up.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "base.yaml"

# Load .env once at import time
load_dotenv(PROJECT_ROOT / ".env")

def load_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file into a plain dictionary."""
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}

def require_env(var_name: str) -> str:
    """Read a secret from the environment, failing fast when it is not set."""
    value = os.environ.get(var_name)
    if not value:
        raise RuntimeError(
            f"Environment variable {var_name} is not set. "
            "Copy .env.example to .env and fill in your API key."
        )
    return value


class Settings:
    """Runtime settings resolved from configs/base.yaml."""

    def __init__(self, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
        raw = load_yaml(config_path)
        self.project: dict[str, Any] = raw.get("project", {})
        self.paths: dict[str, str] = raw.get("paths", {})
        self.chunking: dict[str, Any] = raw.get("chunking", {})
        self.embeddings: dict[str, Any] = raw.get("embeddings", {})
        self.retrieval: dict[str, Any] = raw.get("retrieval", {})
        self.generation: dict[str, Any] = raw.get("generation", {})
        self.tools: dict[str, Any] = raw.get("tools", {})

    def path(self, key: str) -> Path:
        """Resolve a configured relative path against the project root."""
        return PROJECT_ROOT / self.paths[key]

    def embedding_config(self) -> dict[str, Any]:
        """Return the active provider's config block, with its name folded in.
        Single source of truth for provider selection.
        """
        provider = self.embeddings.get("provider", "openai")
        block = dict(self.embeddings.get(provider, {}))
        block["provider"] = provider
        return block

    def generation_config(self) -> dict[str, Any]:
        """Return the active chat provider's config, with its name folded in.
        Same shape as embedding_config(): one place decides which provider
        is in use, everything else reads a flat dict.
        """
        provider = self.generation.get("provider", "openai")
        block = dict(self.generation.get(provider, {}))
        block["provider"] = provider
        block["temperature"] = self.generation.get("temperature", 0)
        block["max_output_tokens"] = self.generation.get("max_output_tokens", 600)
        return block

    def nvd_config(self) -> dict[str, Any]:
        """Return the NVD client config from configs/base.yaml."""
        return dict(self.tools.get("nvd", {}))


def load_sources(manifest_path: Path) -> list[dict[str, Any]]:
    """Load the source manifest, merging `defaults` into every entry.
    Per-source values win over defaults, so a cheat sheet can override
    `publisher` while still inheriting language, domain and license.
    """
    raw = load_yaml(manifest_path)
    defaults = raw.get("defaults", {})
    return [{**defaults, **entry} for entry in raw.get("sources", [])]

