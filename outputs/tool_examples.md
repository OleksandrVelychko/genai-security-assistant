# External tool integration — examples

Generated: 2026-08-13 11:57:48Z
Model: `gpt-4.1-mini` · Router: `rule_router`

Regenerate with `uv run python scripts/run_tool_examples.py`.
The prose below is written by hand in `configs/tool_questions.yaml`
and `configs/tool_conclusions.md`; every call, result and answer is
produced by running the pipeline.

## The tools

### `lookup_cve` — read tool

**Purpose.** Return the current NVD record for one CVE identifier: status, description, CVSS score with its scorer, CWE ids and references.

**Source.** NVD CVE API 2.0

**When to call it**

- The question names a CVE identifier.
- The user asks whether a vulnerability is still current, has been rescored, or has been withdrawn.
- The user asks for the severity or CWE mapping of a known CVE.

**When not to call it**

- The question is about a class of risk rather than one record: the indexed OWASP documents answer those.
- The user wants mitigations or guidance rather than a record.
- No identifier is present. This tool looks up an id and cannot search by keyword.

**Input contract**

| field | type | required |
|---|---|---|
| `cve_id` | string | yes |

Schema as the model receives it:

```json
{
  "additionalProperties": false,
  "description": "Arguments for lookup_cve.",
  "properties": {
    "cve_id": {
      "description": "CVE identifier in the form CVE-YYYY-NNNN, for example CVE-2023-29374. Four or more digits after the year.",
      "maxLength": 30,
      "pattern": "^CVE-\\d{4}-\\d{4,}$",
      "title": "Cve Id",
      "type": "string"
    }
  },
  "required": [
    "cve_id"
  ],
  "title": "CveLookupInput",
  "type": "object"
}
```

**Output contract**

| field | type | required |
|---|---|---|
| `cve_id` | string | yes |
| `published` | string | yes |
| `last_modified` | string | yes |
| `vuln_status` | string | yes |
| `description` | string | yes |
| `cvss_score` | number or null | no |
| `cvss_severity` | string or null | no |
| `cvss_vector` | string or null | no |
| `cvss_version` | string or null | no |
| `cvss_source` | string or null | no |
| `cvss_type` | string or null | no |
| `cwe_ids` | array of string | no |
| `reference_urls` | array of string | no |
| `source` | string | no |
| `source_url` | string | yes |
| `retrieved_at` | string | yes |

### `record_security_finding` — write tool

**Purpose.** Append one security finding to the local audit log and return the stored record, including the identifier assigned to it.

**Source.** data/findings.jsonl

**When to call it**

- The user asks to log, record or file a finding they have described.
- A CVE lookup produced something the user wants kept.

**When not to call it**

- The user is asking a question rather than asking for something to be written down.
- No human has confirmed the write. This tool refuses instead of asking, because the confirmation is not the model's to give.

**Input contract**

| field | type | required |
|---|---|---|
| `title` | string | yes |
| `severity` | `low` / `medium` / `high` / `critical` | yes |
| `related_cve_id` | string or null | no |
| `summary` | string | yes |

Schema as the model receives it:

```json
{
  "additionalProperties": false,
  "description": "Arguments for record_security_finding.",
  "properties": {
    "title": {
      "maxLength": 120,
      "minLength": 5,
      "title": "Title",
      "type": "string"
    },
    "severity": {
      "enum": [
        "low",
        "medium",
        "high",
        "critical"
      ],
      "title": "Severity",
      "type": "string"
    },
    "related_cve_id": {
      "anyOf": [
        {
          "pattern": "^CVE-\\d{4}-\\d{4,}$",
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "default": null,
      "title": "Related Cve Id"
    },
    "summary": {
      "maxLength": 1000,
      "minLength": 10,
      "title": "Summary",
      "type": "string"
    }
  },
  "required": [
    "title",
    "severity",
    "summary"
  ],
  "title": "SecurityFindingInput",
  "type": "object"
}
```

**Output contract**

| field | type | required |
|---|---|---|
| `finding_id` | string | yes |
| `title` | string | yes |
| `severity` | `low` / `medium` / `high` / `critical` | yes |
| `related_cve_id` | string or null | no |
| `summary` | string | yes |
| `recorded_at` | string | yes |
| `proposed_by` | string | yes |
| `confirmed` | boolean | yes |

## Examples

### 1. How severe is CVE-2025-68664?

**User question:** How severe is CVE-2025-68664?

**Route:** `tool` (rule_router) — The question names CVE-2025-68664, which the corpus cannot hold.

**Tool called:** `lookup_cve`

