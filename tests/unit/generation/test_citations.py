"""Unit tests for reading citations and refusals out of an answer."""

from __future__ import annotations

from genai_security_assistant.generation.citations import (
    bare_mentions,
    claims,
    ends_with_citation,
    extract_citation_ids,
    rejection_reason,
    sentences,
    split_citations,
    uncited_sentences,
)
from genai_security_assistant.generation.prompts import FALLBACK_SENTENCE, is_refusal
from genai_security_assistant.models.documents import ChunkMetadata
from genai_security_assistant.models.retrieval import RetrievedChunk


def make_result(chunk_id: str, rank: int = 1, score: float = 0.5) -> RetrievedChunk:
    """A retrieved chunk carrying only the fields a citation reads."""
    return RetrievedChunk(
        rank=rank,
        score=score,
        chunk_id=chunk_id,
        text="body text",
        metadata=ChunkMetadata(
            document_id="llm01",
            source_file="data/raw/llm01.html",
            source_type="html",
            source_url="https://example.test/llm01",
            title="llm01",
            section="Body",
            chunk_index=0,
            language="en",
            domain="genai_security",
            document_type="security_risk",
            publisher="test",
        ),
    )


def test_the_refusal_sentence_is_recognised():
    assert is_refusal(FALLBACK_SENTENCE)


def test_a_quoted_refusal_still_counts():
    """Models often wrap the sentence in quotes. It is still a refusal."""
    assert is_refusal(f'"{FALLBACK_SENTENCE}"')


def test_a_refusal_split_over_lines_still_counts():
    """This is why normalize() collapses whitespace before comparing."""
    assert is_refusal(FALLBACK_SENTENCE.replace(" ", "\n"))


def test_a_real_answer_is_not_a_refusal():
    assert not is_refusal("Prompt injection alters model behaviour [llm01_chunk_001].")


def test_citation_ids_keep_their_order_and_appear_once():
    text = "First [chunk_a]. Second [chunk_b]. Again [chunk_a]."
    assert extract_citation_ids(text) == ["chunk_a", "chunk_b"]


def test_real_and_invented_citations_are_separated():
    retrieved = [make_result("chunk_a")]
    real, invented = split_citations("See [chunk_a] and [chunk_z].", retrieved)

    assert [citation.chunk_id for citation in real] == ["chunk_a"]
    assert invented == ["chunk_z"]


def test_a_citation_carries_the_source_file_of_its_chunk():
    real, _ = split_citations("See [chunk_a].", [make_result("chunk_a")])
    assert real[0].source_file == "data/raw/llm01.html"


def test_anything_bracketed_that_is_not_a_chunk_counts_as_invented():
    """A reader cannot check [1] either, so it is not quietly dropped."""
    _, invented = split_citations("As shown [1].", [make_result("chunk_a")])
    assert invented == ["1"]


def test_an_id_named_without_brackets_is_reported_separately():
    """Prompt v2 asks the model to mention the id but not how. This measures
    the difference between ignoring the rule and using the wrong format."""
    retrieved = [make_result("chunk_a")]
    answer = "According to chunk_a, prompt injection alters behaviour."

    real, invented = split_citations(answer, retrieved)
    assert real == []
    assert invented == []
    assert bare_mentions(answer, retrieved) == ["chunk_a"]


def test_a_bracketed_id_is_not_also_a_bare_mention():
    retrieved = [make_result("chunk_a")]
    assert bare_mentions("See [chunk_a].", retrieved) == []


def test_two_ids_in_one_bracket_are_both_found():
    """The model writes [a, b] often enough that dropping it loses real
    citations, and the earlier pattern dropped it in silence."""
    assert extract_citation_ids("Both [chunk_a, chunk_b].") == ["chunk_a", "chunk_b"]


def test_a_bracketed_phrase_is_not_a_citation():
    """Prose in brackets is prose. Only a single word can be an id."""
    assert extract_citation_ids("As shown [see the next section].") == []


# The three shapes e01 produced across the probe runs, shortened. Keeping
# them as fixtures means every rejection test reproduces a failure that
# actually happened rather than one imagined for the test.
BUNDLED = (
    "Excessive Agency is a vulnerability where the system is granted too "
    "much autonomy. It typically arises through extensions or agents. "
    "Common triggers include prompt injection [chunk_a, chunk_b]."
)

