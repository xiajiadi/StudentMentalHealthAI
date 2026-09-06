# RAG Technical Decision V1

Document Version: 1.0  
Status: PROVISIONALLY_FROZEN  
Date: 2026-09-04  
Depends on: Contract v0.1.0 FROZEN

This document freezes the Round 1 engineering boundary for `05_rag-engine`.
It does not alter a root Contract, establish a psychological interpretation,
or approve real student data for use.

## 1. Boundary and outputs

`04_knowledge-pipeline` ends at contract-valid `knowledge.v1` records and
review-gated `embedding_ready.jsonl`. This module owns:

```text
embedding -> index -> dense/sparse retrieval -> fusion -> rerank
          -> layer/metadata routing -> context -> citation -> trace -> evaluation
```

The public-facing module result is a `RetrievalResult`, `ContextBundle`, and
`CitationBundle`. It does not generate an answer, rewrite a query with an LLM,
interpret a theta/band as a diagnosis, or change an Assessment result.

## 2. Frozen Contract handling

The root `knowledge.v1`, `assessment.v1`, `config.v1`, `logging.v1`, and API
assets remain read-only inputs. The module uses an internal domain model for
retrieval-only fields such as normalized layer and stage scores. It does not
add those fields to the frozen schemas or modify `CONTRACTS.md`.

The actual Knowledge Round 1 export has `metadata.layer=knowledge`, while its
document export retains `category=policy`, `theory`, or
`practice_guidance`. The loader joins those two existing outputs and maps them
to the internal layers `policy`, `theory`, and `intervention`. This avoids
guessing a new upstream field and keeps the mapping auditable.

## 3. Provider decisions

### 3.1 Embedding

The primary adapter is `BGEM3EmbeddingProvider` over FlagEmbedding's current
`BGEM3FlagModel`. It uses `encode_queries()` for queries and
`encode_corpus()` for passages. BGE-M3 dense output is 1024-dimensional. The
adapter also exposes lexical weights when the installed provider returns them;
the learned sparse path is optional because this host has CPU-only Torch.

`MockEmbeddingProvider` is deterministic and is used only for unit tests and
provider-independent tests. It is never reported as BGE-M3 evidence.

### 3.2 Dense store

`ChromaVectorStore` uses the current Python client, `PersistentClient`, a
collection with `hnsw:space=cosine`, explicit query embeddings, metadata
filters, and persisted local data. Chroma is the required Dense baseline and
is hidden behind `VectorStoreProvider`.

### 3.3 Advanced vector store

`QdrantVectorStore` uses qdrant-client local persistent mode. It supports a
dense named vector, an optional sparse named vector, payload filtering, and
the current `query_points` prefetch/RRF API. Qdrant is an advanced provider
PoC, not a replacement for the required Chroma baseline.

### 3.4 Classical sparse retrieval

`BM25SRetriever` delegates indexing and scoring to BM25S. The project owns
only a small deterministic tokenization adapter that separates CJK characters
and ASCII terms so exact Chinese terminology can be tested. It does not
reimplement BM25 mathematics.

### 3.5 Fusion and reranking

The cross-provider baseline uses a thin RRF component. It follows the
position-based formula `sum(1 / (k + rank))` with zero-based ranks and keeps
the dense and sparse scores intact. When Qdrant hybrid is available, the
Qdrant provider can use its native RRF query.

`BGERerankerProvider` uses FlagEmbedding's current `FlagAutoReranker` API and
is called only for the configured candidate pool. `NoOpReranker` is explicit;
it never pretends to be a model run.

## 4. Configuration and lifecycle

Candidate and final limits are named configuration fields:
`dense_candidate_k`, `sparse_candidate_k`, `fusion_candidate_k`,
`rerank_candidate_k`, and `final_k`. The Round 1 values in
`config/rag.v1.json` are a demo baseline, not optimal values or an SLA.

Providers load model weights lazily once per provider instance. Cache paths
come from environment variables and default to the machine's D-drive cache
configuration; model files are not committed. A provider load failure is
surfaced as `ProviderUnavailable`, and no random vector fallback is allowed.

Round 1 does not promise high concurrency. Model instances are process-local;
callers should share a provider instance within a process and put a separate
worker/process boundary around providers if later concurrency work requires
it.

## 5. Index identity and reindex policy

The index ID is derived from the eligible corpus fingerprint, embedding model
name/revision, provider version, store, distance, and canonical config. The
observational timestamp is not part of the ID. Rebuilding the same corpus with
the same model and config therefore resolves to the same identity.

Reindex is required when:

| Change | Required action |
| --- | --- |
| embedding model or revision | new index and full re-embed |
| embedding dimension | new collection/index; old index is incompatible |
| eligible chunk ID/text/content hash | new corpus fingerprint and full rebuild |
| `context_text` | full re-embed because it is the passage input |
| store or distance | new store/collection and new manifest |
| retrieval-only candidate limits | no re-embed; rerun retrieval/evaluation |

The `IndexManifest` records the values needed to make this decision explicit.
No application startup path silently creates a random index.

## 6. Eligibility, routing, and privacy

Only rows already present in the Knowledge pipeline's publishable embedding
export and satisfying `review_status=approved` and `rights_status=verified`
are indexed. Pending, rejected, unknown-rights, or otherwise ineligible rows
are counted as exclusions and cannot be returned by a provider.

`DeterministicQueryBuilder` accepts structured Assessment fields, role,
population, dimension, topic, intent, and an optional user query. It emits a
structured `RetrievalPlan`; it does not infer clinical meaning from theta or
band values. It also rejects subject identifiers and obvious direct identity
tokens before constructing queries.

Layer routing is explicit: `policy`, `theory`, and `intervention` can be
selected individually or searched with separate quotas. Default filters retain
role, population, review, rights, and risk scope constraints.

Subject IDs are kept only as trace linkage when supplied by the orchestration
boundary. They are never embedded, indexed, or concatenated into query text.
No real student data is used in Round 1.

## 7. Trace, context, and citation

Every service search creates a structured trace with raw/built query,
RetrievalPlan, filters, dense/sparse/fusion/rerank/final stages, provider
versions, index/corpus versions, and latency components. Each stage uses
distinct `dense_score`, `sparse_score`, `fusion_score`, and `rerank_score`
fields.

`CitationBundle` is assembled from retrieved Knowledge metadata. Each `S<N>`
entry binds to `chunk_id`, `document_id`, title, organization, locator, and
source file/URL. `ContextBundle` uses the same order as the citation bundle;
the LLM is not involved in source generation.

## 8. Evaluation

The deterministic harness compares Dense, BM25S, Dense+Rerank, and, when
available, Hybrid and Hybrid+Rerank on the same golden query set. It reports
Hit@1/3/5, Recall@5/10, Precision@5, MRR, nDCG@5/10, and P50/P95 latency.
The set includes lexical, semantic, policy, theory, intervention,
role-specific, and negative queries. Ragas is studied as a future
LLM-judgement reference only; it is not a Round 1 runtime dependency or the
sole acceptance criterion.

## 9. Open-source research evidence

Research was performed against the current public references on 2026-09-04.
Exact revisions and studied files are listed in `THIRD_PARTY_NOTICES.md`.
No third-party repository is copied into this module.