**Input:**

```json
{
  "cve_id": "CVE-2025-68664"
}
```

**Result:**

```json
{
  "cve_id": "CVE-2025-68664",
  "cvss_score": 8.2,
  "cvss_severity": "HIGH",
  "cvss_source": "nvd@nist.gov",
  "cvss_type": "Primary",
  "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:L/A:N",
  "cvss_version": "3.1",
  "cwe_ids": [
    "CWE-502"
  ],
  "description": "LangChain is a framework for building agents and LLM-powered applications. Prior to versions 0.3.81 and 1.2.5, a serialization injection vulnerability exists in LangChain's dumps() and dumpd() functions. The functions do not escape dictionaries with 'lc' keys when serializing free-form dictionaries. The 'lc' key is used internally by LangChain to mark serialized objects. When user-controlled data contains this key structure, it is treated as a legitimate LangChain object during deserialization rather than plain user data. This issue has been patched in versions 0.3.81 and 1.2.5.",
  "last_modified": "2026-06-17T09:59:23.937000",
  "published": "2025-12-23T23:15:44.933000",
  "reference_urls": [
    "https://github.com/langchain-ai/langchain/commit/5ec0fa69de31bbe3d76e4cf9cd65a6accb8466c8",
    "https://github.com/langchain-ai/langchain/commit/d9ec4c5cc78960abd37da79b0250f5642e6f0ce6",
    "https://github.com/langchain-ai/langchain/pull/34455",
    "https://github.com/langchain-ai/langchain/pull/34458",
    "https://github.com/langchain-ai/langchain/releases/tag/langchain-core%3D%3D0.3.81",
    "https://github.com/langchain-ai/langchain/releases/tag/langchain-core%3D%3D1.2.5",
    "https://github.com/langchain-ai/langchain/security/advisories/GHSA-c67j-w6g6-q2cm"
  ],
  "retrieved_at": "2026-08-11T11:32:47.657000",
  "source": "NVD CVE API 2.0",
  "source_url": "https://nvd.nist.gov/vuln/detail/CVE-2025-68664",
  "vuln_status": "Analyzed"
}
```

**Final answer:**

CVE-2025-68664 has a high severity with a CVSS score of 8.2, as rated by the National Vulnerability Database (nvd@nist.gov) using the CVSS version 3.1. This vulnerability affects LangChain versions prior to 0.3.81 and 1.2.5 and involves a serialization injection issue. The record was retrieved on 2026-08-11.

**Why tool is better than retrieval:**

Nothing in the corpus can answer this, and a knowledge base could not
be made to.

The six indexed documents are the OWASP LLM Top 10 2025 edition and
its companions. This CVE was published on 2025-12-23 and last modified
on 2026-06-17, long after the guidance was written. A document that
did mention it would still carry whatever score it had on the day it
was written.

The second reason is subtler and is the one that decided the design.
NVD scores this record 8.2 and the CNA that reported it scores the
same record 9.3 - a gap wide enough to move it between severity bands
in most triage policies. A chunk of text holds one number and no way
to say whose it is. The tool returns the number together with its
scorer, and the answer names both.

### 2. What is the status of CVE-2024-5565?

**User question:** What is the status of CVE-2024-5565?

**Route:** `tool` (rule_router) — The question names CVE-2024-5565, which the corpus cannot hold.

**Tool called:** `lookup_cve`

**Input:**

```json
{
  "cve_id": "CVE-2024-5565"
}
```

**Result:**

```json
{
  "cve_id": "CVE-2024-5565",
  "cvss_score": 8.1,
  "cvss_severity": "HIGH",
  "cvss_source": "reefs@jfrog.com",
  "cvss_type": "Secondary",
  "cvss_vector": "CVSS:3.1/AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:H/A:H",
  "cvss_version": "3.1",
  "cwe_ids": [
    "CWE-94"
  ],
  "description": "The Vanna library uses a prompt function to present the user with visualized results, it is possible to alter the prompt using prompt injection and run arbitrary Python code instead of the intended visualization code. Specifically - allowing external input to the library\u2019s \u201cask\u201d method with \"visualize\" set to True (default behavior) leads to remote code execution.",
  "last_modified": "2026-06-17T08:16:12.200000",
  "published": "2024-05-31T15:15:09.673000",
  "reference_urls": [
    "https://research.jfrog.com/vulnerabilities/vanna-prompt-injection-rce-jfsa-2024-001034449/"
  ],
  "retrieved_at": "2026-08-11T11:33:08.003000",
  "source": "NVD CVE API 2.0",
  "source_url": "https://nvd.nist.gov/vuln/detail/CVE-2024-5565",
  "vuln_status": "Deferred"
}
```

