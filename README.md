# GenAI Security Assistant — Knowledge Base

Knowledge base for a retrieval-augmented chatbot that answers questions about
securing generative-AI and LLM applications, built from official OWASP sources.

This repository is the first stage (HW1) of an end-to-end RAG assistant:
`raw sources → normalized documents → chunks → metadata → processed knowledge base`.

## Subject area

**GenAI / LLM application security.** The assistant is meant to answer practical
questions such as *"How do I prevent prompt injection?"*, *"What is excessive
agency and how is it mitigated?"* or *"What should a governance checklist cover
before deploying an LLM application?"*

The scope is deliberately narrow: six OWASP documents covering three risk areas
(prompt injection, sensitive information disclosure, excessive agency) plus
cross-cutting governance.

## Sources

All sources are published by OWASP under **CC-BY-SA 4.0** and are attributed in
each chunk's metadata (`publisher`, `source_url`, `license`).

| Document | Type | Format | Risk category |
|---|---|---|---|
| LLM01:2025 Prompt Injection | security_risk | HTML | prompt_injection |
| LLM02:2025 Sensitive Information Disclosure | security_risk | HTML | sensitive_information_disclosure |
| LLM06:2025 Excessive Agency | security_risk | HTML | excessive_agency |
| LLM Prompt Injection Prevention Cheat Sheet | cheat_sheet | Markdown | prompt_injection |
| AI Agent Security Cheat Sheet | cheat_sheet | Markdown | excessive_agency |
| LLM Applications Cybersecurity and Governance Checklist | checklist | PDF | governance |

Sources are declared in `configs/sources.yaml`, not in code, so the pipeline does
not depend on any particular document set.

## Project structure

```text
src/genai_security_assistant/
  config.py                 # settings + source manifest loading
  models/documents.py       # typed pydantic contracts
  ingestion/
    loaders/                # markdown / html / pdf -> sections
      base.py               # loader interface
      markdown.py
      html.py
      pdf.py
    normalization.py        # sections + manifest -> NormalizedDocument
    chunking.py             # structure-aware chunking
    metadata.py             # chunk ids and metadata assembly
    pipeline.py             # orchestration
    validation.py           # quality checks
scripts/
  prepare_knowledge_base.py   # thin CLI: build the knowledge base
  validate_knowledge_base.py  # thin CLI: quality report
data/
  raw/                      # original source documents
  normalized/documents.jsonl
  processed/chunks.jsonl    # HW1 deliverable -> input for HW2 embeddings
configs/
  base.yaml                 # pipeline parameters
  sources.yaml              # source manifest + controlled vocabularies
tests/
  unit/ingestion/
  integration/
```

Business logic lives in the package; `scripts/` only wires it up and prints.

## Pipeline

```text
data/raw/*.{md,html,pdf}
        │
        ▼  loaders      format-specific parsing into sections
        │
        ▼  normalization  + manifest metadata, content_hash, retrieved_at
data/normalized/documents.jsonl
        │
        ▼  chunking     structure-aware splitting with overlap
        │
        ▼  metadata     chunk_id + flattened provenance
data/processed/chunks.jsonl
        │
        ▼  validation   quality report / CI gate
```

## Metadata structure

Every line of `data/processed/chunks.jsonl` is one chunk:

```text
{ "chunk_id": "...", "text": "...", "metadata": { ... } }
```

| Field | Origin | Purpose |
|---|---|---|
| `chunk_id` | generated | `{document_id}_chunk_{index:03d}`, stable and sortable |
| `document_id`, `source_file`, `source_type` | manifest | provenance of the chunk |
| `source_url`, `publisher`, `license` | manifest | attribution (CC-BY-SA requirement) |
| `title`, `section`, `heading_path` | loader | position of the chunk in the document |
| `chunk_index` | generated | order within the document |
| `language`, `domain` | manifest | corpus-level filtering |
| `document_type`, `risk_category` | curator | controlled vocabulary for metadata filtering |
| `doc_version` | document | version stamped by the publisher, `null` if none |
| `retrieved_at`, `content_hash` | pipeline | freshness tracking (SHA-256 of the raw file) |

