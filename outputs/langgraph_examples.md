# LangGraph workflow — traced examples

Generated: 2026-08-21 12:09:22Z
Framework: `langgraph 1.2.11` · Model: `gpt-4.1-mini` · Router: `agent_router`

> This product uses the NVD API but is not endorsed or certified by
> the NVD.

Regenerate with `uv run python scripts/run_langgraph_examples.py`.
The prose is written by hand in `configs/langgraph_scenarios.yaml`
and `configs/langgraph_conclusions.md`; the diagram, every route,
node, call, observation, state and answer below is produced by
running the graph.

## The graph

Drawn from the compiled graph, so it is the workflow that ran and
not a picture kept beside it. A dotted edge was chosen by a
function; a coloured node is one such a function reads.

```mermaid
graph TD
    __start__([START])
    __end__([END])

    __start__ --> classify_request
    classify_request -. guidance .-> answer_from_documents
    classify_request -. clarification .-> ask_for_clarification
    classify_request -. triage .-> lookup_cve

    subgraph plan ["the eight steps HW6 ran as a plan"]
    direction TB
        lookup_cve -. continue .-> check_asset_inventory
        check_asset_inventory -. continue .-> assess_exposure
        assess_exposure -. exposed .-> retrieve_guidance
        retrieve_guidance --> identify_owner
        identify_owner --> propose_finding
        propose_finding --> confirm_write
        confirm_write -. confirmed .-> record_finding
    end

    answer_from_documents --> build_answer
    ask_for_clarification --> build_answer
    assess_exposure -. settled .-> build_answer
    build_answer --> __end__
    check_asset_inventory -. halt .-> build_answer
    confirm_write -. blocked .-> build_answer
    lookup_cve -. halt .-> build_answer
    record_finding --> build_answer

    classDef branch fill:#fff3cd,stroke:#8a6d00,color:#1a1a1a
    classDef gate fill:#f8d7da,stroke:#9b2226,color:#1a1a1a
    class assess_exposure,check_asset_inventory,classify_request,lookup_cve branch
    class confirm_write gate
```

## Examples

### 1. Does CVE-2025-68664 affect us?

The whole graph, and the only run that reaches every node it can.

Ten of twelve nodes execute. The two that do not are the other two
branches out of `classify_request`, which is what a conditional edge
is for: the route was decided once, at the first node, and eight
nodes downstream ran because of that decision rather than because
anyone listed them.

Compare the trace against HW6's. The eight steps in the middle are
the same eight, in the same order, with the same calls. What the
graph added is a node at each end.

**Question:** Does CVE-2025-68664 affect us?

**Route:** `triage` — The goal names a CVE, so exposure can be checked.

**Confirmed by a human:** True

**Nodes run:** 10 of 12 in the graph

| # | Node | Wrote to state | Tool called | Observation | Note |
|---|---|---|---|---|---|
| 1 | `classify_request` | `clarification_question`, `cve_id`, `route`, `route_reason` | — | — | Sent to triage: The goal names a CVE, so exposure can be checked. |
| 2 | `lookup_cve` | `cve_record` | `lookup_cve` `{"cve_id": "CVE-2025-68664"}` | ok, cached · Analyzed, CVSS 8.2 | CVE-2025-68664 is Analyzed. |
| 3 | `check_asset_inventory` | `affected_services` | `check_asset_inventory` `{"cve_id": "CVE-2025-68664"}` | ok · svc-chat-gateway, svc-doc-indexer | Services running the component: 2. |
| 4 | `assess_exposure` | `exposure` | — | — | svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81. |
| 5 | `retrieve_guidance` | `guidance` | — | — | answered, 2 citations. |
| 6 | `identify_owner` | `owner` | `get_service_owner` `{"service_id": "svc-chat-gateway"}` | ok · Conversational AI | Notify Conversational AI. |
| 7 | `propose_finding` | `proposed_finding` | — | — | Severity high. |
| 8 | `confirm_write` | `write_authorized` | — | — | Confirmed by the caller. |
| 9 | `record_finding` | `recorded_finding` | `record_security_finding` `{"related_cve_id": "CVE-2025-68664", "severity": "high",…` | ok · find_8e2355c84267 | Stored as find_8e2355c84267. |
| 10 | `build_answer` | `final_answer` | — | — | Answer for the triage route. |