**Final answer:**

The status of CVE-2024-5565 is "Deferred." This information was retrieved on 2026-08-11.

**Why tool is better than retrieval:**

The record is from 2024, so age is not the argument here. Its NVD
status is Deferred, meaning NVD has stopped enriching it.

Status describes how the record is being processed, not what the
vulnerability is, and it changes while the vulnerability does not.
The same identifier has been Awaiting Analysis, Analyzed and Deferred
at different times, and will change again. A static document records
the state on one day and cannot be told that day has passed.

### 3. What do we know about CVE-2023-99999?

**User question:** What do we know about CVE-2023-99999?

**Route:** `tool` (rule_router) — The question names CVE-2023-99999, which the corpus cannot hold.

**Tool called:** `lookup_cve`

**Input:**

```json
{
  "cve_id": "CVE-2023-99999"
}
```

**Result:**

```json
{
  "success": false,
  "error_code": "not_found",
  "error_message": "NVD holds no record for CVE-2023-99999."
}
```

**Final answer:**

The lookup_cve tool returned no result (not_found). NVD holds no record for CVE-2023-99999.

**Why tool is better than retrieval:**

This identifier is well formed and does not exist.

Retrieval that finds nothing cannot tell "not in these documents"
apart from "not real". Both come back as an absence, and the HW4
refusal sentence is the same in either case - which is a problem,
because the two mean different things to whoever asked.

Asking the authority settles it. NVD answers with an empty result,
and the assistant can say the identifier is not registered rather
than that it has no information.

### 4. Record a finding that our agent is exposed to CVE-2025-68664.

**User question:** Record a finding that our agent is exposed to CVE-2025-68664.

**Route:** `tool` (cli) — Called directly: no router proposes a write.

**Tool called:** `record_security_finding`

**Input:**

```json
{
  "related_cve_id": "CVE-2025-68664",
  "severity": "high",
  "summary": "Our agent deserializes prompts from user input, which is the pattern this CVE exploits.",
  "title": "LangChain deserialization affects our agent"
}
```

**Result:**

```json
{
  "confirmed": true,
  "created": false,
  "finding_id": "find_e83f63a1cff0",
  "proposed_by": "cli",
  "recorded_at": "2026-08-12T12:12:01.591833Z",
  "related_cve_id": "CVE-2025-68664",
  "severity": "high",
  "summary": "Our agent deserializes prompts from user input, which is the pattern this CVE exploits.",
  "title": "LangChain deserialization affects our agent"
}
```

**Final answer:**

A high severity finding titled "LangChain deserialization affects our agent" has been recorded, confirming that our agent is exposed to CVE-2025-68664. The issue arises because our agent deserializes prompts from user input, which is the exploitation pattern of this CVE. This finding was confirmed and recorded on 2026-08-12T12:12:01.591833Z.

**Why tool is better than retrieval:**

Retrieval answers questions. It cannot make anything true.

This request is not a question at all, and the comparison is between
a tool and no tool rather than a tool and retrieval. Without one the
assistant can only tell the user what to write down somewhere else.
With one the record exists, carries an identifier derived from its
own content, and states who proposed it and that a human confirmed
it.

The identifier is what makes the call safe to repeat. Submitting the
same finding twice appends nothing and returns the first record, so
a retry after a timeout leaves one row rather than two.

### 5. How do I prevent prompt injection?

**User question:** How do I prevent prompt injection?

**Route:** `retrieval` (rule_router) — The question names no CVE identifier.

**Tool called:** none. The indexed documents answered.

**Result:** chunks retrieved from the indexed documents

- `owasp_llm01_prompt_injection_chunk_002` — score 0.6420
- `owasp_llm01_prompt_injection_chunk_001` — score 0.6443
- `owasp_llm01_prompt_injection_chunk_004` — score 0.6084
- `owasp_llm01_prompt_injection_chunk_003` — score 0.5336
- `owasp_llm01_prompt_injection_chunk_008` — score 0.6729

Grounded: True

**Final answer:**

Preventing prompt injection is challenging due to the inherent nature of generative AI and the stochastic processes involved. While fool-proof prevention methods are unclear, mitigation strategies include building safeguards into system prompts and input handling to reduce the impact of prompt injections. Additionally, ongoing updates to the model’s training and safety mechanisms are necessary, especially to prevent jailbreaking, a severe form of prompt injection where safety protocols are disregarded. Techniques like Retrieval Augmented Generation (RAG) and fine-tuning improve output relevance and accuracy but do not fully mitigate prompt injection vulnerabilities. Therefore, a combination of prompt design, input validation, and continuous model safety updates is recommended to manage these risks effectively [owasp_llm01_prompt_injection_chunk_002][owasp_llm01_prompt_injection_chunk_003][owasp_llm01_prompt_injection_chunk_008].

