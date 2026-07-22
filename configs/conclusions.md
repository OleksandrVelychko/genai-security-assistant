## Conclusions

### Setup
264 chunks from 6 OWASP documents, embedded with
`openai/text-embedding-3-small` (1536-dim), FAISS `IndexFlatIP` over
L2-normalized vectors (cosine similarity). 8 test queries, top-k = 5.

### Score scale
Scores fell into three clear ranges. To find the "irrelevant" floor, one control query 
with nothing to do with the knowledge base ("how to make
sourdough bread") was added to check how low its score goes.

| Query type | Typical top-1 score |
|---|---|
| Direct on-topic question | 0.60 - 0.74 |
| Partial / cross-topic     | 0.40 - 0.55 |
| Off-topic control (bread) | 0.12 - 0.15 |

The index always returns 5 results and never says "no match", so the score is
the only signal of relevance. A cutoff around 0.4-0.5 would separate real
answers from noise on this corpus.

### Where retrieval works well

- **Definitions and direct questions (q1, q2, q3, q5).** When the query asks
  plainly what something is or how to prevent it, the top result always comes
  from the right document, with scores between 0.60 and 0.74. These are the
  easy cases and the retriever handles them cleanly.

- **Cross-document retrieval (q1, q4).** Prompt injection is covered in two
  places - the LLM01 risk page and the dedicated prevention cheat sheet - and
  the results correctly pull from both instead of locking onto a single file.
  The retriever follows the topic, not the document boundary.

- **Recall of rare terms (q8).** The query never mentioned "typoglycemia" or
  "Best-of-N", yet the chunks describing those exact attacks came back near the
  top. Nothing here relies on shared keywords, so this is direct evidence that
  the search matches meaning rather than surface wording.

- **Query wording shapes the ranking (q2).** Adding "and what causes it" to the
  question was enough to lift the chunk about the *root cause* above the one
  with the cleaner definition. The model scores the whole query, so a small
  change in phrasing visibly moves the results - exactly the behavior we want.

### Where retrieval struggles

- **Near-duplicate content (q7).** The same "Improper Output Handling" block is
  copied across three OWASP pages, so all three copies came back as Top-1..3
  with almost identical scores and filled most of the top-k. The answer the
  query actually needed never made it into the list. This is the clearest
  failure in the set.

- **Noise sections (q8, Top-5).** A "Reference Links" block - just a list of
  article titles - was retrieved because it shares the topic, even though it
  contains no real content. Topic overlap alone was enough to rank it, and
  similarity scoring can't tell substance from a link list.

- **PDF page-chunking (q6).** The governance checklist is a PDF split by page,
  so its chunks are labeled "Page 19" instead of a real section name. Without
  a semantic heading the metadata is weaker and the previews read as loose
  fragments rather than self-contained points.

- **Chunk-boundary artifacts (q2, Top-1).** Some chunks begin mid-sentence
  ("user, an earlier invocation..."). This comes from how the text was split in
  HW1, not from retrieval - but it shows up here because a broken chunk is
  harder to read once it's been retrieved.

- **Broad questions return fragments, not a single answer (q2).** The query
  asked two things at once - "what is excessive agency" *and* "what causes it".
  No single chunk covered both: the definition, the root causes and the
  mitigation sat in three separate chunks (the definition was even split across
  two by overlap). Ranking stayed correct - all three were in the top-3 from
  the right document - but Top-1 on its own is an incomplete answer. The wider
  the question, the more the real answer is scattered across the top-k, and the
  less any single result can be trusted as "the" answer. This is a limitation of
  chunk-level retrieval, and it's why HW4's generator will need to synthesize
  across several chunks rather than quote the best match.

### Takeaways for HW3
1. Deduplicate near-identical chunks before or during retrieval.
2. Add a relevance threshold (~0.4) so the system can return "no good match".
3. Improve chunking for the PDF source (semantic sections, sentence snapping).
4. Try hybrid search / reranking to lift specific answers above generic blocks.