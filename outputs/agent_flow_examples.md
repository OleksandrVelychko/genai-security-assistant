# Controlled agent workflow — traced examples

Generated: 2026-08-20 19:02:27Z
Model: `gpt-4.1-mini` · Router: `agent_router`

> This product uses the NVD API but is not endorsed or certified by
> the NVD.

Regenerate with `uv run python scripts/run_agent_flow_examples.py`.
The prose is written by hand in `configs/agent_scenarios.yaml` and
`configs/agent_conclusions.md`; every route, call, observation,
state and answer below is produced by running the workflow.

The assignment asks for one `State after step` per example. This
workflow runs up to eight steps, so each step gets a row of its own
in the trace and the state is printed once, after the last one.

## Examples

### 1. Does CVE-2025-68664 affect us?

The whole workflow, and the reason it has to be one.

Neither source can answer this alone. NVD holds the flaw and knows
nothing about this organization; the six OWASP documents hold the
class of risk and know nothing about either. The answer exists only
where the two meet, and reaching it takes four calls whose order is
fixed by what the one before returned.

The step that matters is the third. It calls nothing. It reads the
record from step one and the deployment rows from step two, concludes
`exposed`, and every step after it runs because of that one word.

**Question:** Does CVE-2025-68664 affect us?

**Route:** `triage` — The goal names a CVE, so exposure can be checked.

**Confirmed by a human:** True

**Planned steps:** 8 · **Completed:** 8

| # | Step | Tool called | Observation | Note |
|---|---|---|---|---|
| 1 | `lookup_cve` | `lookup_cve` `{"cve_id": "CVE-2025-68664"}` | ok, cached · Analyzed, CVSS 8.2 | CVE-2025-68664 is Analyzed. |
| 2 | `check_asset_inventory` | `check_asset_inventory` `{"cve_id": "CVE-2025-68664"}` | ok · svc-chat-gateway, svc-doc-indexer | Services running the component: 2. |
| 3 | `assess_exposure` | — | — | svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81. |
| 4 | `retrieve_guidance` | — | — | answered, 2 citations. |
| 5 | `identify_owner` | `get_service_owner` `{"service_id": "svc-chat-gateway"}` | ok · Conversational AI | Notify Conversational AI. |
| 6 | `propose_finding` | — | — | Severity high. |
| 7 | `confirm_write` | — | — | Confirmed by the caller. |
| 8 | `record_finding` | `record_security_finding` `{"related_cve_id": "CVE-2025-68664", "severity": "high",…` | ok · find_8e2355c84267 | Stored as find_8e2355c84267. |

**Finding drafted:**

```json
{
  "title": "CVE-2025-68664 affects svc-chat-gateway",
  "severity": "high",
  "related_cve_id": "CVE-2025-68664",
  "summary": "svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81"
}
```

**State after the last step:**

```json
{
  "route": "triage",
  "cve_id": "CVE-2025-68664",
  "exposure": "exposed",
  "affected_services": [
    "svc-chat-gateway",
    "svc-doc-indexer"
  ],
  "owner": "Conversational AI",
  "pending_confirmation": false,
  "recorded_finding": "find_8e2355c84267",
  "halt_reason": null,
  "completed_steps": [
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure",
    "retrieve_guidance",
    "identify_owner",
    "propose_finding",
    "confirm_write",
    "record_finding"
  ],
  "tool_calls": [
    "lookup_cve",
    "check_asset_inventory",
    "get_service_owner",
    "record_security_finding"
  ]
}
```

**Final answer:**

```text
CVE-2025-68664 is Analyzed, CVSS 8.2 HIGH per nvd@nist.gov, retrieved 2026-08-11.
Exposed: svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81.
Owner: Conversational AI, #sec-conversational-ai.
OWASP guidance: An AI agent should treat all external data as untrusted, including user messages, retrieved documents, API responses, and emails, and implement input sanitization before including such content in the agent's context. It is important to use delimiters and clear boundaries between instructions and data, apply content filtering for known injection patterns, and consider using separate LLM calls to validate or summarize untrusted content. Architecturally, the dual-LLM pattern can limit damage by having a privileged LLM that holds tools but never reads untrusted content directly, while a quarantined LLM reads untrusted content but cannot take action; the privileged model only receives structured summaries or labels, breaking the path for injected instructions to influence the actor. This approach helps refuse actions that drift due to injected instructions, thus limiting the damage from hostile input [owasp_cs_ai_agent_security_chunk_009][owasp_cs_prompt_injection_prevention_chunk_036].
Finding recorded as find_8e2355c84267.
```

### 2. Does CVE-2025-68664 affect us?

The same goal, one flag different.

Seven of the eight steps run exactly as above. The finding is
drafted, the owner is identified, and then `confirm_write` refuses
because no human said yes. Nothing reaches `data/findings.jsonl`.