**Why tool is better than retrieval:**

The counter-example, and the reason the router exists.

No identifier appears, and the question asks about a class of risk
rather than one record. lookup_cve takes an identifier and cannot
search by keyword, so it has nothing to offer here. The rule router
declines because it finds no identifier; the model declines because
the schema tells it not to use the tool for a class of risk.

Retrieval answers from five chunks of LLM01 and cites three of them.
A tool that fired here would replace a grounded answer with nothing.

## What the tool layer refuses

Each row is a real call. None of them reached NVD or the log:
validation runs before the source is touched.

| what was proposed | arguments | code | message |
|---|---|---|---|
| An identifier that is not the right shape. | `{"cve_id": "CVE-23-1"}` | `validation_error` | cve_id: String should match pattern '^CVE-\d{4}-\d{4,}$' |
| A year before the CVE program existed. | `{"cve_id": "CVE-1998-0001"}` | `validation_error` | cve_id: Value error, CVE year 1998 is out of range (1999-2027). |
| A required field left out. | `{}` | `validation_error` | cve_id: Field required |
| A search phrase smuggled in beside the identifier. | `{"cve_id": "CVE-2025-68664", "keyword": "prompt injection"}` | `validation_error` | keyword: Extra inputs are not permitted |
| A write proposed without human confirmation. | `{"severity": "high", "summary": "Our agent deserializes prompts from user input.", "title": "LangChain deserialization affects our agent"}` | `not_confirmed` | record_security_finding changes state and needs confirmation. |

## Which tool each router proposes

The same questions, routed twice. Neither router executes anything
here; only the proposal is shown.

| question | rules propose | model proposes |
|---|---|---|
| How severe is CVE-2025-68664? | `lookup_cve` | `lookup_cve` |
| What is the status of CVE-2024-5565? | `lookup_cve` | `lookup_cve` |
| What do we know about CVE-2023-99999? | `lookup_cve` | `lookup_cve` |
| Record a finding that our agent is exposed to CVE-2025-68664. | `lookup_cve` | `lookup_cve` |
| How do I prevent prompt injection? | retrieval | retrieval |
| Log a high severity finding titled 'LangChain deserialization affects our agent': our agent deserializes prompts from user input, which is the pattern CVE-2025-68664 exploits. | `lookup_cve` | `record_security_finding` |

## Notes

## When the tool is the right source

The CVE lookup tool is useful where retrieval from the indexed corpus is
not enough. Three conditions produce that, and each example in this report
turns on one of them.

### Some values change after the corpus is indexed

`CVE-2024-5565` is a 2024 vulnerability whose current NVD status is
`Deferred`, meaning NVD is no longer prioritizing it for enrichment.

That status describes how NVD is processing the record. It changes without
the vulnerability itself changing, and the same identifier has been
`Awaiting Analysis`, `Analyzed` and `Deferred` at different times.

A static corpus can only hold the state on the day it was written. The tool
asks the source at the moment the value is needed.

### Metadata is invisible to a semantic search

The retrieval pipeline embeds chunk text. Structured fields stored beside a
document are not embedded and can't be reached by similarity, even when
they sit in the same file.

Severity, processing status and CWE mappings are all such fields.
`lookup_cve` returns them as fields rather than hoping a sentence somewhere
happens to mention them.

### A corpus can't hold a row per identifier

The identifier space is open-ended: hundreds of thousands of CVE records
exist and new ones are minted continuously.

Indexing a document per identifier would turn the knowledge base into a
copy of a vulnerability database. The corpus is suited to knowledge that
changes slowly - classes of risk, attack patterns, mitigation guidance -
and the tool handles point lookups.

### Retrieval wins where the key space is closed

None of the three conditions holds for:

> How do I prevent prompt injection?

There is no identifier, and the question is about a class of risk.
`lookup_cve` accepts an identifier and offers no keyword or semantic search
over security concepts, so it has nothing to contribute. Both routers leave
the question on the retrieval path.

The boundary is deliberate:

| Need | Better source |
|---|---|
| Security concepts and mitigation guidance | retrieval |
| Current CVE metadata | tool |
| Exact structured CVE fields | tool |
| Lookup by CVE identifier | tool |

## CVSS: one vulnerability can have multiple scores

