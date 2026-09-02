"""Answer the guidance questions with the citation guardrail off and on,
and write outputs/citation_comparison.md.
Run from the project root:

    uv run python scripts/run_citation_comparison.py

Retrieval, prompt, model and temperature are identical in both halves,
so every difference in the tables comes from the guardrail.

The first answer of each pair is in index/answers_cache.json and replays.
The repair is a second call, cached the first time it runs, so a second
run of this script makes no request at all.

Only the guidance cases are here. A triage run asks the corpus a question
built from a CVE record, which this script has no record to build. Those
two answers take the same code path and have not been re-measured.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone

import yaml

from genai_security_assistant.config import Settings
from genai_security_assistant.generation.answering import PlacedAnswer, RAGAnswerer
from genai_security_assistant.generation.citations import sentences
from genai_security_assistant.models.generation import GroundedAnswer

# The one route whose answers carry chunk citations at all. A triage run
# ends in a composed answer whose first lines come from tool output, and
# a clarification run answers with a question.
GUIDANCE_ROUTE = "guidance"


@dataclass(frozen=True)
class Comparison:
    """One question answered twice, with the guardrail off and on."""

    case_id: str
    question: str
    before: GroundedAnswer
    after: PlacedAnswer

    @property
    def repaired(self) -> bool:
        return self.after.placement == "repaired"


def load_questions(settings: Settings) -> list[tuple[str, str]]:
    """The guidance cases from configs/eval_cases.yaml, in file order."""
    raw = yaml.safe_load(settings.path("eval_cases").read_text(encoding="utf-8"))
    return [
        (case["id"], case["question"])
        for case in raw["cases"]
        if case["expected_route"] == GUIDANCE_ROUTE
    ]


def _flat(text: str) -> str:
    """One paragraph on one line, so a blockquote stays a blockquote."""
    return " ".join(text.split())


def _count(placed: PlacedAnswer, value: int) -> str:
    """One count cell, dashed where the guardrail had nothing to place."""
    return "—" if placed.placement == "not_applicable" else str(value)


def place(answerer: RAGAnswerer, answer: GroundedAnswer) -> PlacedAnswer:
    """Run the guardrail over an answer the first half already produced.
    Asking the model a second time would answer the question twice, and
    two answers to one question can differ - temperature 0 narrows that
    and does not remove it. Repairing the first answer is what makes the
    two halves differ in the guardrail and nothing else.
    """
    if answer.status != "answered":
        return PlacedAnswer(
            text=answer.answer_text,
            placement="not_applicable",
            attempts=1,
            uncited=0,
            uncited_before=0,
            from_cache=True,
            note=None,
        )
    return answerer.place_citations(answer.answer_text, answer.retrieved)


def render_table(rows: list[Comparison]) -> list[str]:
    """One row per case: how many sentences, and how many went uncited."""
    lines = [
        "## Every guidance case, both ways\n",
        "| Case | Sentences | Uncited, off | Uncited, on | Placement |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row.case_id}` | {len(sentences(row.after.text))} "
            f"| {_count(row.after, row.after.uncited_before)} "
            f"| {_count(row.after, row.after.uncited)} "
            f"| `{row.after.placement}` |"
        )
    lines.append("")
    return lines


def render_refusals(rows: list[Comparison]) -> list[str]:
    """The repairs the guardrail declined, and why.
    Prints its own absence rather than disappearing: a missing section
    reads as a section nobody wrote, and this one is a result.
    """
    refused = [row for row in rows if row.after.note]
    lines = ["## Repairs the guardrail refused\n"]
    if not refused:
        lines += [
            "None on this run. The three reasons a repair can be refused "
            "are in `rejection_reason` in `generation/citations.py`, and "
            "the unit tests reproduce all three.\n",
        ]
        return lines

    lines += ["| Case | Reason | What shipped |", "|---|---|---|"]
    for row in refused:
        lines.append(
            f"| `{row.case_id}` | {row.after.note} "
            f"| the first answer, unchanged |"
        )
    lines.append("")
    return lines


def render_answers(rows: list[Comparison]) -> list[str]:
    """The repaired answers in full, so the difference can be read."""
    lines = ["## What changed, in full\n"]
    for row in (row for row in rows if row.repaired):
        lines += [
            f"### `{row.case_id}`\n",
            f"**Question:** {row.question}\n",
            "**Guardrail off**\n",
            f"> {_flat(row.before.answer_text)}\n",
            "**Guardrail on**\n",
            f"> {_flat(row.after.text)}\n",
        ]
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare the citation guardrail.")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()

    settings = Settings()
    questions = load_questions(settings)

    # One answerer, two settings. Loading the index and the BM25 tables
    # twice would change nothing and cost twice as much.
    answerer = RAGAnswerer.from_settings(live=args.live, repair_citations=False)
    before = [answerer.answer(question) for _, question in questions]

    answerer.repair_citations = True
    after = [place(answerer, answer) for answer in before]

    rows = [
        Comparison(case_id=case_id, question=question, before=first, after=second)
        for (case_id, question), first, second in zip(
            questions, before, after, strict=True
        )
    ]

    lines = [
        "# Final improvement - citation placement, off and on\n",
        f"- **Model:** `{answerer.chat.model}`, prompt "
        f"`{answerer.prompt.version}`, temperature "
        f"{settings.generation.get('temperature', 0)}",
        "- **Retrieval:** identical in both halves - the HW3 pipeline, "
        "full configuration, no metadata filter",
        f"- **Top-k:** {answerer.top_k}, **score gate:** {answerer.min_score}",
        f"- **Cases:** {len(rows)} guidance cases from "
        "`configs/eval_cases.yaml`",
        f"- **Generated:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}\n",
        "> Only `repair_citations` differs between the two halves. "
        "Generated by `scripts/run_citation_comparison.py`; the analysis "
        "below comes from `configs/citation_conclusions.md`.\n",
    ]
    lines.extend(render_table(rows))
    lines.extend(render_refusals(rows))
    lines.extend(render_answers(rows))
    lines.append("---\n")

    conclusions = settings.path("citation_conclusions")
    if conclusions.exists():
        lines.append(conclusions.read_text(encoding="utf-8").strip())
        lines.append("")

    output_path = settings.path("citation_comparison")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Wrote {len(rows)} cases, both ways, to {output_path}")


if __name__ == "__main__":
    main()
