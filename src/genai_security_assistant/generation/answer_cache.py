"""Saved answers, so the report stays the same between runs.

query_cache.py froze the query vectors in HW3 for one reason, and the
same reason applies here. temperature=0 asks the API for its least
random answer. It does not promise the same words twice. HW4 compares
prompt v1 with prompt v3, and that comparison is worthless if the text
also changes on its own.

So each answer is fetched once, written to index/answers_cache.json and
committed. While the file has what a run needs, nothing calls the API.
That is what lets outputs/rag_answers_examples.md be rebuilt from a
fresh clone with no key.

The query vectors sit in a .npz, which git can only report as changed.
This file is JSON with sorted keys, so git shows which answer changed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from genai_security_assistant.generation.llm import ChatClient


def cache_key(model: str, system: str, user: str) -> str:
    """Fingerprint of one exact call.

    All three parts count. The user message holds the question and the
    retrieved chunks, so a different top-k is a different call. The
    system message holds the prompt version, so v1 and v3 never share
    an entry.
    """
    payload = "\n<<>>\n".join([model, system, user]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CachedChatClient:
    """A chat client that reads from a file first.

    Has the same name, model and complete() as the real client, so the
    pipeline treats both the same way.
    """

    name = "cached_chat"

    def __init__(
        self,
        path: Path,
        model: str,
        build_client: Callable[[], ChatClient],
        read_cache: bool = True,
    ) -> None:
        """read_cache=False calls the API and overwrites the entry.

        That is what --live does on the command line.
        """
        self.path = path
        self.model = model
        self.read_cache = read_cache

        # A function, not a ready client. Building the real client needs
        # an API key, and a full cache should need none.
        self._build_client = build_client
        self._client: ChatClient | None = None

        self._entries: dict[str, dict] = {}
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

    def _ensure_client(self) -> ChatClient:
        if self._client is None:
            self._client = self._build_client()
        return self._client

    def complete(self, system: str, user: str) -> str:
        """Return the answer, from disk when allowed and present.
        last_was_cached records which of the two happened. The report
        says so, because a replayed answer and a fresh one cost
        different money and are not the same run.
        """
        key = cache_key(self.model, system, user)

        if self.read_cache and key in self._entries:
            self.last_was_cached = True
            return self._entries[key]["answer"]

        answer = self._ensure_client().complete(system, user)
        self._entries[key] = {
            "model": self.model,
            "answer": answer,
            # The user message starts with "Context:", so the question is
            # buried. This is a label for whoever opens the file. Nothing
            # reads it back.
            "question_hint": user.split("Question:")[-1].strip()[:120],
            "created_at": f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%SZ}",
        }
        self._save()
        self.last_was_cached = False
        return answer
