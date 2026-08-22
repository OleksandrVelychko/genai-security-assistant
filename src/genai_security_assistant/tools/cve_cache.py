"""Saved NVD responses, so the report stays the same between runs.

The raw body is kept and CveRecord is rebuilt from it on every read,
so a normalization bug is fixed by editing one function.

A CVE id that doesn't exist is not an error. NVD answers 200 with an
empty vulnerabilities list, so that body caches like any other.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from genai_security_assistant.tools.nvd_client import NvdClient


class CachedNvdClient:
    """An NVD client that reads from a file first.
    Same name, same fetch_cve, so the tool can't tell the two apart.
    """

    name = "nvd_cached"

    def __init__(
        self,
        path: Path,
        build_client: Callable[[], NvdClient],
        read_cache: bool = True,
    ) -> None:
        self.path = path
        self.read_cache = read_cache
        # A function, not a ready client: a full cache should need no
        # network and no key.
        self._build_client = build_client
        self._client: NvdClient | None = None
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

    def _ensure_client(self) -> NvdClient:
        """Build the real client on first use."""
        client = self._client
        if client is None:
            client = self._build_client()
            self._client = client
        return client

    def fetch_cve(self, cve_id: str) -> dict[str, Any]:
        """Return the raw body, from disk when allowed and present."""
        # The id itself, not a hash of it.
        # A plain key makes the file readable.
        key = cve_id.upper()

        if self.read_cache and key in self._entries:
            self.last_was_cached = True
            return self._entries[key]["payload"]

        payload = self._ensure_client().fetch_cve(cve_id)
        self._entries[key] = {
            "payload": payload,
            "fetched_at": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        }
        self._save()
        self.last_was_cached = False
        return payload
