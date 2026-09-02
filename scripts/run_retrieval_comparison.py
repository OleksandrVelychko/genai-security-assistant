"""Write outputs/retrieval_comparison.md: HW2 retrieval against HW3 retrieval.

Run from the project root:
    uv run python scripts/run_retrieval_comparison.py

Everything above the closing analysis is generated from the committed index
and the committed query vectors, so a fresh clone reproduces the file
without an API key. The analysis itself is written by hand in
configs/comparison_conclusions.md and appended unchanged.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from genai_security_assistant.config import Settings
from genai_security_assistant.models.documents import Chunk
from genai_security_assistant.models.retrieval import RetrievedChunk
from genai_security_assistant.retrieval.filters import (
    MetadataFilter,
    SectionType,
    classify_sections,
)
from genai_security_assistant.retrieval.improved import ImprovedRetriever
from genai_security_assistant.retrieval.indexing import load_chunks
from genai_security_assistant.retrieval.labels import LabelSet, QueryLabels
from genai_security_assistant.retrieval.lexical import LexicalIndex
from genai_security_assistant.retrieval.metrics import RunScore, score_query, score_run
from genai_security_assistant.retrieval.search import SemanticRetriever

ANSWER = 2

CONFIGURATIONS = (
    ("baseline", False, False, False),
    ("+ metadata filter", False, False, True),
    ("+ boilerplate filter", False, True, False),
    ("+ both filters", False, True, True),
    ("+ hybrid only", True, False, False),
    ("improved (all three)", True, True, True),
)


def first_answer(results: Sequence[RetrievedChunk], labels: LabelSet,
                 query: QueryLabels) -> int | None:
    """Position of the first chunk labelled as the answer, if any came back."""
    for result in results:
        if labels.grade_of(result.metadata, query) == ANSWER:
            return result.rank
    return None


def answers_returned(results: Sequence[RetrievedChunk], labels: LabelSet,
                     query: QueryLabels) -> int:
    return sum(
        1 for result in results if labels.grade_of(result.metadata, query) == ANSWER
    )


def describe_change(
    old: RetrievedChunk,
    new: RetrievedChunk,
    section_types: dict[str, SectionType],
    metadata_filter: MetadataFilter | None,
    semantic_rank: dict[str, int],
    lexical_rank: dict[str, int],
) -> str:
    """Say, from the data alone, why the first result is a different chunk."""
    if old.chunk_id == new.chunk_id:
        return "unchanged"

    reasons = []
    if section_types[old.chunk_id] == "duplicate":
        reasons.append("old first result was boilerplate copied across pages")
    elif section_types[old.chunk_id] == "reference_links":
        reasons.append("old first result was a list of links")
    elif metadata_filter is not None and not metadata_filter.matches(old.metadata):
        reasons.append(f"old first result failed {metadata_filter.describe()}")
    else:
        reasons.append("old first result demoted by fusion")

    semantic = semantic_rank.get(new.chunk_id)
    keyword = lexical_rank.get(new.chunk_id)
    if keyword is not None and semantic is not None and keyword < semantic:
        reasons.append(
            f"new one ranked #{keyword} by keywords against #{semantic} by meaning"
        )
    elif semantic is not None:
        reasons.append(f"new one was already #{semantic} by meaning")
    return "; ".join(reasons)


def place(rank: int | None) -> str:
    """A position, or a plain statement that nothing correct came back."""
    return "not in top-5" if rank is None else f"#{rank}"


def table(rows: Sequence[Sequence[str]], header: Sequence[str]) -> str:
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def build(settings: Settings, hybrid: bool, boilerplate: bool) -> ImprovedRetriever:
    return ImprovedRetriever.from_settings(
        settings, drop_boilerplate=boilerplate, use_hybrid=hybrid
    )


def results_for(
    retriever: ImprovedRetriever,
    labels: LabelSet,
    use_metadata_filter: bool,
) -> dict[str, list[RetrievedChunk]]:
    out = {}
    for query in labels.queries:
        metadata_filter = (
            MetadataFilter.from_config(query.metadata_filter)
            if use_metadata_filter
            else None
        )
        out[query.id] = retriever.search(query.query, metadata_filter=metadata_filter)
    return out


def scores_for(results, labels: LabelSet, chunks: Sequence[Chunk]) -> RunScore:
    return score_run(
        [score_query(query, results[query.id], labels, chunks)
         for query in labels.queries]
    )


def main() -> None:
    settings = Settings()
    labels = LabelSet.load(settings.path("eval_queries"))
    chunks = load_chunks(settings.path("index_chunks"))
    labels.validate(chunks)

    section_types = classify_sections(chunks, settings.retrieval["reference_sections"])
    semantic = SemanticRetriever.from_settings(settings)
    lexical = LexicalIndex(chunks)

    runs: dict[str, RunScore] = {}
    for name, hybrid, boilerplate, metadata in CONFIGURATIONS:
        results = results_for(build(settings, hybrid, boilerplate), labels, metadata)
        runs[name] = scores_for(results, labels, chunks)

    base_results = results_for(build(settings, False, False), labels, False)
    best_results = results_for(build(settings, True, True), labels, True)

    parts = [
        "# HW3 - Baseline retrieval against improved retrieval\n\n"
        f"- **Baseline:** the HW2 pipeline, unchanged: cosine similarity over "
        f"{len(chunks)} chunks in a FAISS index\n"
        "- **Improved:** the same search, with copied boilerplate and link "
        "lists removed, a metadata filter per query where the question names "
        "one, and BM25 keyword results merged in by rank\n"
        f"- **Queries:** {len(labels.queries)}, the same ones HW2 was measured "
        "on, three of which have no answer anywhere in the corpus\n"
        f"- **Generated:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n\n"
        "> Both sides read committed files: the chunk vectors from "
        "`index/faiss.index` and the query vectors from "
        "`index/query_vectors.npz`. Re-running "
        "`scripts/run_retrieval_comparison.py` on a fresh clone reproduces "
        "every figure below, with no API key.\n"
    ]

    rows = []
    for query in labels.queries:
        old, new = base_results[query.id][0], best_results[query.id][0]
        semantic_rank = {
            r.chunk_id: r.rank for r in semantic.search(query.query, top_k=len(chunks))
        }
        lexical_rank = {
            chunk_id: rank
            for rank, chunk_id in enumerate(
                lexical.rank(query.query, top_k=len(chunks)), start=1
            )
        }
        rows.append([
            query.query,
            f"`{old.chunk_id}`",
            f"`{new.chunk_id}`",
            describe_change(
                old, new, section_types,
                MetadataFilter.from_config(query.metadata_filter),
                semantic_rank, lexical_rank,
            ),
        ])
    parts.append(
        "\n## Top-1 before and after\n\n"
        + table(rows, ["Query", "Baseline top-1", "Improved top-1", "What changed"])
        + "\n\n_Five of the eight answerable queries already had a correct "
        "chunk first, so this table has little room to show an improvement "
        "and does show two regressions. The next one is where the work "
        "actually landed._\n"
    )

    rows = []
    for query in labels.queries:
        if query.abstain:
            continue
        old, new = base_results[query.id], best_results[query.id]
        rows.append([
            query.id,
            place(first_answer(old, labels, query)),
            place(first_answer(new, labels, query)),
            str(answers_returned(old, labels, query)),
            str(answers_returned(new, labels, query)),
        ])
    parts.append(
        "\n## Where the answer actually moved\n\n"
        + table(rows, ["Query", "First answer, baseline", "First answer, improved",
                       "Answers in top-5, baseline", "Answers in top-5, improved"])
        + "\n"
    )

    rows = []
    for name, *_ in CONFIGURATIONS:
        run = runs[name]
        rows.append([
            name,
            f"{run.mean_precision_at_1:.2f}",
            f"{run.mean_precision_at_3:.2f}",
            f"{run.mean_precision_at_5:.2f}",
            f"{run.mean_mrr:.3f}",
            f"{run.mean_ndcg_at_5:.4f}",
            f"{run.separation_margin:+.4f}",
        ])
    parts.append(
        "\n## Results by configuration\n\n"
        "How to read the columns:\n\n"
        "- **P@k** - the share of the first k results that are the answer\n"
        "  itself. A section that is merely on the right topic does not\n"
        "  count.\n"
        "- **MRR** - one over the position of the first answer, averaged.\n"
        "  0.5 means it arrived second, 0 that it never arrived at all.\n"
        "- **nDCG@5** - the whole ranking against the best one the corpus\n"
        "  allows for that query, counting an on-topic section for less\n"
        "  than an answer. 1.0 means nothing better could have come back.\n"
        "- **Separation margin** - defined below the table.\n\n"
        + table(rows, ["Configuration", "P@1", "P@3", "P@5", "MRR", "nDCG@5",
                       "Separation margin"])
        + "\n\nEvery figure except the last column is a mean over the eight "
        "answerable queries.\n\n"
        "### How the separation margin is computed\n\n"
        "```\n"
        "confidence(query) = max cosine similarity among the chunks the\n"
        "                    pipeline actually returned for it\n"
        "\n"
        "margin = min(confidence(q) for the 8 answerable queries)\n"
        "       - max(confidence(q) for the 3 unanswerable ones)\n"
        "```\n\n"
        "- **Which score.** Cosine similarity, in every configuration. "
        "Fusion changes the order of results; the score attached to each "
        "chunk stays the semantic similarity it had, so the rows of this "
        "table are on one scale. The highest unanswerable confidence is "
        "0.4899 in both filtered rows, which is the same number rather "
        "than two comparable ones.\n"
        "- **Top-1 or first relevant?** Neither. It is the highest cosine "
        "among the five results shown, which under cosine ordering is the "
        "first of them and after fusion may not be. The labels are not "
        "consulted: a threshold in a running system would not have them.\n"
        "- **Queries with no correct result in the top five** still count, "
        "with whatever confidence they returned. Excluding them would "
        "measure the margin only where retrieval already worked.\n"
        "- **An empty result set** cannot occur here: filtering that leaves "
        "fewer than five widens the search to the whole index, and scoring "
        "refuses an empty list outright rather than treating it as zero.\n"
        "- **Is more always better?** A larger positive margin is more room "
        "for a threshold to sit in, and a negative one means the two groups "
        "overlap and no threshold exists. It says nothing about answer "
        "quality, and with three unanswerable queries it is a weak "
        "estimate: useful for comparing rows of this table, not for "
        "choosing a production threshold.\n"
    )

    conclusions = settings.path("comparison_conclusions")
    if conclusions.exists():
        parts.append("\n" + conclusions.read_text(encoding="utf-8").rstrip() + "\n")

    output = settings.path("retrieval_comparison")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {len(labels.queries)} queries and {len(CONFIGURATIONS)} "
          f"configurations to {output}")


if __name__ == "__main__":
    main()
