"""Run the HW4 questions and write outputs/rag_answers_examples.md.
Run from the project root:

    uv run python scripts/run_rag_examples.py
    uv run python scripts/run_rag_examples.py --prompt v1 --output outputs/v1.md

Answers come from index/answers_cache.json, so this rebuilds the report
with no network and no key. --live forces fresh calls instead.

--prompt writes the same nine questions through an older prompt. That is
how the before/after examples in outputs/rag_prompt_improvements.md were
produced.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import yaml

from genai_security_assistant.config import Settings
from genai_security_assistant.generation.answering import RAGAnswerer
from genai_security_assistant.generation.citations import bare_mentions
from genai_security_assistant.generation.prompts import PROMPTS
from genai_security_assistant.models.generation import GroundedAnswer


def load_questions(settings: Settings) -> list[dict]:
    path = settings.path("qa_questions")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)["questions"]


def outcome(item: dict, answer: GroundedAnswer) -> str:
    """Did the pipeline do what the question was written to expect?
    Written into qa_questions.yaml before the run, so this compares a
    prediction with a result rather than describing the result twice.
    """
    actual = "abstained" if answer.abstained else "answered"
    return "as expected" if actual == item["expect"] else f"NOT expected ({actual})"


def render_summary(rows: list[tuple[dict, GroundedAnswer]]) -> list[str]:
    """One table, so the whole run can be read without scrolling."""
    lines = [
        "| Question | Kind | Expected | Status | Grounded | Cited |",
        "|---|---|---|---|---|---|",
    ]
    for item, answer in rows:
        lines.append(
            f"| {item['id']} | {item['kind']} | {item['expect']} | "
            f"{answer.status} | {answer.is_grounded} | {len(answer.citations)} |"
        )
    return lines


def render_question(
    item: dict,
    answer: GroundedAnswer,
    show_comment: bool,
) -> list[str]:
    """One question, in the shape the assignment asks for."""
    cited_ids = {citation.chunk_id for citation in answer.citations}

    lines = [
        f"## {item['id']}\n",
        f"**Question:** {answer.question}\n",
        "**Retrieved chunks:**\n",
        "```",
    ]
    for chunk in answer.retrieved:
        mark = " | cited" if chunk.chunk_id in cited_ids else ""
        meta = chunk.metadata
        lines.append(
            f"Top-{chunk.rank}: {chunk.chunk_id} | "
            f"score {chunk.score:.4f}{mark}"
        )
        lines.append(f"  {meta.source_file} | {meta.section or '-'}")
    lines.append("```\n")

    lines.append(f"**Answer:**\n\n{answer.answer_text}\n")
    lines.append(f"**Source:** {', '.join(answer.sources) or '-'}\n")
    lines.append(f"**Status:** `{answer.status}` - {outcome(item, answer)}\n")

    if answer.unsupported_citations:
        lines.append(
            f"**Invented citations:** {', '.join(answer.unsupported_citations)}\n"
        )

    # Only worth printing when there are no real citations. Otherwise it is
    # noise; here it says whether the model ignored the citation rule or
    # used a format the code cannot read.
    if not answer.citations:
        bare = bare_mentions(answer.answer_text, answer.retrieved)
        if bare:
            lines.append(f"**Named without brackets:** {', '.join(bare)}\n")

    # The comments in qa_questions.yaml describe the v3 run. Printing them
    # under a v1 answer would put analysis of one run beside the output of
    # another. The a priori note is safe in any version.
    if show_comment:
        text = (item.get("comment") or item.get("note") or "").strip()
        lines.append(f"**Comment:** {text}\n")
    else:
        lines.append(f"**Note:** {(item.get('note') or '').strip()}\n")
    lines.append("---\n")
    return lines

def main() -> None:
    parser = argparse.ArgumentParser(description="Write the HW4 answers report.")
    parser.add_argument("--prompt", "-p", choices=sorted(PROMPTS), default=None)
    parser.add_argument("--output", "-o", type=Path, default=None)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    # repair_citations=False: this report is a record of how the prompts
    # behaved, and the guardrail would rewrite the citations it measures.
    # It would also spend a second call on every answer here, which is what
    # the docstring above promises it does not do.
    answerer = RAGAnswerer.from_settings(
        prompt_version=args.prompt, live=args.live, repair_citations=False
    )
    questions = load_questions(settings)

    rows = [
        (item, answerer.answer(item["query"]))
        for item in questions
    ]

    matched = sum(1 for item, answer in rows if outcome(item, answer) == "as expected")
    # Gated questions never reach the client, so they are neither cached
    # nor live. Counting them in the denominator would read as three live
    # calls when there was one.
    called = [answer for _, answer in rows if answer.status != "abstained_by_gate"]
    replayed = sum(1 for answer in called if answer.from_cache)
    gated = len(rows) - len(called)

    lines = [
        "# HW4 - Grounded answers over retrieval\n",
        f"- **Model:** `{answerer.chat.model}`, temperature "
        f"{settings.generation.get('temperature', 0)}",
        f"- **Prompt:** `{answerer.prompt.version}` - {answerer.prompt.note}",
        "- **Retrieval:** the HW3 pipeline, full configuration "
        "(boilerplate dropped, BM25 fused), no metadata filter",
        f"- **Top-k:** {answerer.top_k}",
        f"- **Score gate:** {answerer.min_score}",
        f"- **Questions:** {len(rows)}, {matched} behaved as expected",
        f"- **Answers replayed from cache:** {replayed} of {len(called)} "
        f"({gated} questions never reached the model)",
        f"- **Generated:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n",
        "> Generated by `scripts/run_rag_examples.py`. Answers are read from "
        "`index/answers_cache.json` and questions from "
        "`configs/qa_questions.yaml`, so re-running this on a fresh clone "
        "reproduces the file without an API key.\n",
    ]

    lines.extend(render_summary(rows))
    lines.append("\n---\n")

    default_version = settings.generation.get("prompt_version", "v3")
    show_comments = answerer.prompt.version == default_version

    for item, answer in rows:
        lines.extend(render_question(item, answer, show_comments))
    conclusions = settings.path("answer_conclusions")
    if conclusions.exists():
        lines.append(conclusions.read_text(encoding="utf-8").strip())
        lines.append("")

    output_path = args.output or settings.path("rag_answers_examples")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {len(rows)} answers to {output_path} ({matched} as expected)")


if __name__ == "__main__":
    main()