Metadata falls into four kinds by origin:

- **observed** from the source (`source_url`, `title`, `language`, `source_type`)
- **assigned** by the curator (`document_type`, `risk_category` — controlled
  vocabularies documented at the top of `configs/sources.yaml`)
- **intrinsic** to the document (`doc_version`, `null` when the publisher stamps none)
- **machine-generated** (`chunk_id`, `chunk_index`, `content_hash`, `retrieved_at`)

`content_hash` and `retrieved_at` exist so that a future re-ingestion can detect
which upstream documents actually changed and re-chunk only those.

Controlled vocabularies are enforced, not merely documented: `document_type` and
`risk_category` are `Literal` types in `models/documents.py`, so an unknown value
is rejected at validation time instead of being stored silently.

## Chunking strategy

`chunk_size = 700`, `chunk_overlap = 150`, `min_chunk_size = 200`, strategy
`structure_aware`. Rules, in priority order:

1. **Section boundaries are hard.** Two document sections never share a chunk.
2. Inside a section, whole paragraphs / list items accumulate up to `chunk_size`.
3. An over-long paragraph is split on **sentence** boundaries.
4. An over-long sentence is split on **word** boundaries — never mid-word.
5. Fenced code blocks stay **atomic**; if too long, they split on **line** boundaries.
6. Overlap is built from the **last complete sentences** of the previous chunk,
   so no chunk ever starts mid-sentence.
7. Undersized fragments are folded back at three levels: whole sections before
   chunking, mid-stream fragments during accumulation, trailing fragments after.

This replaces naive fixed-width slicing (`text[start:end]`), which cuts words,
sentences and code examples in half.

## Example chunks

#### owasp_llm01_prompt_injection_chunk_001 (html)

HTML source: clean extraction after page chrome was stripped

```json
{
  "chunk_id": "owasp_llm01_prompt_injection_chunk_001",
  "text": "A Prompt Injection Vulnerability occurs when user prompts alter the LLM’s behavior or output in unintended ways. These inputs can affect the model even if they are imperceptible to humans, therefore prompt injections do not need to be human-visible/readable, as long as the content is parsed by the model.",
  "metadata": {
    "document_id": "owasp_llm01_prompt_injection",
    "source_file": "data/raw/owasp_llm01_prompt_injection.html",
    "source_type": "html",
    "source_url": "https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
    "title": "LLM01:2025 Prompt Injection",
    "section": "LLM01:2025 Prompt Injection",
    "heading_path": [
      "LLM01:2025 Prompt Injection"
    ],
    "chunk_index": 1,
    "language": "en",
    "domain": "genai_security",
    "document_type": "security_risk",
    "risk_category": "prompt_injection",
    "publisher": "OWASP Gen AI Security Project",
    "doc_version": "2025",
    "retrieved_at": "2026-07-18T15:51:25.931554Z",
    "content_hash": "82f21555ca25c2a31989d2f482feefe3856b1344f29e0154210fdf8f176f6827"
  }
}
```

#### owasp_llm01_prompt_injection_chunk_002 (html)

The next chunk of the same document: note the sentence-aligned overlap

```json
{
  "chunk_id": "owasp_llm01_prompt_injection_chunk_002",
  "text": "are imperceptible to humans, therefore prompt injections do not need to be human-visible/readable, as long as the content is parsed by the model.\nPrompt Injection vulnerabilities exist in how models process prompts, and how input may force the model to incorrectly pass prompt data to other parts of the model, potentially causing them to violate guidelines, generate harmful content, enable unauthorized access, or influence critical decisions. While techniques like Retrieval Augmented Generation (RAG) and fine-tuning aim to make LLM outputs more relevant and accurate, research shows that they do not fully mitigate prompt injection vulnerabilities.",
  "metadata": {
    "document_id": "owasp_llm01_prompt_injection",
    "source_file": "data/raw/owasp_llm01_prompt_injection.html",
    "source_type": "html",
    "source_url": "https://genai.owasp.org/llmrisk/llm01-prompt-injection/",
    "title": "LLM01:2025 Prompt Injection",
    "section": "LLM01:2025 Prompt Injection",
    "heading_path": [
      "LLM01:2025 Prompt Injection"
    ],
    "chunk_index": 2,
    "language": "en",
    "domain": "genai_security",
    "document_type": "security_risk",
    "risk_category": "prompt_injection",
    "publisher": "OWASP Gen AI Security Project",
    "doc_version": "2025",
    "retrieved_at": "2026-07-18T15:51:25.931554Z",
    "content_hash": "82f21555ca25c2a31989d2f482feefe3856b1344f29e0154210fdf8f176f6827"
  }
}
```

