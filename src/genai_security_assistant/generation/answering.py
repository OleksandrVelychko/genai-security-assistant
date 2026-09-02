"""The QA pipeline: a question in, a grounded answer out.
    question
    -> retrieve top-k chunks       (the HW3 pipeline, unchanged)
    -> stop here if nothing scored well enough
    -> build the prompt
    -> call the model
    -> read the citations back and check them
    -> GroundedAnswer

Two things can stop an answer. The score gate runs before the model and
costs nothing. The refusal rule in the prompt runs inside the model and
catches what the gate can't, such as q10.
"""

from __future__ import annotations

from genai_security_assistant.config import Settings
from genai_security_assistant.generation.answer_cache import CachedChatClient
from genai_security_assistant.generation.citations import split_citations
from genai_security_assistant.generation.llm import ChatClient, build_chat_client
from genai_security_assistant.generation.prompts import (
    DEFAULT_PROMPT_VERSION,
    FALLBACK_SENTENCE,
    PromptTemplate,
    get_prompt,
    is_refusal,
)
from genai_security_assistant.models.generation import GroundedAnswer
from genai_security_assistant.retrieval.filters import MetadataFilter
from genai_security_assistant.retrieval.improved import ImprovedRetriever


class RAGAnswerer:
    """Retrieval and generation joined together.
    Holds the retriever and the chat client, so a script can load once and
    ask many questions.
    """

    def __init__(
        self,
        retriever: ImprovedRetriever,
        chat: ChatClient,
        prompt: PromptTemplate,
        top_k: int,
        min_score: float,
    ) -> None:
        self.retriever = retriever
        self.chat = chat
        self.prompt = prompt
        self.top_k = top_k
        self.min_score = min_score

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        prompt_version: str | None = None,
        live: bool = False,
        use_hybrid: bool = True,
        drop_boilerplate: bool = True,
    ) -> RAGAnswerer:
        """Build everything from configs/base.yaml.
        prompt_version and live come from the command line and win over
        the config, so one run can be changed without editing a file.
        """
        settings = settings or Settings()
        config = settings.generation_config()

        use_cache = settings.generation.get("use_cached_answers", True)
        chat = CachedChatClient(
            path=settings.path("answers_cache"),
            model=config["model"],
            build_client=lambda: build_chat_client(config),
            read_cache=use_cache and not live,
        )

        version = prompt_version or settings.generation.get(
            "prompt_version", DEFAULT_PROMPT_VERSION
        )

        return cls(
            retriever=ImprovedRetriever.from_settings(
                settings,
                drop_boilerplate=drop_boilerplate,
                use_hybrid=use_hybrid,
            ),
            chat=chat,
            prompt=get_prompt(version),
            top_k=settings.retrieval.get("top_k", 5),
            min_score=settings.generation.get("min_score", 0.45),
        )

    def answer(
        self,
        question: str,
        metadata_filter: MetadataFilter | None = None,
    ) -> GroundedAnswer:
        """Answer one question, or say why it wasn't answered."""
        results = self.retriever.search(
            question, top_k=self.top_k, metadata_filter=metadata_filter
        )

        # max(), not results[0].score: hybrid mode reorders by RRF while
        # the scores stay cosine, so the first chunk is not the closest.
        best_score = max((chunk.score for chunk in results), default=0.0)

        if best_score < self.min_score:
            # No call is made. Nothing here is worth reading, so there's
            # nothing for the model to be grounded in.
            return GroundedAnswer(
                question=question,
                answer_text=FALLBACK_SENTENCE,
                status="abstained_by_gate",
                prompt_version=self.prompt.version,
                model=self.chat.model,
                retrieved=results,
            )

        system, user = self.prompt.render(question, results)
        answer_text = self.chat.complete(system, user)

        # Citations are read whatever the model said. A refusal should not
        # carry any, and if one does, the report should show that rather
        # than hide it behind a branch.
        citations, unsupported = split_citations(answer_text, results)

        return GroundedAnswer(
            question=question,
            answer_text=answer_text,
            status="abstained_by_model" if is_refusal(answer_text) else "answered",
            prompt_version=self.prompt.version,
            model=self.chat.model,
            citations=citations,
            unsupported_citations=unsupported,
            retrieved=results,
            # A test client is a plain ChatClient and has no such
            # attribute. Only the cache sets it.
            from_cache=getattr(self.chat, "last_was_cached", False),
        )
