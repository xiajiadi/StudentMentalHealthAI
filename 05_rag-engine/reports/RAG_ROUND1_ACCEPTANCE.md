# RAG Round 1 Acceptance

Evidence date: 2026-09-05
Module: 05_rag-engine
Contract: root v0.1.0 FROZEN

## 1. Conclusion

**Initial status: PARTIAL PASS** for the local Round 1 module scope.

The initial report verified the provider-neutral retrieval path, Knowledge
eligibility gate, deterministic query planning, BM25S baseline, real BGE-M3 +
Chroma dense path, real BGE-M3 + BM25S hybrid path, Qdrant PoC,
citation/context assembly, trace model, benchmark harness, and frozen-contract
tests, but left the BGE reranker gate blocked because its model weights were
not yet available in the configured cache. The closure evidence below records
the subsequent official model acquisition, real load/score probe, reranker
integration, and complete rerun. The host has CPU-only Torch (2.14.0+cpu,
CUDA unavailable). No Mock result is presented as BGE evidence.

This is an engineering acceptance of the synthetic/authorized Round 1 corpus;
it is not clinical validation, expert approval of a real corpus, or production
release acceptance.

## 2. Implemented scope

- EmbeddingProvider with real FlagEmbedding BGE-M3 adapter, explicit output
  shape checks, optional lexical-weight output, lazy model lifecycle, and no
  random fallback;
- provider-neutral VectorStoreProvider with Chroma persistent dense storage,
  Qdrant local named dense/sparse vectors, and native Qdrant RRF PoC;
- BM25S 0.3.11 lexical baseline with a project-owned CJK-bigram/ASCII tokenizer,
  zero-score suppression, persistent save/load, and a stable lexical manifest;
- deterministic QueryBuilder and RetrievalPlan; no LLM rewrite, HyDE,
  MultiQuery, Self-RAG, GraphRAG, or answer generation;
- policy/theory/intervention layer routing and role/population/risk/review/rights
  eligibility filters;
- stable IndexBuilder/IndexManifest with corpus/model/store/config identity,
  stale chunk cleanup, and explicit rebuild conditions;
- stage-specific RetrievalTrace scores and timings;
- ContextBuilder and CitationBundle with identical order and source bindings;
- deterministic IR evaluation for Hit@1/3/5, Recall@5/10, Precision@5,
  MRR, nDCG@5/10, and P50/P95 latency.

## 3. Corpus and data boundary

Input: 04_knowledge-pipeline/data/published/round1/embedding_ready.jsonl.

| Check | Result |
| --- | ---: |
| Eligible Knowledge chunks | 14 |
| Excluded rows | 0 |
| Knowledge documents joined for layer mapping | 7 |
| Golden queries | 30 |
| Negative queries | 2 |
| Missing relevant chunk IDs | 0 |

Only rows already present in the upstream embedding-ready export and carrying
review_status=approved, rights_status=verified, role scope, population, and
risk scope were indexed. Assessment data is used only as a synthetic query
input. No names, student identifiers, raw responses, consultation records, or
real student data were indexed.

## 4. Real provider evidence

### BGE-M3

FlagEmbedding 1.4.2 imports successfully and the adapter matches the current
BGEM3FlagModel, encode_queries, and encode_corpus boundary. The real
BAAI/bge-m3 snapshot (`5617a9f61b028005a4858fdac845db406aefb181`) was loaded
offline from the configured D-drive cache; CPU inference produced
1024-dimensional dense vectors and non-empty lexical weights. Real BGE-M3 +
Chroma Dense benchmark: **PASS**.

Sparse observation: the final benchmark's real-provider probe produced one
non-empty sparse row with 5 non-zero lexical terms. The output is exposed by
the provider and recorded in the runtime report; Round 1 does not claim that
BGE lexical weights are the production hybrid scorer.

### Chroma

Chroma 1.5.9 PersistentClient storage, cosine collection, explicit query
embeddings, metadata filtering, upsert, and retrieval were executed in an
integration test using deterministic test-only vectors. The full benchmark
also built and queried the persistent Chroma collection with real BGE-M3
vectors. Chroma adapter: **INTEGRATED**; BGE+Chroma Dense evidence: **PASS**.

### Qdrant

Qdrant client 1.19.0 local mode was executed with named dense and sparse
vectors, payload filters, prefetch, and native RRF. This remains a **POC**
using test-only vectors; it is not the production BGE dense/sparse benchmark.

### BGE reranker

FlagEmbedding 1.4.2 and the current `FlagAutoReranker.from_finetuned` API were
exercised at the adapter boundary. The official
[BAAI/bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3)
snapshot `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` was loaded offline from
`D:\Dev\caches\huggingface`; the 2,271,071,852-byte safetensors file matches
SHA-256
`d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286`.
The model is Apache-2.0 licensed, ran on CPU with fp32, and produced a real
score probe. The benchmark runtime report records `status=ok`, observed load
latency 2742.689 ms, score-probe latency 3112.167 ms, and probe score
0.0000163246. Dense+Rerank and Hybrid+Rerank are therefore **PASS** for the
Round 1 engineering gate; no hand-written ranking is used.

## 5. Citation and trace evidence