This is the control HW5 built at the tool layer, working one level
up. `BaseTool.run` refuses an unconfirmed write; here the workflow
never proposes one. Two independent refusals for a single action is
deliberate: a workflow that forgot its gate would still be stopped
by the tool.

**Question:** Does CVE-2025-68664 affect us?

**Route:** `triage` — The goal names a CVE, so exposure can be checked.

**Confirmed by a human:** False

**Planned steps:** 8 · **Completed:** 7

| # | Step | Tool called | Observation | Note |
|---|---|---|---|---|
| 1 | `lookup_cve` | `lookup_cve` `{"cve_id": "CVE-2025-68664"}` | ok, cached · Analyzed, CVSS 8.2 | CVE-2025-68664 is Analyzed. |
| 2 | `check_asset_inventory` | `check_asset_inventory` `{"cve_id": "CVE-2025-68664"}` | ok · svc-chat-gateway, svc-doc-indexer | Services running the component: 2. |
| 3 | `assess_exposure` | — | — | svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81. |
| 4 | `retrieve_guidance` | — | — | answered, 2 citations. |
| 5 | `identify_owner` | `get_service_owner` `{"service_id": "svc-chat-gateway"}` | ok · Conversational AI | Notify Conversational AI. |
| 6 | `propose_finding` | — | — | Severity high. |
| 7 | `confirm_write` | — | — | Not confirmed; nothing written. |

**Finding drafted:**

```json
{
  "title": "CVE-2025-68664 affects svc-chat-gateway",
  "severity": "high",
  "related_cve_id": "CVE-2025-68664",
  "summary": "svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81"
}
```

**State after the last step:**

```json
{
  "route": "triage",
  "cve_id": "CVE-2025-68664",
  "exposure": "exposed",
  "affected_services": [
    "svc-chat-gateway",
    "svc-doc-indexer"
  ],
  "owner": "Conversational AI",
  "pending_confirmation": true,
  "recorded_finding": null,
  "halt_reason": null,
  "completed_steps": [
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure",
    "retrieve_guidance",
    "identify_owner",
    "propose_finding",
    "confirm_write"
  ],
  "tool_calls": [
    "lookup_cve",
    "check_asset_inventory",
    "get_service_owner"
  ]
}
```

**Final answer:**

```text
CVE-2025-68664 is Analyzed, CVSS 8.2 HIGH per nvd@nist.gov, retrieved 2026-08-11.
Exposed: svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81.
Owner: Conversational AI, #sec-conversational-ai.
OWASP guidance: An AI agent should treat all external data as untrusted, including user messages, retrieved documents, API responses, and emails, and implement input sanitization before including such content in the agent's context. It is important to use delimiters and clear boundaries between instructions and data, apply content filtering for known injection patterns, and consider using separate LLM calls to validate or summarize untrusted content. Architecturally, the dual-LLM pattern can limit damage by having a privileged LLM that holds tools but never reads untrusted content directly, while a quarantined LLM reads untrusted content but cannot take action; the privileged model only receives structured summaries or labels, breaking the path for injected instructions to influence the actor. This approach helps refuse actions that drift due to injected instructions, thus limiting the damage from hostile input [owasp_cs_ai_agent_security_chunk_009][owasp_cs_prompt_injection_prevention_chunk_036].
A finding is drafted and waiting for confirmation. Nothing has been written.
```

### 3. Does CVE-2025-67644 affect us?

The run that stops early, and what stopping early saves.

This CVE reaches one deployed service, and that service already runs
3.0.1 - the version the fix landed in. The assessment concludes
`patched`, and the five steps after it never run, including
`retrieve_guidance`, the only step in the workflow that calls a
model.

The plan still lists eight steps. Completed lists three. That gap is
what the assignment is about: what runs is decided by state, not by
the plan.

**Question:** Does CVE-2025-67644 affect us?

**Route:** `triage` — The goal names a CVE, so exposure can be checked.

**Confirmed by a human:** False

**Planned steps:** 8 · **Completed:** 3

| # | Step | Tool called | Observation | Note |
|---|---|---|---|---|
| 1 | `lookup_cve` | `lookup_cve` `{"cve_id": "CVE-2025-67644"}` | ok, cached · Analyzed, CVSS 7.8 | CVE-2025-67644 is Analyzed. |
| 2 | `check_asset_inventory` | `check_asset_inventory` `{"cve_id": "CVE-2025-67644"}` | ok · svc-agent-runtime | Services running the component: 1. |
| 3 | `assess_exposure` | — | — | Every affected service is already on the fix. |

**State after the last step:**

```json
{
  "route": "triage",
  "cve_id": "CVE-2025-67644",
  "exposure": "patched",
  "affected_services": [
    "svc-agent-runtime"
  ],
  "owner": null,
  "pending_confirmation": false,
  "recorded_finding": null,
  "halt_reason": null,
  "completed_steps": [
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure"
  ],
  "tool_calls": [
    "lookup_cve",
    "check_asset_inventory"
  ]
}
```

