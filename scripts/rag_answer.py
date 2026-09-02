"""Answer one question from the knowledge base.
Run from the project root:

    uv run python scripts/rag_answer.py -q "How do I prevent prompt injection?"
    uv run python scripts/rag_answer.py -q "..." --prompt v1
    uv run python scripts/rag_answer.py -q "..." --show-prompt
    uv run python scripts/rag_answer.py -q "..." --live

Retrieval runs in the full HW3 configuration: boilerplate dropped, BM25
fused with the dense ranking. HW4 compares prompts, not retrievers, so
that half is fixed here. scripts/retrieval_improved.py is still the place
to try search settings.

Answers and the API key
-----------------------
Answers already in index/answers_cache.json are replayed from disk, so
the nine questions in configs/qa_questions.yaml run with no network and
no key. Any other question calls the API and needs OPENAI_API_KEY in
.env, and its answer is written into the cache. That means the file turns
up as modified in git. Throw those away with

    git checkout -- index/answers_cache.json

unless the question is one being added to configs/qa_questions.yaml.

--live ignores the cache and calls the API even for a question already
in it, then overwrites the entry. Use it to check that a prompt change
actually changed the answer.
"""

from __future__ import annotations

import argparse

from genai_security_assistant.generation.answering import RAGAnswerer
from genai_security_assistant.generation.prompts import PROMPTS
from genai_security_assistant.models.generation import GroundedAnswer
from genai_security_assistant.retrieval.filters import MetadataFilter

LINE = "=" * 78


def parse_filter(pairs: list[str]) -> MetadataFilter | None:
    """Turn --filter field=value arguments into one filter."""
    conditions: dict[str, str | list[str]] = {}
    for pair in pairs:
        field, separator, value = pair.partition("=")
        if not separator or not value:
            raise SystemExit(
                f"--filter expects field=value, got {pair!r}. "
                "For example: --filter risk_category=prompt_injection"
            )
        conditions[field] = value
    return MetadataFilter.from_config(conditions)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Grounded question answering over the GenAI security corpus."
    )
    parser.add_argument("--query", "-q", required=True, help="User question.")
    parser.add_argument(
        "--prompt",
        "-p",
        choices=sorted(PROMPTS),
        default=None,
        help="Prompt version (defaults to configs/base.yaml).",
    )
    parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=None,
        help="Chunks to put in the prompt (defaults to configs/base.yaml).",
    )
    parser.add_argument(
        "--filter",
        "-f",
        action="append",
        default=[],
        metavar="FIELD=VALUE",
        help="Keep only chunks whose metadata matches. May be repeated.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Call the API even if the answer is cached, and overwrite it.",
    )
    parser.add_argument(
        "--no-repair",
        action="store_true",
        help="Skip the citation repair pass and answer as the pipeline did before.",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the prompt that would be sent, and stop.",
    )
    return parser.parse_args()


def print_answer(answer: GroundedAnswer) -> None:
    """Everything one question produced, in the order it happened."""
    source = "cache" if answer.from_cache else "live call"
    print(LINE)
    print(f"Question: {answer.question}")
    print(f"Prompt:   {answer.prompt_version}")
    print(f"Model:    {answer.model} ({source})")
    print(LINE)

    print("\nRetrieved chunks:")
    for chunk in answer.retrieved:
        meta = chunk.metadata
        print(
            f"  Top-{chunk.rank}: {chunk.chunk_id} | score {chunk.score:.4f}\n"
            f"    {meta.source_file} | {meta.section or '-'}"
        )

    print(f"\nAnswer:\n{answer.answer_text}")

    print(f"\nStatus:   {answer.status}")
    print(f"Grounded: {answer.is_grounded}")
    print(f"Sources:  {', '.join(answer.sources) or '-'}")
    print(f"Cited:    {', '.join(c.chunk_id for c in answer.citations) or '-'}")
    if answer.status == "answered":
        print(
            f"Placed:   {answer.citation_placement} "
            f"({answer.uncited_before_repair} -> {answer.uncited_count} uncited, "
            f"{answer.generation_attempts} call(s))"
        )
    if answer.repair_note:
        print(f"Repair:   {answer.repair_note}")
    if answer.unsupported_citations:
        # Printed only when it happens, so it reads as the alarm it is.
        print(f"INVENTED: {', '.join(answer.unsupported_citations)}")


def main() -> None:
    args = parse_args()

    answerer = RAGAnswerer.from_settings(
        prompt_version=args.prompt,
        live=args.live,
        # None, not True: without the flag the config decides.
        repair_citations=False if args.no_repair else None,
    )
    if args.top_k:
        answerer.top_k = args.top_k

    metadata_filter = parse_filter(args.filter)

    if args.show_prompt:
        results = answerer.retriever.search(
            args.query, top_k=answerer.top_k, metadata_filter=metadata_filter
        )
        system, user = answerer.prompt.render(args.query, results)
        print(LINE)
        print(f"SYSTEM ({answerer.prompt.version})")
        print(LINE)
        print(system or "(none)")
        print()
        print(LINE)
        print("USER")
        print(LINE)
        print(user)
        return

    print_answer(answerer.answer(args.query, metadata_filter=metadata_filter))


if __name__ == "__main__":
    main()
