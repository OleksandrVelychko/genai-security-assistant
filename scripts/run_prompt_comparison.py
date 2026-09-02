"""Run the same questions through all three prompts and write
outputs/rag_prompt_improvements.md.
Run from the project root:

    uv run python scripts/run_prompt_comparison.py

Retrieval, model and temperature are identical in all 3 runs, so
every difference in the tables comes from the prompt.

Every answer is already in index/answers_cache.json, so this makes no
API calls. --live forces fresh ones.

The figures are computed here. The analysis lives in
configs/prompt_conclusions.md and is appended to the end, the same way
HW2 and HW3 reports are built.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

from genai_security_assistant.config import Settings
from genai_security_assistant.generation.answering import RAGAnswerer
from genai_security_assistant.generation.citations import bare_mentions
from genai_security_assistant.generation.prompts import PROMPTS, get_prompt
from genai_security_assistant.models.generation import GroundedAnswer

# v2r sits between v2 and v3 on purpose: the table then reads as one
# change at a time.
VERSIONS = ["v1", "v2", "v2r", "v2c", "v3", "v3nr"]

# Statuses are long, and the per-question table has one column per version.
SHORT = {
    "answered": "answered",
    "abstained_by_gate": "gate",
    "abstained_by_model": "refused",
}


@dataclass(frozen=True)
class VersionScore:
    """One prompt version, reduced to the row that goes in the table."""

    version: str
    as_expected: int
    answered: int
    grounded: int
    citations: int
    prose_only: int


def load_questions(settings: Settings) -> list[dict]:
    path = settings.path("qa_questions")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)["questions"]


def matches(item: dict, answer: GroundedAnswer) -> bool:
    actual = "abstained" if answer.abstained else "answered"
    return actual == item["expect"]


def score_version(
    version: str,
    questions: list[dict],
    answers: list[GroundedAnswer],
) -> VersionScore:
    """Count what this prompt got right.
    prose_only counts answers that have no bracketed citation but still
    name a chunk id somewhere in the text.
    """
    answered = [a for a in answers if not a.abstained]
    return VersionScore(
        version=version,
        as_expected=sum(1 for i, a in zip(questions, answers) if matches(i, a)),
        answered=len(answered),
        grounded=sum(1 for a in answered if a.is_grounded),
        citations=sum(len(a.citations) for a in answers),
        prose_only=sum(
            1
            for a in answered
            if not a.citations and bare_mentions(a.answer_text, a.retrieved)
        ),
    )


def render_versions() -> list[str]:
    """What each prompt adds, read from the templates themselves."""
    lines = ["## What each version adds\n"]
    for version in VERSIONS:
        lines.append(f"- **{version}** - {PROMPTS[version].note}")
    lines.append("")
    return lines


def render_scores(scores: list[VersionScore], total: int) -> list[str]:
    lines = [
        "## Results\n",
        "| Prompt | Behaved as expected | Answered | Grounded "
        "| Citations | Named in prose only |",
        "|---|---|---|---|---|---|",
    ]
    for score in scores:
        lines.append(
            f"| {score.version} | {score.as_expected} of {total} "
            f"| {score.answered} | {score.grounded} of {score.answered} "
            f"| {score.citations} | {score.prose_only} |"
        )
    lines.append("")
    return lines


def render_matrix(
    questions: list[dict],
    runs: dict[str, list[GroundedAnswer]],
) -> list[str]:
    lines = [
        "## Question by question\n",
        "`gate` means the score gate stopped it and no call was made. "
        "**Bold** marks a result the question did not expect.\n",
        "| Question | Expected | " + " | ".join(VERSIONS) + " |",
        "|---|---|" + "---|" * len(VERSIONS),
    ]
    for index, item in enumerate(questions):
        cells = []
        for version in VERSIONS:
            answer = runs[version][index]
            label = SHORT[answer.status]
            cells.append(label if matches(item, answer) else f"**{label}**")
        lines.append(f"| {item['id']} | {item['expect']} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare the three prompts.")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    questions = load_questions(settings)

    # One retriever, three prompts. Loading the index and the BM25 tables
    # three times would change nothing and cost three times as much.
    # repair_citations=False: this report is a record of how the prompts
    # behaved, and the guardrail would rewrite the citations it measures.
    # It would also spend a second call on every answer here, which is what
    # the docstring above promises it does not do.
    answerer = RAGAnswerer.from_settings(
        live=args.live, repair_citations=False
    )

    runs: dict[str, list[GroundedAnswer]] = {}
    for version in VERSIONS:
        answerer.prompt = get_prompt(version)
        runs[version] = [answerer.answer(item["query"]) for item in questions]

    scores = [score_version(v, questions, runs[v]) for v in VERSIONS]

    lines = [
        "# HW4 - What changed between prompt versions\n",
        f"- **Model:** `{answerer.chat.model}`, temperature "
        f"{settings.generation.get('temperature', 0)}",
        f"- **Retrieval:** identical in all {len(VERSIONS)} runs - the HW3 pipeline, "
        "full configuration, no metadata filter",
        f"- **Top-k:** {answerer.top_k}, **score gate:** {answerer.min_score}",
        f"- **Questions:** {len(questions)}, from `configs/qa_questions.yaml`",
        f"- **Generated:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n",
        f"> Only the prompt differs between the {len(VERSIONS)} columns. "
        "Generated by `scripts/run_prompt_comparison.py`; the analysis "
        "below the tables comes from `configs/prompt_conclusions.md`. "
        "Full answers are in `outputs/rag_answers_v1.md`, "
        "`rag_answers_v2.md`, `rag_answers_v2r.md`, `rag_answers_v2c.md` "
        "and `rag_answers_examples.md`.\n",
    ]
    lines.extend(render_versions())
    lines.extend(render_scores(scores, len(questions)))
    lines.extend(render_matrix(questions, runs))
    lines.append("---\n")

    conclusions = settings.path("prompt_conclusions")
    if conclusions.exists():
        lines.append(conclusions.read_text(encoding="utf-8").strip())
        lines.append("")

    output_path = settings.path("prompt_improvements")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {len(VERSIONS)} prompt versions to {output_path}")


if __name__ == "__main__":
    main()