#### owasp_cs_prompt_injection_prevention_chunk_001 (markdown)

Markdown source: heading path preserved as section context

```json
{
  "chunk_id": "owasp_cs_prompt_injection_prevention_chunk_001",
  "text": "Prompt injection is a vulnerability in Large Language Model (LLM) applications that allows attackers to manipulate the model's behavior by injecting malicious input that changes its intended output. Unlike traditional injection attacks, prompt injection exploits the common design of most LLMs where natural language instructions and data are processed together without clear separation.\n**Key impacts include:**\n- Bypassing safety controls and content filters\n- Unauthorized data access and exfiltration\n- System prompt leakage revealing internal configurations\n- Unauthorized actions via connected tools and APIs\n- Persistent manipulation across sessions",
  "metadata": {
    "document_id": "owasp_cs_prompt_injection_prevention",
    "source_file": "data/raw/owasp_llm_prompt_injection_prevention_cheat_sheet.md",
    "source_type": "markdown",
    "source_url": "https://raw.githubusercontent.com/OWASP/CheatSheetSeries/master/cheatsheets/LLM_Prompt_Injection_Prevention_Cheat_Sheet.md",
    "title": "LLM Prompt Injection Prevention Cheat Sheet",
    "section": "Introduction",
    "heading_path": [
      "LLM Prompt Injection Prevention Cheat Sheet",
      "Introduction"
    ],
    "chunk_index": 1,
    "language": "en",
    "domain": "genai_security",
    "document_type": "cheat_sheet",
    "risk_category": "prompt_injection",
    "publisher": "OWASP Cheat Sheet Series",
    "doc_version": null,
    "retrieved_at": "2026-07-18T15:51:25.964538Z",
    "content_hash": "581a9bb96bc934fa277fde7610b6e05fdd485d79ff617851de99fc1262f56f74"
  }
}
```

#### owasp_llm_governance_checklist_chunk_001 (pdf)

PDF source: ligatures repaired, page-level section

```json
{
  "chunk_id": "owasp_llm_governance_checklist_chunk_001",
  "text": "Overview\nEvery internet user and company should prepare for the upcoming wave of powerful generative\nartificial intelligence (GenAI) applications. GenAI has enormous promise for innovation, efficiency,\nand commercial success across a variety of industries. Still, like any powerful early stage technology,\nit brings its own set of obvious and unexpected challenges.\nArtificial intelligence has advanced greatly over the last  years, inconspicuously supporting a\nvariety of corporate processes until ChatGPT’s public appearance drove the development and use of\nLarge Language Models (LLMs) among both individuals and enterprises. Initially, these technologies",
  "metadata": {
    "document_id": "owasp_llm_governance_checklist",
    "source_file": "data/raw/owasp_llm_governance_checklist.pdf",
    "source_type": "pdf",
    "source_url": "https://genai.owasp.org/resource/llm-applications-cybersecurity-and-governance-checklist-english/",
    "title": "LLM Applications Cybersecurity and Governance Checklist",
    "section": "Page 5",
    "heading_path": [
      "Page 5"
    ],
    "chunk_index": 1,
    "language": "en",
    "domain": "genai_security",
    "document_type": "checklist",
    "risk_category": "governance",
    "publisher": "OWASP Gen AI Security Project",
    "doc_version": null,
    "retrieved_at": "2026-07-18T15:51:26.504796Z",
    "content_hash": "583457f34081dc4487ffc72530aa80e32edef8086637e3d7e3a59cb1a4511426"
  }
}
```


