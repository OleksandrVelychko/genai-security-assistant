## What the guardrail moved

Four of the seven cases produce an answer with citations in it. Across
their fourteen sentences, seven ended without one. After the guardrail,
none do, and the one answer that already met the contract was left alone
at the cost of no second call.

The three abstentions are untouched. A refusal claims nothing, so there is
nothing to attach a source to, and `not_applicable` says that rather than
counting them as clean.

That is the whole measured effect: one of four answers met the
sentence-level citation contract before, four of four meet it now.
Everything below is what that number does not say.

## e03 shows the ceiling of this improvement

Its four sentences now carry four citations, and all four are the same id.
Retrieval found one usable chunk for this question - `chunk_050`, "Page 19"
of the governance checklist - and its five bullets are where all four
sentences come from. The placement is correct and it discriminates nothing:
a reader checking the third sentence still has the same one page to read.

The count went from three uncited to zero. What a reader can verify did not
change at all. An improvement that shows up entirely in a number, on one
case out of four, is worth naming rather than averaging away.

## The same prompt does not place the same citations twice

`e01` was repaired twice while this layer was being built, with the
identical repair prompt, the identical model and `temperature: 0`. One run
attached `chunk_003` to the first sentence. The other attached `chunk_003`
and `chunk_002`.

The second is the better answer. The clause "damaging actions in response
to unexpected, ambiguous, or manipulated outputs from an LLM" is a verbatim
line of `chunk_002`, and the first run left it uncredited. The validator
passed both, because both end every sentence with an id.

`temperature: 0` narrows the variation and does not remove it. Placement is
therefore a property this pipeline enforces, and attribution is one it
happens to get, differently, on each run. Both runs are recorded here
rather than scripted: the second came from a throwaway probe that is not
in this repository.

## Nothing was refused on this run, which is not the check sitting idle

`rejection_reason` has three ways to decline a repair, and two of them were
produced by real runs while the repair prompt was being written:

- **the claims changed.** A prompt saying "a sentence built from two chunks
  and cited to one is wrong" had the model paste a whole chunk into the
  answer as three new sentences.
- **no fewer uncited sentences.** A prompt saying "the sentences are fixed,
  only the brackets move" had the model rewrite `[a, b]` as `[a][b]`, in
  the same place, and stop there.
- **invented ids.** Not seen in any run here. The check exists because a
  pass that may add a bracket may add a wrong one, and a citation pointing
  at a chunk the answer never saw is the failure this layer is for.

The unit tests reproduce all three. A clean table is what the guardrail
looks like when the model behaves, not evidence that it always will.

## Two answers this guardrail touches are not in this table

`retrieve_guidance` calls the same pipeline, so the triage cases `e07` and
`e08` are placed as well. Their questions are built from a CVE record at
run time and this script has no record to build one from, so they are
covered by `outputs/eval_results.md` instead.

Their composed answers are also why the check runs inside `RAGAnswerer`
rather than on the finished text. Four of the eight sentences in `e07` come
from tool output - a CVSS score, a service version, an owner, a finding id
- and none of them has a chunk to cite. Auditing the composed answer would
report seven violations against a run that did nothing wrong.

## A placed citation is still not a checked one

Every claim above is about where a citation sits. Whether the chunk it sits
on supports the sentence is measured nowhere in this repository, and `e01`
is where the two came apart: a run that satisfied the placement check
attributed a definition to the chunk holding the root causes.

`groundedness_good_rate` proves a citation resolves to a chunk the answer
was given. `citation_compliance_rate` proves it sits on a sentence. Neither
proves it is right, and only a reader closes that gap.
