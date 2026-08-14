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
- **The findings log is committed.** `data/findings.jsonl` is in the
  repository so a regenerated report shows the same record as the committed
  one. That's right for an example and wrong for real use: a log of
  security findings belongs where access to it is controlled.
- **Nothing bounds the size of a response.** The NVD client has a timeout
  and no limit on the body it will read into memory and cache. NVD is a
  trusted source, but `base_url` is configuration, and a different source
  behind it wouldn't be.