## Quality report

Produced by `scripts/validate_knowledge_base.py`:

```text
Chunks parsed     : 264
Parse errors      : 0
Length min/avg/max: 190 / 491 / 920

Chunks per document:
  owasp_cs_ai_agent_security                   58
  owasp_cs_prompt_injection_prevention         50
  owasp_llm01_prompt_injection                 26
  owasp_llm02_sensitive_information_disclosure 19
  owasp_llm06_excessive_agency                 25
  owasp_llm_governance_checklist               86

Chunks per source type:
  html       70
  markdown  108
  pdf        86

duplicate chunk_id   : OK
empty text           : OK
below min_chunk_size : 1 found
above 1000 characters: OK
unmapped glyphs      : OK
RESULT: PASS
```

Blocking failures (malformed JSON, duplicate ids, empty text) make the script
exit non-zero so it can be used as a CI gate. Soft quality signals (a chunk
slightly below the minimum, suspicious glyphs) are reported but do not fail
the build.

## What worked well

- **Structure-aware chunking.** No chunk starts or ends mid-word or mid-sentence,
  and code examples survive intact. Lengths stay within 190–920 characters.
- **Manifest-driven ingestion.** Adding a source is a YAML edit, not a code change.
- **Typed contracts.** Controlled vocabularies are `Literal` types, so an invalid
  `risk_category` is rejected at validation time rather than silently stored.
- **Provenance from day one.** Every chunk carries its URL, license, version,
  retrieval timestamp and content hash.
- **Problems were found by measurement, not by guessing.** An oversized-overlap
  bug (one chunk reached 1915 characters) and shredded code blocks were both
  caught by inspecting length distributions and the shortest chunks, then locked
  down with regression tests.

## What to improve

- **PDF extraction is the weakest link.** The source PDF embeds fonts without a
  Unicode map, so `fi`/`fl` ligatures and some digits decode to `U+FFFF`.
  Ligatures are repaired heuristically, but lost digits are unrecoverable —
  "Figure 1:" becomes "Figure .:". A different extractor or an OCR fallback
  would be the proper fix.
- **PDF sectioning is page-based.** Without reliable heading detection, `section`
  is only `Page N`, which is weaker context than the HTML/Markdown heading paths.
