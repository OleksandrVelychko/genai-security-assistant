### What the two runs measure

The same twelve cases run twice: once against OpenAI and NVD, once out of
the caches the live half had just filled. The answers, routes, citations
and verdicts are identical between them. Only the latency columns move,
which is the point of running both.

The cached run is what a clone with no API key reproduces. Its latencies
measure retrieval, the graph and the disk - a real pipeline, minus the
network. The live run is the one the table above describes.

### The most expensive node, and which half of it we control

`lookup_cve` is the largest entry in "Where the time goes" and it does no
thinking: it reads a JSON record. Its time is two things added together -
the wait that tools.nvd.min_interval_seconds imposes before the request,
and however long NVD takes to answer it.

Only the first is ours. Across repeated runs the split between them has
moved from roughly three-quarters wait to roughly three-quarters upstream,
because the same endpoint has answered both in under a second and in about
nineteen. Derive the split for any run by subtracting the work done since
the previous request from six seconds, node by node, in
outputs/eval_traces_live.jsonl.

Two things follow, and neither is about our code. A maximum is a weak
statistic here: it names whichever case met the slowest call, and both
which case that is and how slow it was have moved between runs. And
timeout_seconds is 20 while a request has come back at about 19, so a
slower answer turns a case that reports a CVE into one that reports
upstream_error, taking its verdict with it.

An API key is worth setting, and it fixes the half we own rather than the
half we do not: nvd_client sets the interval to zero outright when a key
is present, which removes the wait and leaves the upstream exactly as it
was.

### What the framework costs

Streaming and state merging in LangGraph come to under 20 ms across all
twelve runs of the set. That figure is the difference between latency_ms
and node_ms, which outputs/eval_results.csv carries for every case, so it
can be re-added at any time rather than taken on trust.

Beside a run that waits on a network that is nothing. Beside the cached
run, where the whole set finishes in a couple of milliseconds per case, it
is most of the time spent. The same absolute cost, read two opposite ways,
which is why both rows are in the table.

### What this eval cannot see

groundedness_good_rate reads 100% over the cases where it applies, and that
measures one thing only: every citation resolves to a chunk that was
actually retrieved. It says nothing about where the citation sits. Five of
the six answered cases put every citation at the end of the paragraph
rather than after the sentence it supports, and no check here notices.

Nor does anything here measure whether a cited chunk supports the sentence
it is attached to. That is the difference between a citation being real and
a citation being right, and only a reader closes it.
