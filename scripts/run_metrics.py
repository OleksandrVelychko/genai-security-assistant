"""Print retrieval quality metrics for every pipeline configuration.

Run from the project root:
    uv run python scripts/run_metrics.py
    
Nothing is written to disk. This is the quick feedback loop for changing
the pipeline; outputs/retrieval_comparison.md is the report that is kept.

The two improvements are switched on separately as well as together, so
that the last table answers 'which one did the work' rather than only
'is the result better'.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from genai_security_assistant.config import Settings
from genai_security_assistant.models.documents import Chunk
from genai_security_assistant.retrieval.filters import MetadataFilter
from genai_security_assistant.retrieval.improved import ImprovedRetriever
from genai_security_assistant.retrieval.indexing import load_chunks
from genai_security_assistant.retrieval.labels import LabelSet
from genai_security_assistant.retrieval.metrics import (
    QueryScore,
    RunScore,
    score_query,
    score_run,
)


@dataclass(frozen=True)
class Configuration:
    """One combination of the improvements, and the name it goes by."""

    name: str
    use_hybrid: bool
    drop_boilerplate: bool
    use_metadata_filter: bool


CONFIGURATIONS = (
    Configuration("baseline", False, False, False),
    Configuration("+ metadata filter", False, False, True),
    Configuration("+ boilerplate filter", False, True, False),
    Configuration("+ both filters", False, True, True),
    Configuration("+ hybrid only", True, False, False),
    Configuration("everything", True, True, True),
)

QUERY_HEADER = (
    f"{'query':<32}{'P@1':>6}{'P@3':>6}{'P@5':>6}{'MRR':>7}{'nDCG@5':>8}{'best':>8}"
)
RUN_HEADER = (
    f"{'configuration':<24}{'P@1':>6}{'P@3':>6}{'P@5':>6}"
    f"{'MRR':>7}{'nDCG@5':>8}{'margin':>9}"
)


def query_row(score: QueryScore) -> str:
    """One line of the per-query table, dashes where a figure has no meaning."""
    if score.abstain:
        figures = f"{'-':>6}{'-':>6}{'-':>6}{'-':>7}{'-':>8}"
    else:
        figures = (
            f"{score.precision_at_1:>6.2f}"
            f"{score.precision_at_3:>6.2f}"
            f"{score.precision_at_5:>6.2f}"
            f"{score.mrr:>7.3f}"
            f"{score.ndcg_at_5:>8.4f}"
        )
    return f"{score.query_id:<32}{figures}{score.best_score:>8.4f}"


def run_row(name: str, run: RunScore) -> str:
    return (
        f"{name:<24}{run.mean_precision_at_1:>6.2f}{run.mean_precision_at_3:>6.2f}"
        f"{run.mean_precision_at_5:>6.2f}{run.mean_mrr:>7.3f}"
        f"{run.mean_ndcg_at_5:>8.4f}{run.separation_margin:>+9.4f}"
    )


def measure(
    configuration: Configuration,
    settings: Settings,
    labels: LabelSet,
    chunks: Sequence[Chunk],
) -> RunScore:
    """Score every query once, under one combination of the improvements."""
    retriever = ImprovedRetriever.from_settings(
        settings,
        drop_boilerplate=configuration.drop_boilerplate,
        use_hybrid=configuration.use_hybrid,
    )
    scores = []
    for query in labels.queries:
        metadata_filter = (
            MetadataFilter.from_config(query.metadata_filter)
            if configuration.use_metadata_filter
            else None
        )
        results = retriever.search(query.query, metadata_filter=metadata_filter)
        scores.append(score_query(query, results, labels, chunks))
    return score_run(scores)


def main() -> None:
    settings = Settings()

    labels = LabelSet.load(settings.path("eval_queries"))
    chunks = load_chunks(settings.path("index_chunks"))
    # Same guard as check_labels.py: a label pointing at a section that does
    # not exist would quietly drag every figure below it down.
    labels.validate(chunks)

    runs = {c.name: measure(c, settings, labels, chunks) for c in CONFIGURATIONS}

    for name in ("baseline", "everything"):
        print(f"\n{name}\n")
        print(QUERY_HEADER)
        print("-" * len(QUERY_HEADER))
        for score in runs[name].per_query:
            print(query_row(score))

    print(f"\n\nablation\n\n{RUN_HEADER}")
    print("-" * len(RUN_HEADER))
    for configuration in CONFIGURATIONS:
        print(run_row(configuration.name, runs[configuration.name]))


if __name__ == "__main__":
    main()