"""Embedding backends behind one interface.
Chunks and queries must be encoded by the same model, so the rest of the
code asks for a provider once and reuses it for both.
"""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np

from genai_security_assistant.config import require_env


class EmbeddingProvider(Protocol):
    """What the indexing and search code needs from an embedding backend."""

    name: str
    model: str

    @property
    def dimension(self) -> int:
        """Length of a single vector. The FAISS index is built for it."""
        ...

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts into a float32 array of shape (len(texts), dimension)."""
        ...


class OpenAIEmbeddingProvider:
    """OpenAI embeddings, also usable with any OpenAI-compatible endpoint
    such as OpenRouter - only base_url and the key change.
    """

    name = "openai"

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str,
        batch_size: int = 64,
    ) -> None:
        from openai import OpenAI

        self.model = model
        self.batch_size = batch_size
        self._client = OpenAI(api_key=require_env(api_key_env), base_url=base_url)
        self._dimension: int | None = None

    @property
    def dimension(self) -> int:
        # The API does not advertise vector size, so ask it once and cache.
        if self._dimension is None:
            self._dimension = int(self.encode(["dimension probe"]).shape[1])
        return self._dimension

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            response = self._client.embeddings.create(model=self.model, input=batch)
            # The API may return items out of order; each carries its index.
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend(item.embedding for item in ordered)
        return np.asarray(vectors, dtype="float32")


class SentenceTransformerEmbeddingProvider:
    """Local embeddings. Needs the optional extra:
    uv sync --extra local-embeddings
    """

    name = "sentence_transformers"

    def __init__(self, model: str, batch_size: int = 32) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "sentence-transformers is not installed. Run: "
                "uv sync --extra local-embeddings"
            ) from error

        self.model = model
        self.batch_size = batch_size
        self._model = SentenceTransformer(model)

    @property
    def dimension(self) -> int:
        return int(self._model.get_sentence_embedding_dimension())

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            show_progress_bar=len(texts) > 64,
        )
        return vectors.astype("float32")


def build_embedding_provider(config: dict[str, Any]) -> EmbeddingProvider:
    """Instantiate the provider selected in configs/base.yaml.

    Takes the flat dict from Settings.embedding_config(), so this is the
    only function in the codebase that branches on provider names.
    """
    provider = config["provider"]

    if provider == "openai":
        return OpenAIEmbeddingProvider(
            model=config["model"],
            base_url=config["base_url"],
            api_key_env=config["api_key_env"],
            batch_size=config.get("batch_size", 64),
        )

    if provider == "sentence_transformers":
        return SentenceTransformerEmbeddingProvider(
            model=config["model"],
            batch_size=config.get("batch_size", 32),
        )

    raise ValueError(
        f"Unknown embeddings provider: {provider!r}. "
        "Expected 'openai' or 'sentence_transformers'."
    )
