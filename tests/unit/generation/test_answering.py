"""Unit tests for the citation guardrail around a generated answer."""

from __future__ import annotations

from genai_security_assistant.generation.answering import RAGAnswerer
from genai_security_assistant.generation.prompts import (
    FALLBACK_SENTENCE,
    get_prompt,
)
from genai_security_assistant.models.documents import ChunkMetadata
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.filters import MetadataFilter

BUNDLED = (
    "Agents act on model output. Excessive permissions widen the "
    "damage [chunk_a, chunk_b]."
)

DISTRIBUTED = (
    "Agents act on model output [chunk_a]. Excessive permissions widen "
    "the damage [chunk_b]."
)


def make_chunk(chunk_id: str, rank: int = 1) -> RetrievedChunk:
    """A retrieved chunk scoring well above any gate in these tests."""
    return RetrievedChunk(
        rank=rank,
        score=0.9,
        chunk_id=chunk_id,
        text="body text",
        metadata=ChunkMetadata(
            document_id="llm06",
            source_file="data/raw/llm06.html",
            source_type="html",
            source_url="https://example.test/llm06",
            title="llm06",
            section="Body",
            chunk_index=0,
            language="en",
            domain="genai_security",
            document_type="security_risk",
            publisher="test",
        ),
    )


class StubRetriever:
    """A retriever that answers every query with the same chunks.
    It records what it was asked, so a test can check that the pipeline
    hands its own top_k and filter down rather than only that a list
    comes back.
    """

    def __init__(self, chunks: list[RetrievedChunk], score: float = 0.9) -> None:
        self.chunks = [chunk.model_copy(update={"score": score}) for chunk in chunks]
        self.calls: list[tuple[str, int | None, MetadataFilter | None]] = []

    def search(
        self,
        query: str,
        top_k: int | None = None,
        metadata_filter: MetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        self.calls.append((query, top_k, metadata_filter))
        return self.chunks


class ScriptedChat:
    """A chat client that returns its replies in order and counts calls.
    last_was_cached is scripted per reply, because the pipeline reads it
    after the first call and a repair must not be able to change it.
    """

    name = "scripted"
    model = "test-model"

    def __init__(self, *replies: str, cached: tuple[bool, ...] = ()) -> None:
        self.replies = replies
        self.cached = cached
        self.calls: list[tuple[str, str]] = []
        self.last_was_cached = False

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        index = len(self.calls) - 1
        if index < len(self.cached):
            self.last_was_cached = self.cached[index]
        return self.replies[index]


def build(
    chat: ScriptedChat,
    score: float = 0.9,
    repair: bool = True,
    retriever: StubRetriever | None = None,
) -> RAGAnswerer:
    """A pipeline with the retrieval half stubbed out.
    retriever is injected the way build_flow takes a FakeRetrieval: a
    test asserting on what the stub recorded holds its own reference
    instead of reading one back through the protocol.
    """
    if retriever is None:
        chunks = [make_chunk("chunk_a"), make_chunk("chunk_b", 2)]
        retriever = StubRetriever(chunks, score)

    return RAGAnswerer(
        retriever=retriever,
        chat=chat,
        prompt=get_prompt("v3"),
        top_k=5,
        min_score=0.4,
        repair_citations=repair,
    )


def test_an_answer_already_cited_per_sentence_costs_one_call():
    chat = ScriptedChat(DISTRIBUTED)
    answer = build(chat).answer("why")

    assert len(chat.calls) == 1
    assert answer.citation_placement == "compliant"
    assert answer.generation_attempts == 1
    assert answer.citations_placed


def test_a_repair_that_only_moves_citations_replaces_the_answer():
    chat = ScriptedChat(BUNDLED, DISTRIBUTED)
    answer = build(chat).answer("why")

    assert answer.answer_text == DISTRIBUTED
    assert answer.citation_placement == "repaired"
    assert answer.generation_attempts == 2
    assert answer.uncited_count == 0


def test_a_repair_that_rewrites_the_answer_is_discarded():
    """The e01 run that pasted a chunk in as new sentences."""
    padded = "An agent is granted agency [chunk_a]. " + DISTRIBUTED
    chat = ScriptedChat(BUNDLED, padded)
    answer = build(chat).answer("why")

    assert answer.answer_text == BUNDLED
    assert answer.citation_placement == "unrepaired"
    assert answer.repair_note == "the claims changed"


def test_a_repair_that_moves_nothing_is_discarded():
    """The e01 run that turned [a, b] into [a][b] and stopped there."""
    reformatted = BUNDLED.replace("[chunk_a, chunk_b]", "[chunk_a][chunk_b]")
    chat = ScriptedChat(BUNDLED, reformatted)
    answer = build(chat).answer("why")

    assert answer.answer_text == BUNDLED
    assert answer.repair_note == "no fewer uncited sentences"

def test_turning_the_guardrail_off_spends_no_second_call():
    chat = ScriptedChat(BUNDLED)
    answer = build(chat, repair=False).answer("why")

    assert len(chat.calls) == 1
    assert answer.citation_placement == "unrepaired"
    assert answer.uncited_count == 1
    assert answer.uncited_before_repair == 1


def test_the_score_gate_still_answers_before_any_call():
    chat = ScriptedChat(DISTRIBUTED)
    answer = build(chat, score=0.1).answer("sourdough")

    assert chat.calls == []
    assert answer.status == "abstained_by_gate"
    assert answer.citation_placement == "not_applicable"


def test_a_refusal_is_not_sent_for_repair():
    chat = ScriptedChat(FALLBACK_SENTENCE)
    answer = build(chat).answer("unbounded consumption")

    assert len(chat.calls) == 1
    assert answer.status == "abstained_by_model"
    assert answer.citation_placement == "not_applicable"


def test_a_live_repair_makes_the_run_report_a_network_call():
    """The answer replayed and the repair did not. from_cache is read as
    "this run made no request", so one live call is enough to clear it."""
    chat = ScriptedChat(BUNDLED, DISTRIBUTED, cached=(True, False))
    answer = build(chat).answer("why")

    assert answer.from_cache is False


def test_a_run_replayed_end_to_end_still_reports_the_cache():
    chat = ScriptedChat(BUNDLED, DISTRIBUTED, cached=(True, True))
    answer = build(chat).answer("why")

    assert answer.from_cache is True


def test_the_pipeline_searches_with_its_own_top_k():
    """top_k belongs to the pipeline, not to the retriever's default: a
    prompt built for five chunks must not be handed a different number."""
    retriever = StubRetriever([make_chunk("chunk_a")])
    build(ScriptedChat(DISTRIBUTED), retriever=retriever).answer("why")

    assert retriever.calls == [("why", 5, None)]


def test_a_repaired_answer_records_the_count_it_started_from():
    """One run carries both columns of the before/after table."""
    chat = ScriptedChat(BUNDLED, DISTRIBUTED)
    answer = build(chat).answer("why")

    assert answer.uncited_before_repair == 1
    assert answer.uncited_count == 0