- **Indented code blocks are not detected.** Only fenced (```) blocks are kept
  atomic; four-space indented code is still treated as prose and split by words.
- **No deduplication.** The LLM01 risk page and the prompt-injection cheat sheet
  overlap in content, so near-duplicate chunks may compete in retrieval.
- **No incremental re-ingestion yet.** `content_hash` is stored but not yet used
  to skip unchanged documents — the natural next step towards a scheduled refresh.
- **Average chunk length (491) sits below the 700 target**, because section
  boundaries end chunks early. This is a deliberate trade-off favoring
  readability over uniform size.
- **The table-of-contents filter is a heuristic.** It keys on dot leaders
  (a period ratio above 0.15) and would miss a contents page styled differently.

## Reproducing

```bash
uv sync
uv run python scripts/prepare_knowledge_base.py
uv run python scripts/validate_knowledge_base.py
uv run pytest -q
```

## HW2 - Semantic retrieval layer

Turns the HW1 chunks into a searchable vector index and answers questions by
semantic similarity:

`chunks.jsonl -> embeddings -> FAISS index -> top-k semantic search`

### Embedding model

Configured in `configs/base.yaml` under `embeddings`. Two interchangeable
providers behind one interface:

| Provider | Model | Dim | Notes |
|---|---|---|---|
| `openai` (default) | `text-embedding-3-small` | 1536 | needs `OPENAI_API_KEY`; also works with OpenRouter (change `base_url`) |
| `sentence_transformers` | `all-MiniLM-L6-v2` | 384 | local, offline; install with `uv sync --extra local-embeddings` |

Chunks and queries are always encoded by the same model. The index records the
model it was built with (`index/index_meta.json`); querying with a different
model fails fast with a rebuild message instead of returning wrong results.

### Setup

    uv sync
    cp .env.example .env      # then add your OPENAI_API_KEY

### Build the index

    uv run python scripts/build_index.py

Writes three files to `index/`: the FAISS index, a chunk snapshot in index
order, and a metadata sidecar.

### Search

    uv run python scripts/retrieval.py --query "How do I prevent prompt injection?"
    uv run python scripts/retrieval.py -q "excessive agency" -k 3

Each result shows `chunk_id`, cosine `score`, `source_file`, `document_id` and a
text preview.

### Evaluation

    uv run python scripts/run_retrieval_examples.py

Runs the queries in `configs/eval_queries.yaml` and regenerates
`outputs/retrieval_examples.md`. Per-query comments live in the query file; the
analysis lives in `configs/conclusions.md` - the report is assembled from both,
so re-running the script reproduces it exactly.

### Layout

    configs/
      eval_queries.yaml     # test queries + manual relevance comments
      conclusions.md        # retrieval analysis (source of truth)
    index/
      faiss.index           # vector index
      chunks.jsonl          # chunks in index order
      index_meta.json       # model, dimension, digest
    scripts/
      build_index.py        # build the index
      retrieval.py          # CLI semantic search
      run_retrieval_examples.py   # regenerate the evaluation report
    src/genai_security_assistant/retrieval/
      embeddings.py         # pluggable embedding providers
      vector_store.py       # FAISS wrapper (cosine search)
      indexing.py           # chunks -> index pipeline
      search.py             # SemanticRetriever
    outputs/
      retrieval_examples.md # generated report (HW2 deliverable)


## HW3 - Retrieval optimization

In progress. This section grows with the assignment.

### Why query vectors are cached

The 264 chunk vectors have lived in `index/faiss.index` since HW2: built
once, read from disk. The eleven test queries were not treated the same way
- every run sent them to the embeddings API and used whatever came back.

Two runs four minutes apart, with no file changed in between, produced
different numbers. The API does not promise identical vectors for identical
input, and the gap was about one part in a thousand. That sounds harmless
until you see what it did to q7:

    run A   rank 5   owasp_llm_governance_checklist / Page 19      0.5014
    run B   rank 5   owasp_llm02 / Incorporate Differential Priv   0.5000

HW3 has to show that a filtered and hybrid pipeline ranks better than the
HW2 baseline. If the ranking also moves on its own between runs, and by
about as much, a better score proves nothing. So query vectors are now
fetched once into `index/query_vectors.npz`, committed, and read from disk,
the same way chunk vectors already are.

The code and the longer explanation are in
`src/genai_security_assistant/retrieval/query_cache.py`. Three properties
are covered by `tests/unit/retrieval/test_query_cache.py` and were also
checked against the real pipeline:

| Property | How it was checked |
|---|---|
| Two runs produce the same report | ran the script twice; only the `Generated:` line differed |
| The reports need no API key | renamed `.env` away and reran; output identical |
| Vectors from another model are refused | loading the cache under a different model name raises |

Two things follow, and both matter when reading the numbers:

- They describe the pipeline given one fixed set of query vectors, not an
  average over everything the API might return. Comparing two pipelines is
  still fair, since both read the same file, but a number quoted on its own
  should be read with that in mind.
- Both reports can be regenerated from a fresh clone with no API key, since
  both sides of the retrieval are now committed.

Known limitation: this fixes the measurement, not the system. A live
service embeds each user query as it arrives, so the variation described
here is still there in production - it has been removed from the experiment
so that the experiment can answer one question at a time.

## License and attribution

Source documents are © OWASP Foundation, licensed **CC-BY-SA 4.0**. Attribution
is preserved per chunk in `metadata.publisher`, `metadata.source_url` and
`metadata.license`. Pipeline code in this repository is the author's own work.
