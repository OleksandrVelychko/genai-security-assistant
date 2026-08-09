## What these nine questions showed

Nine questions, nine outcomes matching their expected labels. Eight of
those labels were written and committed before any prompt ran. `hw4_q9`
was added later, after a manual test, and labelled once its result was
known - see the last section of `outputs/rag_prompt_improvements.md`.
Six answered, every one citing chunks it was given and inventing none.
Three refused, by two different mechanisms.

### The refusal is two layers, and only one of them is cheap

`hw4_q6` (sourdough bread, best score 0.1258) and `hw4_q8` (Kubernetes
network policies, 0.3199) never reached the model. The score gate at 0.40
stopped both, at no cost.

`hw4_q7` (unbounded consumption, 0.4899) went through, and the model
refused it. Nothing else could have stopped it: `hw4_q3` has an answer in
this corpus and scores 0.4799, below `hw4_q7`. The two groups overlap, so
no threshold separates them, and the gate is only useful at the far end
where a question is plainly not about this corpus.

That is the case for keeping both layers. The gate saves a call on
questions that are obviously outside. Everything nearer the boundary is
the prompt's problem.

### Grounding is a second selection, after retrieval

Retrieval hands over five chunks. The answers do not use five.

- `hw4_q4`: the highest-scoring chunk, the agent cheat sheet Introduction
  at 0.5880, is not cited, and neither are the two governance PDF pages.
  Two of five chunks carried the answer.
- `hw4_q5`: the highest-scoring chunk is not cited either. The answer is
  built from ranks 3 and 5.

So retrieval decides what the model may use, and the prompt decides what
it does use. A pipeline judged only on retrieval metrics would not show
this, and a pipeline judged only on answers would not show which half went
wrong when one does.

### The gate belongs on the set, not on each chunk

`hw4_q2` cites a chunk scoring 0.3152 - below the 0.40 gate. The answer
needed it. A per-chunk cut at the same threshold would have removed
material the answer was built from.

The gate is applied to the best score among the chunks returned, which is
also how `retrieval/metrics.py` computes confidence in HW3, so the two
numbers are comparable.

### One answer depends on HW3

`hw4_q5` asks how to validate and constrain LLM output. Four sections in
this corpus are labelled grade 2 for that question in
`configs/eval_queries.yaml`; the closest match is "2. Define and validate
expected output formats", whose heading repeats most of the question.

In the HW2 baseline no grade-2 chunk reached the top five for this query at
all: three copies of the same cross-reference footer filled the first three
places. Both HW3 changes moved it. Deduplication removed the copies, which
is when a correct chunk first entered the top five, and BM25 brought in
"Output Monitoring and Validation" as well. The v3 answer cites exactly
those two, at ranks 3 and 5.

So the answer to this question rests on retrieval work that barely moved
the headline metrics in HW3.

### Rewording costs confidence, not accuracy

`hw4_q3` is `hw4_q1` with the words "prompt injection" removed. The best
score falls from 0.7003 to 0.4799, and four of the five chunks still come
from the same document. The answer even uses the term the question avoided,
having taken it from the context.

The practical reading: a score is a poor proxy for whether the corpus can
answer a question, because it also measures how closely the asker happened
to use the corpus's vocabulary.

### Citations are placed as asked in one answer out of six

Rule 3 asks for a citation after each sentence that used a chunk. Only
`hw4_q9` does that, in all four of its sentences. The other five bundle
every id at the end of the paragraph. The citations resolve either way, so
this costs nothing in verification and everything in readability: in five
answers out of six a reader cannot tell which sentence came from which
chunk.

## What this report does not show

- **Faithfulness is checked by hand, not by code.** The pipeline verifies
  that every cited id was among the chunks retrieved. Whether each sentence
  actually follows from the chunk it cites was traced by hand for `hw4_q5`
  and `hw4_q9` only.
- **One run.** Each answer here was produced once and then cached. Two runs
  of the same prompt can differ; see `retrieval/query_cache.py` for the
  same problem measured on the embedding side.
- **Nine questions, one model, one corpus.** Every figure above is a
  description of this run, not an estimate of how often any of it happens.