Working with real responses exposed a normalization problem that no plan
anticipated. One CVE record can carry several CVSS assessments from
different organizations. NVD labels its own as `Primary` and the reporting
CNA's as `Secondary`, and the values differ:

| record | Primary | Secondary |
|---|---|---|
| CVE-2025-68664 | 8.2 (nvd@nist.gov) | 9.3 (security-advisories@github.com) |
| CVE-2025-67644 | 7.8 (nvd@nist.gov) | 7.3 (security-advisories@github.com) |
| CVE-2026-34070 | none | 7.5 (security-advisories@github.com) |
| CVE-2024-5565 | none | 8.1 (reefs@jfrog.com) |

Taking the first entry is unsafe. On `CVE-2025-68664` the secondary entry
is listed first, so

    metrics["cvssMetricV31"][0]

returns 9.3 where NVD's own analysis says 8.2 - a gap wide enough to move
the record between severity bands in most triage policies, produced by a
line that looks correct.

Always taking `Primary` is not sufficient either. Two of the four records
carry no `Primary` at all.

The selection therefore prefers `Primary` and falls back to another
assessment when there is none. `CveRecord` keeps `cvss_source` and
`cvss_type` beside the score, so a number is never presented without its
author, and the answer prompt requires the scorer to be named. It is:

> a CVSS score of 8.2, which is classified as HIGH severity according to
> the NVD (nvd@nist.gov)

One further constraint came from the same responses. The `metrics` object
also holds `ssvcV203`, CISA's decision model, which exposes no
`baseScore`. Selection is restricted to keys beginning with `cvssMetric`,
which excludes it.

## The routers differ only when the request is an action

On the five report questions the rule-based and the model-based routers
make the same decision. A sixth question separates them.

> Record a finding that our agent is exposed to CVE-2025-68664.

This is a request to act, and both routers propose `lookup_cve`.

The rule-based router does so because it finds an identifier and looks for
nothing else. Its rules cannot distinguish a question about a CVE from a
request to record one.

For the model, two observations bound what can be said:

- given this request, which supplies none of the three fields the write
  tool requires, it proposed the read tool;
- given a request that supplies `title`, `severity` and `summary`, it
  proposed the write tool and filled every argument from the user's own
  words, inventing nothing.

The second result is consistent with the model declining to invent required
arguments. It's one run of one model on one pair of requests, and the
reasoning was not observed, so this is the most economical explanation
rather than a measured cause.

Execution did not follow. The confirmation gate refused the proposal,
because no human had approved it.

The router's system message was edited once after this case was seen: the
original described only questions and had no notion of a request to act.
Re-running produced the same decision. The behavior above is therefore
attributed to the tool contract rather than to that edit.

An unresolved case sits here. When a user asks for an action but omits
required information, the right response is usually a clarifying question,
not a different route. The current orchestration layer has no way to ask
one.

## Three mechanisms, and only two of them are controls

The write path involves three things that are easy to conflate.

**`extra="forbid"` is a control.** An argument the tool never declared is
rejected before anything runs, so a search phrase or a path can't be
smuggled in beside a valid identifier.

**Required fields are not a control.** They describe what a valid call
looks like. A model is free to invent them, and nothing in this system
prevents that. The observation above is consistent with a model choosing
not to; it's not evidence that it can't.

**The confirmation gate governs the action.** A valid, fully populated
write proposal still changes nothing until a human approves it. The gate is
checked before the arguments, so a perfectly formed unconfirmed write is
refused for the right reason.

The identifier is what makes the confirmed call safe to repeat. It's
derived from the content of the finding, so submitting the same finding
twice appends nothing and returns the first record with its original
timestamp. A retry after a timeout leaves one row rather than two, and the
regenerated report shows the same record as the committed one.

## Known limitations

- **The rule-based router reads one identifier and nothing else.** It
  cannot tell a lookup question from a request to record a finding, and it
  takes the first identifier when a question names two.
- **One model, one temperature, one cached decision per question.**
  Routing variance across repeated runs was not measured.
- **Six routing questions.** Enough to show one behavioral difference
  between the routers, not enough to say how often they disagree.
- **`configurations` is cached whole.** Each of these records affects one
  product, so the field is small. A vulnerability spanning hundreds of
  products would produce a much larger cached response.
- **Faithfulness is checked by hand.** The code verifies that a call was
  validated and that a result was normalized. Whether every sentence of an
  answer follows from the record it read was checked by eye.
- **The write tool appends to a local file.** Authorization, retention,
  storage permissions and who may confirm a write are all outside it.