**Finding drafted:**

```json
{
  "title": "CVE-2025-68664 affects svc-chat-gateway",
  "severity": "high",
  "related_cve_id": "CVE-2025-68664",
  "summary": "svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81"
}
```

**Final state:**

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
  "write_authorized": true,
  "recorded_finding": "find_8e2355c84267",
  "halt_reason": null,
  "executed_nodes": [
    "classify_request",
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure",
    "retrieve_guidance",
    "identify_owner",
    "propose_finding",
    "confirm_write",
    "record_finding",
    "build_answer"
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

The same goal, one flag different, and the node that reads it.

`confirm_write` runs and writes `write_authorized: false`. The edge
under it reads that field and goes to `build_answer` instead of
`record_finding`. Nothing reaches `data/findings.jsonl`.

The field exists because of a defect this port introduced. HW6's
`confirm_write` returned a boolean that `run_triage` had to read, so
a workflow that skipped the gate could not compile. A graph has no
such coupling: an edge reads a field, and a field a node never wrote
still holds its default. The first version of that edge read
`pending_confirmation`, whose default is `false` - and so a graph
with the gate removed would have written every time.

**Question:** Does CVE-2025-68664 affect us?

**Route:** `triage` — The goal names a CVE, so exposure can be checked.

**Confirmed by a human:** False

**Nodes run:** 9 of 12 in the graph

| # | Node | Wrote to state | Tool called | Observation | Note |
|---|---|---|---|---|---|
| 1 | `classify_request` | `clarification_question`, `cve_id`, `route`, `route_reason` | — | — | Sent to triage: The goal names a CVE, so exposure can be checked. |
| 2 | `lookup_cve` | `cve_record` | `lookup_cve` `{"cve_id": "CVE-2025-68664"}` | ok, cached · Analyzed, CVSS 8.2 | CVE-2025-68664 is Analyzed. |
| 3 | `check_asset_inventory` | `affected_services` | `check_asset_inventory` `{"cve_id": "CVE-2025-68664"}` | ok · svc-chat-gateway, svc-doc-indexer | Services running the component: 2. |
| 4 | `assess_exposure` | `exposure` | — | — | svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81. |
| 5 | `retrieve_guidance` | `guidance` | — | — | answered, 2 citations. |
| 6 | `identify_owner` | `owner` | `get_service_owner` `{"service_id": "svc-chat-gateway"}` | ok · Conversational AI | Notify Conversational AI. |
| 7 | `propose_finding` | `proposed_finding` | — | — | Severity high. |
| 8 | `confirm_write` | `pending_confirmation`, `write_authorized` | — | — | Not confirmed; nothing written. |
| 9 | `build_answer` | `final_answer` | — | — | Answer for the triage route. |

**Finding drafted:**

```json
{
  "title": "CVE-2025-68664 affects svc-chat-gateway",
  "severity": "high",
  "related_cve_id": "CVE-2025-68664",
  "summary": "svc-chat-gateway runs langchain-core 0.3.74, fixed in 0.3.81"
}
```

**Final state:**

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
  "write_authorized": false,
  "recorded_finding": null,
  "halt_reason": null,
  "executed_nodes": [
    "classify_request",
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure",
    "retrieve_guidance",
    "identify_owner",
    "propose_finding",
    "confirm_write",
    "build_answer"
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

The run that stops early, and the edge that stops it.

One deployed service runs the affected component, and it is already
on the fixed version. `assess_exposure` concludes `patched`, and the
edge under it sends the run straight to `build_answer`.

Five nodes of twelve. The seven that did not run include
`retrieve_guidance`, the only node on this branch that spends a model
call. That is the practical shape of conditional routing: not a
tidier diagram, but a model call not made because the state already
settled the question.

**Question:** Does CVE-2025-67644 affect us?

**Route:** `triage` — The goal names a CVE, so exposure can be checked.

**Confirmed by a human:** False

**Nodes run:** 5 of 12 in the graph

| # | Node | Wrote to state | Tool called | Observation | Note |
|---|---|---|---|---|---|
| 1 | `classify_request` | `clarification_question`, `cve_id`, `route`, `route_reason` | — | — | Sent to triage: The goal names a CVE, so exposure can be checked. |
| 2 | `lookup_cve` | `cve_record` | `lookup_cve` `{"cve_id": "CVE-2025-67644"}` | ok, cached · Analyzed, CVSS 7.8 | CVE-2025-67644 is Analyzed. |
| 3 | `check_asset_inventory` | `affected_services` | `check_asset_inventory` `{"cve_id": "CVE-2025-67644"}` | ok · svc-agent-runtime | Services running the component: 1. |
| 4 | `assess_exposure` | `exposure` | — | — | Every affected service is already on the fix. |
| 5 | `build_answer` | `final_answer` | — | — | Answer for the triage route. |

**Final state:**

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
  "write_authorized": null,
  "recorded_finding": null,
  "halt_reason": null,
  "executed_nodes": [
    "classify_request",
    "lookup_cve",
    "check_asset_inventory",
    "assess_exposure",
    "build_answer"
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

### 4. Are we affected by that LangChain bug?

A route that runs no tool and asks nothing of the corpus.

Three nodes: classify, ask, answer. `classify_request` finds no
identifier and writes the question that `build_answer` returns.

Worth including because it is the cheapest run the graph can do, and
because its trace shows the two nodes HW6 had no name for. In HW6
this route completed "1 of 1" planned steps while the router and the
answer composer ran outside the count. Here everything that happened
is in the trace.

**Question:** Are we affected by that LangChain bug?

**Route:** `clarification` — The goal asks about this deployment but names no identifier, and the documents hold no deployment facts.

**Confirmed by a human:** False

**Nodes run:** 3 of 12 in the graph

| # | Node | Wrote to state | Tool called | Observation | Note |
|---|---|---|---|---|---|
| 1 | `classify_request` | `clarification_question`, `cve_id`, `route`, `route_reason` | — | — | Sent to clarification: The goal asks about this deployment but names no identifier, and the documents hold no deployment facts. |
| 2 | `ask_for_clarification` | — | — | — | Asked for a CVE identifier. |
| 3 | `build_answer` | `final_answer` | — | — | Answer for the clarification route. |

**Final state:**

```json
{
  "route": "clarification",
  "cve_id": null,
  "exposure": null,
  "affected_services": [],
  "owner": null,
  "pending_confirmation": false,
  "write_authorized": null,
  "recorded_finding": null,
  "halt_reason": null,
  "executed_nodes": [
    "classify_request",
    "ask_for_clarification",
    "build_answer"
  ],
  "tool_calls": []
}
```

**Final answer:**

```text
Which CVE do you mean? Checking whether something affects this organization needs an identifier, for example CVE-2025-68664.
```

## Every path, run

One row per outcome the graph can reach. Each was executed for this
report; none of it is written by hand.

| Goal | Confirmed | Route | Exposure | Nodes | Calls | Wrote |
|---|---|---|---|---|---|---|
| Does CVE-2025-68664 affect us? | True | `triage` | exposed | 10 of 12 | 4 | `find_8e2355c84267` |
| Does CVE-2025-68664 affect us? | False | `triage` | exposed | 9 of 12 | 3 | — |
| Does CVE-2025-67644 affect us? | False | `triage` | patched | 5 of 12 | 2 | — |
| Does CVE-2024-5565 affect us? | False | `triage` | not_affected | 5 of 12 | 2 | — |
| Does CVE-2023-99999 affect us? | False | `triage` | — | 3 of 12 | 1 | — |
| How do I prevent prompt injection? | False | `guidance` | — | 3 of 12 | 0 | — |
| Are we affected by that LangChain bug? | False | `clarification` | — | 3 of 12 | 0 | — |

## Notes

Filled in after the report runs. See README.md, HW7.