The closure benchmark contains dense, sparse, fusion, rerank, and final stages
where applicable. Rerank-stage items record `before_rank`, `after_rank`, the
real rerank score, candidate pool membership, provider version/revision, and
latency. The context and CitationBundle preserve the same final order. For
example, the Dense+Rerank trace for the policy query
`日常教学怎样营造尊重和保密的支持环境` has final context `[S1, S2, S3, S4,
S5]`; S1 is `CHUNK_73dea0ea11c13057ae5b`, document
`KB_1814fbd0be27f07bbe9c`, titled `学校心理健康教育工作指引（合成夹具）`,
with locator `file:policy_copy.md; section:学校心理健康教育工作指引;
pages:unknown`. The citation regression asserts that citation IDs equal the
final context IDs in order.

## 6. Negative-query evidence

GQ_029 (校园食堂菜单和公交线路) and GQ_030 (量子计算机编程接口) have no
relevant chunks. Across the six benchmark configurations, BM25S returned 3/3
candidates, Mock dense returned 5/3, and each real BGE dense, hybrid, and
reranked path returned 5/3 for GQ_029/GQ_030 respectively. The reranker
reordered candidates but did not abstain; no formal abstention policy is
claimed. The deterministic relevance metrics remain zero for these negative
rows.

## 7. Benchmark

The full 30-query result is in reports/rag_eval_round1.json, with the readable
summary in reports/RAG_RETRIEVAL_BENCHMARK.md.

| Configuration | Status | Hit@1 | Recall@5 | MRR | nDCG@5 | P50 ms | P95 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25S | PASS | 0.867 | 0.892 | 0.900 | 0.891 | 0.633 | 1.151 |
| Dense (Mock; test-only) | PASS | 0.767 | 0.825 | 0.814 | 0.799 | 10.104 | 12.024 |
| Dense (BGE-M3) | PASS | 0.933 | 0.900 | 0.933 | 0.919 | 262.804 | 392.259 |
| Dense+Rerank (BGE) | PASS | 0.900 | 0.900 | 0.917 | 0.910 | 1926.742 | 2635.553 |
| Hybrid (BGE-M3 + BM25S) | PASS | 0.933 | 0.908 | 0.933 | 0.923 | 256.747 | 382.123 |
| Hybrid+Rerank (BGE + BM25S) | PASS | 0.867 | 0.917 | 0.900 | 0.913 | 2007.943 | 3027.209 |

BM25S is higher than the test-only Mock dense smoke on this small dataset. The
reranker is real and integrated, but it did not improve synthetic Hit@1, MRR,
or nDCG over the corresponding non-reranked paths; Hybrid+Rerank improved
Recall@5 and Precision@5 while adding approximately 7–8x CPU latency. This is
recorded as evidence for evaluation-driven enable/disable decisions, not as a
claim that reranking should be the default. These metrics are not clinical
validation or production quality evidence. Qdrant real BGE dense+sparse native
RRF remains a P1 follow-up and is not a Full PASS blocker.

## 8. Contract and tests

The root Frozen Contract files were read as inputs and not modified by this
module. knowledge.v1 projections for all 14 eligible rows validate against the
root schema. The retrieval API envelope validates against the frozen OpenAPI
RetrievalEnvelope schema.

Executed locally:

    uv sync --offline --extra runtime --extra test
    .venv\Scripts\python.exe -m compileall -q src tests
    $env:SMHAI_RUN_RERANKER_INTEGRATION='1'
    .venv\Scripts\python.exe -m pytest -q
    22 passed, 3 warnings

    powershell -NoProfile -ExecutionPolicy Bypass -File .\00_architecture\tests\run_contract_checks.ps1
    13 root tests passed, 0 failed; OpenAPI validator OK

The warnings are upstream/deprecation notices from jsonschema and Chroma; they
did not fail the tests. No project Vale configuration was present, so no Vale
pass is claimed.

## 9. Runtime and storage

- Python 3.14.6 on Windows 11;
- Torch 2.14.0+cpu; CUDA unavailable;
- package versions, model revisions, provider health, and warnings are in
  reports/RAG_RUNTIME_COMPATIBILITY.md;
- BGE-M3 and BGE reranker cache assets are kept under
  D:\Dev\caches\huggingface and are not repository files;
- local index artifacts are under 05_rag-engine/data/indexes/ and are ignored
  from source delivery;
- GPU performance is not validated because CUDA is unavailable; RTX 3060
  validation is deferred;
- no Git metadata exists in this workspace, so no commit, diff, remote CI, or
  release evidence is claimed.

## 10. Acceptance Closure

Closure date: 2026-09-05

The initial **PARTIAL PASS** was closed by official BGE reranker acquisition and
checksum verification, real offline model load and score probe, current API
verification, Dense+Rerank and Hybrid+Rerank integration, a fresh six-path
30-query benchmark, three query-type before/after traces, negative-query
checks, citation/trace regression, the full module suite, and the root
Contract/Governance suite.

**Final status: PASS — Round 1 engineering acceptance only.**

All Full PASS conditions in the module scope are satisfied. This does not claim
Qdrant real BGE sparse benchmarking, GPU performance, real-student data
validation, clinical validation, expert approval of a real corpus, or release
acceptance. Supporting evidence is in
[`RAG_ROUND1_CLOSURE_EVIDENCE.md`](RAG_ROUND1_CLOSURE_EVIDENCE.md).

## 11. Deferred scope

1. Run the Qdrant dense+sparse/native-RRF benchmark with real BGE outputs as a
   P1 follow-up; the current Qdrant implementation remains a test-only PoC.
2. Validate GPU performance later on the target RTX 3060 environment.
3. Keep human review, rights decisions, safety review, and real/clinical corpus
   approval outside this synthetic Round 1 acceptance.
