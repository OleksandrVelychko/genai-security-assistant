## The answer exists only where two sources meet

"Does this CVE affect us" is not one question. It is a fact about the
vulnerability, a fact about this deployment, and a judgement that joins
them.

NVD answers the first and has never heard of this organization. The six
OWASP documents answer what to do about a class of risk and know nothing
about either the record or the deployment. Nothing in HW1 through HW5 can
reach the answer, and no amount of better retrieval would change that: the
missing facts are not in the corpus because they are not public.

That's what makes this a workflow rather than a longer prompt. The order
is fixed, but what runs and what it is asked are not: `get_service_owner`
is called with the service id the inventory returned, and the corpus is
asked about the weakness the record carried. Five of the eight steps run
only because a third one, which calls nothing, concluded `exposed`.

## The step that calls nothing is the step that decides

`assess_exposure` reaches no tool, no corpus and no clock. It reads the
CVSS score the lookup returned and the installed versions the inventory
returned, and it produces one word.

Every branch in the workflow turns on that word. `not_affected` and
`patched` end the run three steps in; `exposed` runs five more, one of
which writes to an audit log.

Keeping it as a step rather than folding it into either tool call was the
main structural decision. A tool that returned `is_exposed: true` would
hide the judgement inside an integration, and the trace would jump from a
lookup straight to a conclusion with nothing in between to disagree with.

## What the state saves is measured in model calls

`retrieve_guidance` is the only step that calls a model, and it sits
behind the assessment. Of the seven paths in the table above, three reach
it. The other four - patched, not affected, no such record, and the
clarification route - complete without one.

This is the practical form of "state decides the next step". It is not a
style preference; it is four model calls not spent on goals where the
answer was already known.

## A guidance question must name a control, not a defect

The question the corpus is asked is chosen by the CWE the record carries.
Four candidates were measured against the pipeline before two were kept:

| Question | Top score | Status |
|---|---|---|
| What controls limit what a compromised component of an LLM application can do? | 0.6301 | answered |
| How should an AI agent handle untrusted input that it parses or loads, and what limits the damage when that input is hostile? | 0.5547 | answered |
| What does OWASP recommend for validating file paths and external resources an LLM application loads on behalf of a user? | 0.6004 | **abstained_by_model** |
| How should an LLM application limit the permissions of an extension that reads external resources on a user's behalf? | 0.7391 | answered |

Reproduce any row with:

    uv run python scripts/rag_answer.py -q "..."

The third and fourth rows are the same CVE. The third names the defect -
validating a file path - and was refused even though it scored above the
`min_score` gate: retrieval found the neighbourhood, and the model, having
read the chunks, correctly said the documents do not cover it. The fourth
names the control the documents do prescribe, and scored highest of the
four.

The generalisation is about the corpus, not about phrasing. OWASP guidance
is organised around controls. A question shaped like a defect finds
adjacent text and no answer.

Two things follow. The gate and the prompt's refusal rule catch different
failures, and the third row is a live example of the second catching what
the first let through. And the agent layer inherited that refusal without
writing it: `retrieve_guidance` never inspects answer quality, because
`GroundedAnswer.abstained` already reports it.

## Two refusals for one write, on purpose

A finding is written only if the workflow proposes it and the tool
accepts it, and each refuses independently.

`confirm_write` stops the run when `AgentState.confirmed` is false.
`BaseTool.run` refuses a write whose `ToolRequest.confirmed` is false,
before it validates the arguments. Neither reads the other, and neither
can be set by a step or by a model - both arrive from the caller.

Example a2 shows the first one firing. The HW5 report shows the second.

## A failed lookup and an empty one mean different things

`check_asset_inventory` returns success with an empty list when nothing
deployed runs the component. That is an answer, and `not_affected` is
built on it.

A call that fails is treated as a halt instead. The distinction is not
tidiness: reading a broken inventory as "nothing runs this" would report
safety that nothing ever claimed, and it would read identically in the
trace.

`get_service_owner` goes the other way and returns `not_found` for an
unknown service, because a deployed service nobody owns is a gap in the
catalogue rather than a fact. A missing owner does not stop the run - the
finding is still worth writing, and the answer says nobody was found.

## Known limitations

- **The router reads an identifier, not an intent.** "How severe is
  CVE-2025-68664?" gets a full exposure triage, which is more than was
  asked for. HW5 has the same limitation from the other side.
- **`not_affected` is only as true as the inventory.** Nothing checks that
  the inventory is complete, and an absent service and an unknown one look
  the same.
- **One owner is looked up**, the first exposed service, even when several
  are exposed. The finding's title names that service; its summary names
  all of them.
- **`version_parts` is not PEP 440.** It compares leading digits and drops
  the rest, so `2.0.0rc1` and `2.0.0` compare equal. The versions in
  `configs/asset_inventory.yaml` stay inside what it handles.
- **`fixed_version` is one value per service, not a range per release
  line.** CVE-2025-68664 is patched in both 0.3.81 and 1.2.5, and the
  inventory records whichever line the service is on.
- **No step can ask a follow-up.** Clarification is a route decided before
  anything runs. A run that stops at the confirmation gate has to be
  started again with `--confirm`; it cannot wait.
- **The guidance map has two entries**, chosen by measuring four
  candidates. It is not a general mapping from CWE to corpus question, and
  a weakness outside it falls to the default.
- **The inventory is a file in this repository.** A real one is a service
  with access control, an owner and a staleness problem of its own.
