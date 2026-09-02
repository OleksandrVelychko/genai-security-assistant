# Observability metrics

Generated: 2026-09-02 16:06:44Z
Run mode: `live` · Model: `gpt-4.1-mini` · Prompt: `v3` · Framework: `langgraph 1.2.11`

> This product uses the NVD API but is not endorsed or certified by
> the NVD.

Regenerate with `uv run python scripts/run_eval.py --live`.

## Metrics

| Metric | Value |
|---|---|
| total_cases | 12 |
| success_rate | 83.3% (12 of 12 judged) |
| partial_rate | 16.7% |
| failure_rate | 0.0% |
| groundedness_good_rate | 50.0% |
| groundedness_good_rate, where it applies | 100.0% (6 cases) |
| average_latency_ms | 5943 |
| median_latency_ms | 2749 |
| max_latency_ms | 24948 (`e10_triage_unknown_record`) |
| replayed from cache | 0.0% of cacheable calls |

A case with no retrieval behind it cannot be grounded in anything,
so the first groundedness rate is bounded by how much of the set
asks the corpus at all. The second one is over those cases only.

## top_error_types

| Error | Cases |
|---|---|
| `none` | 9 |
| `missing_context` | 2 |
| `tool_error` | 1 |

## The same cases, run the other way

| Run | Mean ms | Median ms | Max ms |
|---|---|---|---|
| `live` | 5943 | 2749 | 24948 |
| `cached` | 2 | 2 | 4 |

## Where the time goes

One row per node, over every case that executed it.

| Node | Calls | Total ms |
|---|---|---|
| `lookup_cve` | 4 | 51298.652 |
| `answer_from_documents` | 7 | 13641.480 |
| `retrieve_guidance` | 2 | 6354.117 |
| `record_finding` | 1 | 0.264 |
| `build_answer` | 12 | 0.248 |
| `classify_request` | 12 | 0.213 |
| `check_asset_inventory` | 3 | 0.132 |
| `identify_owner` | 2 | 0.128 |
| `propose_finding` | 2 | 0.066 |
| `assess_exposure` | 3 | 0.049 |
| `confirm_write` | 2 | 0.006 |
| `ask_for_clarification` | 1 | 0.004 |

## Notes

### What the two runs measure

The same twelve cases run twice: once against OpenAI and NVD, once out of
the caches the live half had just filled. The answers, routes, citations
and verdicts are identical between them. Only the latency columns move,
which is the point of running both.

The cached run is what a clone with no API key reproduces. Its latencies
measure retrieval, the graph and the disk - a real pipeline, minus the
network. The live run is the one the table above describes.

### The most expensive node is the most predictable one

`lookup_cve` is the largest entry in "Where the time goes" and it does no
thinking: it reads a JSON record. Around 78% of its time is the wait that
tools.nvd.min_interval_seconds imposes, not the request.

That wait is deterministic, so the node holds its total to within 2% over
repeated runs, while a single model call beside it can vary by a factor of
three. `e10_triage_unknown_record` is the clearest case: it executes three
nodes, makes no model call, and stays within 3% of itself run to run,
because it is six seconds of sleeping plus one round trip. Re-measure both
with `uv run python scripts/run_eval.py --live` and read the node column of
outputs/eval_traces_live.jsonl.

Two things follow. A maximum is a weak statistic here - the slowest case
changes between runs on one unlucky model call, while the medians stay
comparable. And the cheapest latency available to this system is an NVD API
key: the same file that sets the interval records that a key raises the
allowance from 5 requests per 30 seconds to 50.

### What the framework costs

Streaming and state merging in LangGraph come to under 20 ms across all
twelve runs of the set. That figure is the difference between latency_ms
and node_ms, which outputs/eval_results.csv carries for every case, so it
can be re-added at any time rather than taken on trust.

Beside a run that waits on a network that is nothing. Beside the cached
run, where the whole set finishes in a couple of milliseconds per case, it
is most of the time spent. The same absolute cost, read two opposite ways,
which is why both rows are in the table.

### What this eval can't see

groundedness_good_rate reads 100% over the cases where it applies, and that
measures one thing only: every citation resolves to a chunk that was
actually retrieved. It says nothing about where the citation sits. Five of
the six answered cases put every citation at the end of the paragraph
rather than after the sentence it supports, and no check here notices.

Nor does anything here measure whether a cited chunk supports the sentence
it is attached to. That is the difference between a citation being real and
a citation being right, and only a reader closes it.
