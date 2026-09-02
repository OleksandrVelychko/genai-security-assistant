"""Persistent cache for model-based routing decisions.

Routing decisions are cached to keep orchestration and the evaluation
reports reproducible across runs, since a model asked the same question
twice can answer differently.

The key covers the model, the router's system message, the question and
the tool schemas the model was shown. Change any of them and a different
key is computed, so an earlier decision is simply not matched rather than
reused under new conditions. Nothing is removed: superseded entries stay
in the file.

Persistence follows the same pattern as generation/answer_cache.py.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from genai_security_assistant.models.orchestration import ToolChoice


def decision_key(model: str, system: str, question: str, tools: Any) -> str:
    """Fingerprint of one exact routing question."""
    payload = "\n<<>>\n".join(
        [model, system, question, json.dumps(tools, sort_keys=True)]
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CachedToolChooser:
    """A chooser that reads from a file first."""

    name = "cached_chooser"

    def __init__(
        self,
        path: Path,
        model: str,
        build_chooser: Callable[[], Any],
        read_cache: bool = True,
    ) -> None:
        self.path = path
        self.model = model
        self.read_cache = read_cache
        self._build_chooser = build_chooser
        self._chooser: Any | None = None
        self._entries: dict[str, dict[str, Any]] = {}
        self.last_was_cached: bool = False
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            self._entries = json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        """Write the whole file with sorted keys, so the diff is readable."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._entries, indent=2, sort_keys=True, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    def _ensure_chooser(self) -> Any:
        chooser = self._chooser
        if chooser is None:
            chooser = self._build_chooser()
            self._chooser = chooser
        return chooser

    def choose(
        self, system: str, question: str, tools: list[dict[str, Any]]
    ) -> ToolChoice:
        """Return the decision, from disk when allowed and present."""
        key = decision_key(self.model, system, question, tools)

        if self.read_cache and key in self._entries:
            self.last_was_cached = True
            return ToolChoice.model_validate(self._entries[key]["choice"])

        choice = self._ensure_chooser().choose(system, question, tools)
        self._entries[key] = {
            "choice": choice.model_dump(mode="json"),
            # A label for whoever opens the file. Nothing reads it back.
            "question_hint": question[:120],
            "created_at": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        }
        self._save()
        self.last_was_cached = False
        return choice
