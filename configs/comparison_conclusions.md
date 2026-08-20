## What each change did

Each figure names the row of the "Results by configuration" table it came
from, so it can be traced to a single configuration.

### The metadata filter

Where a question names a risk or a kind of document, the search was
narrowed to that part of the corpus. This restricted the candidate set,
and the ranking of what remained changed with it. Between `baseline` and
`+ metadata filter`, P@3 went from 0.29 to 0.38, MRR from 0.698 to 0.729
and nDCG@5 from 0.4843 to 0.5192.

Seven of the eleven questions name a scope. Four ranked differently once
the filter was applied; three came out exactly as before. The unchanged
results are informative too: for those three, dense retrieval was already
confined to the relevant documents.

The margin did not change in this run. No filter was applied to the three
unanswerable queries, and the weakest answerable one, q7, has no filter
either, so neither end of the subtraction moved.

Those three were left unfiltered for two different reasons. One is the
questions themselves: q9 asks about sourdough bread and q11 about
Kubernetes, and neither names anything this corpus holds, so no rule could
derive a scope. q10 names one, unbounded consumption, which exists in the
controlled vocabulary but has no document behind it; filtering on it would
return an empty candidate set. That absence is also why q10 has no answer.

The other reason is how the experiment is set up. These filters are written
by hand in configs/eval_queries.yaml, one per question, and are not
extracted from the question text by the pipeline. Two experiments are worth
keeping apart, and only the first was run:

1. **Correct constraints supplied.** Every scoped question is given the
   right filter by hand. This measures what a good metadata constraint is
   worth to retrieval, and it is what the table reports.
2. **End to end.** The pipeline derives the scope itself, or does without
   filtering. This measures a finished system, and was not attempted.

There is an asymmetry inside the first experiment as well. Scoped
answerable questions get a hand-written filter; q10 names a scope too and
does not. Supplying it would return no chunks at all, which hands the
abstention answer to the evaluator instead of measuring it.

### Deduplication

Fifteen chunks in this corpus are five paragraphs copied word for word onto
three pages each. They read like clean definitions, so they score well.

In `baseline`, three copies of the same footer filled the first three
places of q7, and no correct chunk reached the top five at all. In q10
three copies of another footer scored 0.5952, three thousandths below q7's
0.5982, the weakest of the eight questions this corpus can answer. Nothing
separated a question with an answer from a question without one.

Between `baseline` and `+ boilerplate filter` the margin went from +0.0030
to +0.0231, more than sevenfold (7.64 on the unrounded figures), and P@5
from 0.30 to 0.33. A correct chunk entered q7's results for the first time.

The filter drops every copy rather than keeping one canonical instance.
That is the aggressive option, and it needed checking, because repeated text
is often the important text: definitions, legal requirements, warnings and
shared policies all recur by design.

Two measurements decided it. First, none of the fifteen duplicated chunks
is labelled as an answer to any of the eleven queries; across all of them
they carry 160 grade-0 and 5 grade-1 labels, and no grade-2. Second,
keeping the best-scoring copy and dropping the rest was measured directly:
P@5 stayed at 0.30, MRR at 0.729, and the margin at +0.0030. The surviving
copy still stands first in q10, so the failure the filter exists for goes
unrepaired.

What the first check establishes is narrow. Removing these fifteen chunks
does not remove a grade-2 answer for the current evaluation set. It does
not show that the same paragraphs will be irrelevant to questions nobody
has asked yet. For a corpus this size, dropping them outright is
defensible; a production system has gentler options, such as keeping one
copy but excluding it from retrieval by a boilerplate flag, applying a
score penalty, or collapsing repeats in the returned top-k rather than in
the index.

nDCG@5 fell while this happened, from 0.4843 in `baseline` to 0.4760 in
`+ boilerplate filter`. That needs explaining, because it appears to
contradict the other metrics. The labels are attached to chunks and grade
those three footers as on topic, so nDCG treats each copy as a separate
useful result and awards gain three times, with nothing in the calculation
penalizing repetition. The decrease is driven by how duplicate grade-1
chunks are represented in the current evaluation, not by the removal of any
grade-2 answer.

### Hybrid search

BM25 found q7's "Output Monitoring and Validation", a section repeating
almost every word of the question. Dense retrieval placed it 23rd of 264
and never brought it into the top five in any configuration.

Between `+ both filters` and `improved (all three)`, P@5 went from 0.33 to
0.38 and nDCG@5 from 0.5055 to 0.5531, the best figures in the table. The
same step cost P@1, from 0.62 to 0.50, MRR, from 0.754 to 0.677, and the
margin, from +0.0231 to +0.0083.

Reciprocal rank fusion adds 1/(60 + position) across both rankings and uses
nothing else: not the cosine, not the BM25 score, only the positions. Rank
one is a position, not a statement of confidence, and fusion has no access
to confidence either way. q1 shows what that costs.

```
correct chunk    "Prevention and Mitigation Strategies"   grade 2
                 dense #1, BM25 #20   ->  1/61 + 1/80  =  0.028893

winning chunk    "Direct Prompt Injections"               grade 1
                 dense #9, BM25 #3    ->  1/69 + 1/63  =  0.030366
```

