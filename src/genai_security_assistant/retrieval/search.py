"""Top-k semantic search over the vector index.
Ties the pieces together: load the index and its chunk snapshot once,
then answer queries by encoding them and mapping FAISS rows back to chunks.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from genai_security_assistant.config import Settings
from genai_security_assistant.models.documents import Chunk
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.embeddings import (
    EmbeddingProvider,
    build_embedding_provider,
)
from genai_security_assistant.retrieval.indexing import load_chunks
from genai_security_assistant.retrieval.query_cache import CachedQueryEmbedder
from genai_security_assistant.retrieval.vector_store import FaissVectorStore


class BaseRetriever(Protocol):
    """What this file needs from the pipeline it wraps.
    A protocol rather than SemanticRetriever itself, for the same reason
    embeddings.py declares one: it names the three things actually used, so
    a test can supply a stand-in without an index and an embedding model
    behind it.
    """

    @property
    def default_top_k(self) -> int: ...

    @property
    def chunks(self) -> Sequence[Chunk]: ...

    def search(
        self, query: str, top_k: int | None = None
    ) -> list[RetrievedChunk]: ...


class SemanticRetriever:
    """Answers text queries with the most similar chunks.
    Load once, query many times: the model, index and chunks all stay
    in memory between calls.
    """

    def __init__(
        self,
        store: FaissVectorStore,
        provider: EmbeddingProvider,
        chunks: list,
        default_top_k: int = 5,
    ) -> None:
        self.store = store
        self.provider = provider
        self.chunks = chunks
        self.default_top_k = default_top_k

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> SemanticRetriever:
        """Build a retriever from configs/base.yaml and the saved index."""
        settings = settings or Settings()

        store = FaissVectorStore.load(
            settings.path("faiss_index"),
            settings.path("index_meta"),
        )

        embedding_config = settings.embedding_config()
        # Guard: the query model must match the one the index was built with.
        store.meta.assert_compatible(
            provider=embedding_config["provider"],
            model=embedding_config["model"],
        )

        # Query vectors come from a committed file instead of the API, so
        # that two runs of the same code produce the same numbers. See
        # query_cache.py for what went wrong without it.
        provider = CachedQueryEmbedder(
            path=settings.path("query_vectors"),
            model=embedding_config["model"],
            build_provider=lambda: build_embedding_provider(embedding_config),
        )
        chunks = load_chunks(settings.path("index_chunks"))

        if len(chunks) != store.meta.chunks_count:
            raise RuntimeError(
                f"Chunk snapshot has {len(chunks)} rows but the index holds "
                f"{store.meta.chunks_count}. Rebuild: "
                "uv run python scripts/build_index.py"
            )

        return cls(
            store=store,
            provider=provider,
            chunks=chunks,
            default_top_k=settings.retrieval.get("top_k", 5),
        )

    def search(self, query: str, top_k: int | None = None) -> list[RetrievedChunk]:
        """Return the top-k chunks most similar to the query."""
        if not query.strip():
            raise ValueError("Query is empty.")

        k = top_k or self.default_top_k
        query_vector = self.provider.encode([query])[0]
        hits = self.store.search(query_vector, top_k=k)

        results: list[RetrievedChunk] = []
        for rank, (row, score) in enumerate(hits, start=1):
            chunk = self.chunks[row]
            results.append(
                RetrievedChunk(
                    rank=rank,
                    score=score,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    metadata=chunk.metadata,
                )
            )
        return results