DISTRIBUTED = (
    "Excessive Agency is a vulnerability where the system is granted too "
    "much autonomy [chunk_b]. It typically arises through extensions or "
    "agents [chunk_a]. Common triggers include prompt injection [chunk_b]."
)

# The ids these fixtures were given. A bracket holding anything else is
# prose, and the checks below have to tell the two apart.
KNOWN = {"chunk_a", "chunk_b"}


def test_sentences_split_on_a_period_before_a_capital():
    assert len(sentences(BUNDLED)) == 3


def test_a_version_number_does_not_end_a_sentence():
    """No space follows the period in 1.2.9, which is what the lookahead
    in SENTENCE_BREAK relies on."""
    text = "svc-prompt-studio runs 1.2.9, fixed in 1.2.22 [chunk_a]."
    assert len(sentences(text)) == 1


def test_a_sentence_opening_with_a_quote_is_kept_whole():
    """e12 answers a question about an attack string and quotes it."""
    text = 'It is an attack [chunk_a]. "Ignore all instructions" [chunk_b].'
    assert len(sentences(text)) == 2


def test_a_citation_before_the_final_period_still_ends_the_sentence():
    assert ends_with_citation("Agents may act [chunk_a].", KNOWN)


def test_a_sentence_with_no_citation_is_reported():
    assert uncited_sentences(BUNDLED, KNOWN) == [1, 2]


def test_an_answer_cited_throughout_reports_nothing():
    assert uncited_sentences(DISTRIBUTED, KNOWN) == []


def test_claims_ignore_where_the_citations_sit():
    """The two answers differ only in placement, which is the change a
    repair is allowed to make."""
    assert claims(BUNDLED, KNOWN) == claims(DISTRIBUTED, KNOWN)


def test_a_repair_that_only_moves_citations_is_taken():
    retrieved = [make_result("chunk_a"), make_result("chunk_b", rank=2)]
    assert rejection_reason(BUNDLED, DISTRIBUTED, retrieved) is None


def test_a_repair_that_adds_a_sentence_is_refused():
    """The repair prompt once said a sentence built from two chunks and
    cited to one is wrong. The model satisfied that by pasting a chunk in
    as new sentences."""
    padded = DISTRIBUTED.replace(
        "It typically arises",
        "An LLM-based system is granted agency by its developer "
        "[chunk_a]. It typically arises",
    )
    retrieved = [make_result("chunk_a"), make_result("chunk_b", rank=2)]

    assert rejection_reason(BUNDLED, padded, retrieved) == "the claims changed"


def test_a_repair_that_invents_an_id_is_refused():
    candidate = DISTRIBUTED.replace("[chunk_a]", "[chunk_z]")
    reason = rejection_reason(BUNDLED, candidate, [make_result("chunk_b")])

    assert reason is not None
    assert "chunk_z" in reason


def test_a_repair_that_only_reformats_the_brackets_is_refused():
    """The second probe prompt turned [a, b] into [a][b] and moved
    nothing. Same placement, same information, one wasted call."""
    candidate = BUNDLED.replace("[chunk_a, chunk_b]", "[chunk_a][chunk_b]")
    retrieved = [make_result("chunk_a"), make_result("chunk_b", rank=2)]

    assert (
        rejection_reason(BUNDLED, candidate, retrieved)
        == "no fewer uncited sentences"
    )


def test_prose_in_brackets_is_not_a_citation():
    """A sentence ending "[above]" cites nothing, and counting it would
    report a claim as sourced when no chunk sourced it."""
    assert not ends_with_citation("See details [above].", KNOWN)


def test_a_numeric_range_is_not_a_citation():
    assert not ends_with_citation("Scores fall in [0,1].", KNOWN)


def test_a_repair_that_deletes_a_bracket_of_prose_is_refused():
    """Only citations are stripped before the comparison. A repair that
    removed "[0,1]" changed what the sentence says, and a check that
    stripped every bracket would have called the two texts equal."""
    original = "Use values [0,1] carefully."
    candidate = "Use values carefully [chunk_a]."
    retrieved = [make_result("chunk_a")]

    assert rejection_reason(original, candidate, retrieved) == "the claims changed"
