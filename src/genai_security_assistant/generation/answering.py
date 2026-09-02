"""The QA pipeline: a question in, a grounded answer out.
    question
    -> retrieve top-k chunks       (the HW3 pipeline, unchanged)
    -> stop here if nothing scored well enough
    -> build the prompt
    -> call the model
    -> read the citations back and check them
    -> place them, repairing once if they are bundled
    -> GroundedAnswer

Two things can stop an answer. The score gate runs before the model and
costs nothing. The refusal rule in the prompt runs inside the model and
catches what the gate can't, such as q10.

A third check runs after both, and stops nothing: a repair that cannot
prove it left the claims alone is discarded, and the first answer ships
with citation_placement saying so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from genai_security_assistant.config import Settings
from genai_security_assistant.generation.answer_cache import CachedChatClient
from genai_security_assistant.generation.citations import (
    rejection_reason,
    split_citations,
    uncited_sentences,
)
from genai_security_assistant.generation.llm import ChatClient, build_chat_client
from genai_security_assistant.generation.prompts import (
    DEFAULT_PROMPT_VERSION,
    FALLBACK_SENTENCE,
    PromptTemplate,
    get_prompt,
    is_refusal,
    render_repair,
)
from genai_security_assistant.models.generation import (
    CitationPlacement,
    GroundedAnswer,
)
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.filters import MetadataFilter
from genai_security_assistant.retrieval.improved import ImprovedRetriever


@dataclass(frozen=True)
class PlacedAnswer:
    """One answer's citations, after the guardrail decided what to ship."""

    text: str
    placement: CitationPlacement
    attempts: int
    uncited: int
    uncited_before: int
    # False when the repair call went out for real. The answer's own flag
    # is not enough: a replayed answer whose repair reached the network
    # still cost a request, and from_cache is read as "this run made
    # none".
    from_cache: bool
    note: str | None


class FilteringRetriever(Protocol):
    """What this pipeline needs from retrieval: one call, filter included.
    A protocol rather than ImprovedRetriever itself, for the reason
    search.py gives for BaseRetriever - it names the one method actually
    used, so a test can stand in without an index behind it.
    """

    def search(
        self,
        query: str,
        top_k: int | None = None,
        metadata_filter: MetadataFilter | None = None,
    ) -> list[RetrievedChunk]: ...


class RAGAnswerer:
    """Retrieval and generation joined together.
    Holds the retriever and the chat client, so a script can load once and
    ask many questions.
    """

    def __init__(
        self,
        retriever: FilteringRetriever,
        chat: ChatClient,
        prompt: PromptTemplate,
        top_k: int,
        min_score: float,
        repair_citations: bool = True,
    ) -> None:
        self.retriever = retriever
        self.chat = chat
        self.prompt = prompt
        self.top_k = top_k
        self.min_score = min_score
        self.repair_citations = repair_citations

    @classmethod
    def from_settings(
        cls,
        settings: Settings | None = None,
        prompt_version: str | None = None,
        live: bool = False,
        use_hybrid: bool = True,
        drop_boilerplate: bool = True,
        repair_citations: bool | None = None,
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
            repair_citations=(
                repair_citations
                if repair_citations is not None
                else settings.generation.get("repair_citations", True)
            ),
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

        # Read here rather than at the return. last_was_cached describes
        # the most recent call, and the repair below would overwrite the
        # answer's flag with its own.
        from_cache = getattr(self.chat, "last_was_cached", False)

        if is_refusal(answer_text):
            # Citations are read whatever the model said. A refusal should
            # not carry any, and if one does, the report should show that
            # rather than hide it behind a branch. Placement is not judged:
            # the refusal claims nothing, so it has nothing to cite.
            citations, unsupported = split_citations(answer_text, results)
            return GroundedAnswer(
                question=question,
                answer_text=answer_text,
                status="abstained_by_model",
                prompt_version=self.prompt.version,
                model=self.chat.model,
                citations=citations,
                unsupported_citations=unsupported,
                retrieved=results,
                from_cache=from_cache,
            )

        placed = self.place_citations(answer_text, results)
        citations, unsupported = split_citations(placed.text, results)

        return GroundedAnswer(
            question=question,
            answer_text=placed.text,
            status="answered",
            prompt_version=self.prompt.version,
            model=self.chat.model,
            citations=citations,
            unsupported_citations=unsupported,
            retrieved=results,
            # Both calls, not the first one. The field is read as "this
            # answer cost no request", and a live repair costs one
            # whether or not it was taken.
            from_cache=from_cache and placed.from_cache,
            citation_placement=placed.placement,
            generation_attempts=placed.attempts,
            repair_note=placed.note,
            uncited_count=placed.uncited,
            uncited_before_repair=placed.uncited_before,
        )

    def place_citations(
        self, answer_text: str, results: list[RetrievedChunk]
    ) -> PlacedAnswer:
        """Return the citations this answer is allowed to ship with.
        One repair at most, and it replaces the answer only when it can
        be shown to be better: same claims, no invented ids, fewer
        uncited sentences. Every other outcome ships the first answer.
        """
        known = {chunk.chunk_id for chunk in results}
        first = len(uncited_sentences(answer_text, known))
        if first == 0:
            return PlacedAnswer(
                text=answer_text,
                placement="compliant",
                attempts=1,
                uncited=0,
                uncited_before=0,
                from_cache=True,
                note=None,
            )

        if not self.repair_citations:
            return PlacedAnswer(
                text=answer_text,
                placement="unrepaired",
                attempts=1,
                uncited=first,
                uncited_before=first,
                from_cache=True,
                note="repair_citations is off",
            )

        system, user = render_repair(answer_text, results)
        try:
            candidate = self.chat.complete(system, user)
        except Exception as error:
            # Deliberately broad. The repair is cosmetic and the answer
            # already in hand is not, so every way a second call can fail -
            # transport, rate limit, a body that will not parse - ends the
            # same way: the first answer ships and the failure is recorded.
            # Narrowing this to the exceptions known today would let an
            # unlisted one throw away a correct answer, which is the one
            # outcome this layer exists to prevent.
            return PlacedAnswer(
                text=answer_text,
                placement="unrepaired",
                attempts=2,
                uncited=first,
                uncited_before=first,
                # A call that failed still went out.
                from_cache=False,
                note=f"the repair call failed: {type(error).__name__}",
            )
        # Read here, before rejection_reason can return early. A refused
        # repair still made the call that this flag is about.
        repair_cached = getattr(self.chat, "last_was_cached", False)

        note = rejection_reason(answer_text, candidate, results)
        if note is not None:
            return PlacedAnswer(
                text=answer_text,
                placement="unrepaired",
                attempts=2,
                uncited=first,
                uncited_before=first,
                from_cache=repair_cached,
                note=note,
            )

        return PlacedAnswer(
            text=candidate,
            placement="repaired",
            attempts=2,
            uncited=len(uncited_sentences(candidate, known)),
            uncited_before=first,
            from_cache=repair_cached,
            note=None,
        )