**Final answer:**

```text
CVE-2025-67644 is Analyzed, CVSS 7.8 HIGH per nvd@nist.gov, retrieved 2026-08-11.
Every service running the component is already on the fix.
```

### 4. How do I prevent prompt injection?

The route that was already finished before HW6 started.

No identifier, and no claim about this deployment: the goal asks
about a class of risk, which is precisely what six OWASP documents
answer. The router hands it to `RAGAnswerer` untouched, and what
comes back is the HW4 answer, citations and all.

Worth stating plainly, because it is the argument for having a
router at all: the agent layer adds nothing here. A workflow that
ran triage steps on this goal would call two tools with nothing to
contribute and produce a worse answer more slowly.

**Question:** How do I prevent prompt injection?

**Route:** `guidance` — The goal asks about a class of risk, which the corpus covers.

**Confirmed by a human:** False

**Planned steps:** 1 · **Completed:** 1

| # | Step | Tool called | Observation | Note |
|---|---|---|---|---|
| 1 | `answer_from_documents` | — | — | answered, 3 citations. |

**State after the last step:**

```json
{
  "route": "guidance",
  "cve_id": null,
  "exposure": null,
  "affected_services": [],
  "owner": null,
  "pending_confirmation": false,
  "recorded_finding": null,
  "halt_reason": null,
  "completed_steps": [
    "answer_from_documents"
  ],
  "tool_calls": []
}
```

**Final answer:**

```text
Preventing prompt injection is challenging due to the inherent nature of generative AI and the stochastic processes involved. While fool-proof prevention methods are unclear, mitigation strategies include building safeguards into system prompts and input handling to reduce the impact of prompt injections. Additionally, ongoing updates to the model’s training and safety mechanisms are necessary, especially to prevent jailbreaking, a severe form of prompt injection where safety protocols are disregarded. Techniques like Retrieval Augmented Generation (RAG) and fine-tuning improve output relevance and accuracy but do not fully mitigate prompt injection vulnerabilities. Therefore, a combination of prompt design, input validation, and continuous model safety updates is recommended to manage these risks effectively [owasp_llm01_prompt_injection_chunk_002][owasp_llm01_prompt_injection_chunk_003][owasp_llm01_prompt_injection_chunk_008].
```

### 5. Are we affected by that LangChain bug?

The gap HW5 wrote down and could not fill.

Its README lists it as a known limitation: "A request missing
required fields needs a clarifying question, not a different route.
The orchestration layer has no way to ask one."

This goal is clear English and nothing the assistant has can answer
it. The corpus holds no deployment facts. Triage needs an identifier
and there is none. Retrieval would answer about LangChain in
general, which is not what was asked. Asking back is the only
correct move, and it is now a route rather than a missing case.

**Question:** Are we affected by that LangChain bug?

**Route:** `clarification` — The goal asks about this deployment but names no identifier, and the documents hold no deployment facts.

**Confirmed by a human:** False

**Planned steps:** 1 · **Completed:** 1

| # | Step | Tool called | Observation | Note |
|---|---|---|---|---|
| 1 | `ask_for_clarification` | — | — | Asked for a CVE identifier. |

**State after the last step:**

```json
{
  "route": "clarification",
  "cve_id": null,
  "exposure": null,
  "affected_services": [],
  "owner": null,
  "pending_confirmation": false,
  "recorded_finding": null,
  "halt_reason": null,
  "completed_steps": [
    "ask_for_clarification"
  ],
  "tool_calls": []
}
```

**Final answer:**

```text
Which CVE do you mean? Checking whether something affects this organization needs an identifier, for example CVE-2025-68664.
```

## Every path, run

One row per outcome the workflow can reach. Each was executed for
this report; none of it is written by hand.

| Goal | Confirmed | Route | Exposure | Steps | Calls | Wrote |
|---|---|---|---|---|---|---|
| Does CVE-2025-68664 affect us? | True | `triage` | exposed | 8 of 8 | 4 | `find_8e2355c84267` |
| Does CVE-2025-68664 affect us? | False | `triage` | exposed | 7 of 8 | 3 | — |
| Does CVE-2025-67644 affect us? | False | `triage` | patched | 3 of 8 | 2 | — |
| Does CVE-2024-5565 affect us? | False | `triage` | not_affected | 3 of 8 | 2 | — |
| Does CVE-2023-99999 affect us? | False | `triage` | — | 1 of 8 | 1 | — |
| How do I prevent prompt injection? | False | `guidance` | — | 1 of 1 | 0 | — |
| Are we affected by that LangChain bug? | False | `clarification` | — | 1 of 1 | 0 | — |

## Notes

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

