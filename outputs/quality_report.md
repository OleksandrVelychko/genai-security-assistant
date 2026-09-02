# Quality Report — GenAI Security Assistant (HW8)

Written by hand, unlike its neighbors in this directory. Every figure
below comes from `outputs/eval_summary.md` and `outputs/eval_results.csv`,
regenerated with `uv run python scripts/run_eval.py --live`.

## What was tested

Twelve questions through the HW7 LangGraph workflow, covering the six
scenarios the assignment asks for: a plain knowledge-base question, one
needing retrieval across two documents, one where retrieval is known to
struggle, three where the assistant should refuse, four needing a tool,
and two that are ambiguous or adversarial.

The set exercises all three routes, all four tools, and eleven of the
twelve graph nodes. Expected route, expected mode and expected behavior
were written in `configs/eval_cases.yaml` before the first run and were
not edited afterward.

## Results

| | |
|---|---|
| Task success | 10 of 12, no failures, 2 partial |
| Groundedness | good on 6 of 6 cases where it applies |
| Routing | 12 of 12 routes and modes as expected |
| Errors | `missing_context` 2, `tool_error` 1, none 9 |

The single `tool_error` is `e10`, which asks about a CVE that does not
exist. The empty result is the answer that case was written to get.

## Where the system works well

**Routing does not miss.** Every case reached the branch its expectation
named, including the one that ends in a question rather than an answer.

**Refusals work through three separate mechanisms.** An off-topic
question stops at the score gate far below the threshold; a neighboring
domain stops at the gate just below it; a question in the right domain
with no answer in the corpus passes the gate and is refused by the model.
None of the three cost a wrong answer.

**The tool layer holds its guarantees.** All four tools ran, the write
gate refused an unconfirmed write, and the confirmed write returned the
identifier an earlier report had already stored, appending nothing.
`e08` also caught the version trap it was built for: 1.2.9 against a fix
in 1.2.22 was read as exposed, which a text comparison would have called
patched.

**The injection probe was answered, not obeyed.** The assistant explained
the attack pattern from the corpus, cited five sections, and did not
disclose its own instructions.

## Where the system fails

Both partial cases are the same failure: a question whose answer is spread
across two documents got one of them. `e02` retrieved one of the seven
sections graded as its answer; `e03` cited one chunk out of five. Across
the six answered cases, 13 of 30 retrieved chunks were never cited.

## 3 main problems

**1. Retrieval follows the corpus's vocabulary, not the user's.**
`e02` asks how to apply least privilege to *AI agent tools* and gets
nothing from LLM06. In the same run, `e08` asks — in a question generated
from a CWE mapping — how to limit *the permissions of an extension*, and
receives two of the exact sections `e02` needed: "4. Minimize extension
permissions" and "5. Execute extensions in user's context". Same index,
same run, different wording. A user who does not already write like OWASP
gets a thinner answer, and nothing in the output says so.

**2. Citations are bundled, so no claim can be traced to a chunk.**
Five of the six answered cases place every citation at the end of the
paragraph. Only `e12` puts one after each sentence, which is what rule 3
of prompt v3 asks for. Verification therefore degrades from checking one
sentence against one chunk to reading all five. The groundedness metric
reports 100% here precisely because it only checks that a citation
resolves, never where it sits.

**3. No score threshold separates an unanswerable question from an
answerable one.** `e06` has no answer in this corpus and scored 0.4899,
above the 0.40 gate; the model refused it instead. Within these twelve
the gate looks adequate — the lowest answerable score was 0.5547 — but
`configs/qa_questions.yaml` records a question that *does* have an answer
scoring 0.4799, below `e06`. The margin here is a property of this set,
not of the system. The only working defense is one rule in the prompt, and
`outputs/rag_prompt_improvements.md` shows that changing the role block
turns that refusal back into an answer.

## Next steps

1. Bridge the vocabulary gap: map user phrasing onto corpus headings, or
   expand the query before searching. Measured by re-running `e02` and
   checking whether the four missing LLM06 sections reach the top five.
2. Enforce citation placement in the prompt, and add a check to the eval
   that measures where a citation sits rather than only that it resolves.
   The layer cannot currently see problem 2 at all.
3. Set `NVD_API_KEY`. About 78% of `lookup_cve`'s time is the wait that
   `tools.nvd.min_interval_seconds` imposes; a key raises the allowance
   from 5 requests per 30 seconds to 50, which would cut roughly a third
   off the whole live run.
4. Pin the refusal rule with a regression test, so a prompt edit that
   turns `e06` or `e12` into an answer fails loudly rather than quietly.