The correct chunk ended at position four. A chunk that neither ranker put
first beat one that dense retrieval alone had found.

The margin narrowed for a related reason. In `+ both filters` the highest
cosine among q7's five results was 0.5130; fusion reordered them, that
chunk was no longer among the five, and the highest remaining was 0.4982.
Neither is a grade-2 answer. Both are on-topic chunks that happen to score
well, which is the point: the margin is computed from similarity alone and
never consults the labels. q7 was the weakest answerable query in both
configurations, and q10 the strongest unanswerable one at 0.4899 in both,
so the entire change came from q7's side.

The constant 60 is the value the authors of the method settled on, and they
reported it as not sensitive to the exact choice. It was left alone; tuning
it against eleven queries would fit noise.

## Which change did the most

It depends on what the retrieval is for, and there are three defensible
answers.

| Goal                                            | Change          | Evidence                                                                                      |
|-------------------------------------------------|-----------------|-----------------------------------------------------------------------------------------------|
| One right answer first                          | Metadata filter | MRR 0.698 in `baseline` to 0.729 in `+ metadata filter`; adding hybrid takes it back to 0.677 |
| Five useful results                             | Hybrid search   | P@5 0.33 to 0.38 and nDCG@5 0.5055 to 0.5531, from `+ both filters` to `improved (all three)` |
| Separating answerable from unanswerable queries | Deduplication   | Margin +0.0030 in `baseline` to +0.0231 in `+ boilerplate filter`                             |

If only one may be named, it is deduplication. It produced the largest
improvement in answerable-versus-unanswerable separation, repaired two
unrelated failures at once, and needs no per-question configuration. The
rule behind it needs no knowledge of the subject either: text repeated word
for word across documents is identified from the data alone, and whether
dropping it is safe is a question the labels can answer for the queries
they cover.

## What this pipeline would ship as

All three changes together: the last row of the "Results by configuration"
table. That choice rests on retrieval figures alone and is made for this
assignment. It does not show that the same setup produces the best answers
once an assistant writes them.

The reason is that this retrieval hands all five chunks to the assistant,
so what matters most is the five as a set rather than which one is first.
Order still counts: a prompt can be cut short, a model tends to lean on
what it reads first, and one right chunk among four wrong ones can be
missed. The drop in P@1 is a real loss, not a rounding error.

The margin is the other loss, +0.0083 with fusion against +0.0231 without
it. If the main job were refusing questions the corpus cannot answer,
`+ both filters` would be the better starting point. That is a reason to
test it, not a reason to ship it.

## What these numbers do not say

**Only retrieval was measured.** These figures say whether the right chunks
came back. They say nothing about the answer an assistant would write from
them: whether it is correct, whether it sticks to the sources, whether it
cites them, whether it refuses when it should. The order the chunks arrive
in may matter to that as well. The configuration that wins here may not be
the one that produces the best answers, and that has to be checked
separately.

**q6 is easier than the others.** Thirty-eight of the 264 chunks count as
answering it, one in seven of the whole corpus, so landing on one of them
takes less than it does anywhere else. That says something about how q6 was
labelled rather than about the pipelines. The hardest queries are q7 and
q8, whose answers are five chunks and four.

**Eleven queries are not a benchmark.** Three of them are negative, which
is too few to pick a threshold that would hold. Even after a sevenfold
improvement, +0.0231 is a narrow band.

**Refusal is measured here, not implemented.** The `abstain` flag in
configs/eval_queries.yaml tells the metric which group a query belongs to.
Nothing in the pipeline reads it, and nothing in the pipeline refuses
anything. What the margin shows is that retrieval scores on their own are
not a sound basis for refusing. Where that decision should live - a
threshold on the retriever, a reranker, a separate classifier, or the
assistant itself - is not something this work answers.

**Query rewriting was not tried.** The assignment allows it as the second
technique, and it might have helped q7 the way BM25 did, but nothing here
tests that. It was left out because the assignment asks for one technique
and BM25 needs no model in the retrieval path. Reproducibility is not the
reason: rewritten queries could be cached the same way query vectors are.

## What comes next

- **A better measure of separation.** The margin is a single pair of
  extremes. Answerability AUROC or AUPRC would use every query rather than
  the two at the edges. With three unanswerable queries either would still
  be unstable, which is an argument for more negative queries first.
- **PDF extraction.** The governance checklist is split by page, so its
  sections are called "Page 19" and carry no heading. Fixing that changes
  the chunks themselves, which would have made this comparison measure two
  things at once.
- **Near-duplicate detection.** Exact repetition is caught; boilerplate
  reworded slightly is not, and a larger corpus would contain it. The same
  grade-2 check should gate any such rule, with the same limits on what it
  proves.
- **Incremental ingestion.** `content_hash`, the SHA-256 of each source
  file, is recorded on every chunk and still unused. It is what would let
  re-ingestion skip documents that have not changed.
- **A verification step.** A cross-encoder, or a model asked to judge one
  question against one chunk, would give a more meaningful relevance signal
  than RRF, which produces a rank-aggregation score rather than a
  calibrated one. Its output would not be calibrated by construction
  either: a usable refusal threshold needs a held-out set of answerable and
  unanswerable questions, a calibration procedure, and a check that it
  holds on questions it has not seen.