# RAG Round 1 Closure Evidence

Evidence date: 2026-09-05  
Module: `05_rag-engine`  
Contract: root v0.1.0 FROZEN

This is supporting evidence for the Round 1 acceptance closure. The formal
acceptance conclusion remains in
[`RAG_ROUND1_ACCEPTANCE.md`](RAG_ROUND1_ACCEPTANCE.md). This document does not
start Round 2 and does not expand the module's data or safety boundary.

## 1. Initial partial-pass reason

The initial Round 1 report was **PARTIAL PASS** because the BGE reranker
adapter existed but its real model weights were not available in the offline
cache. Consequently, real reranker load, score, candidate before/after
evidence, and the two reranked benchmark configurations were not claimed.
No ranking was hand-written and no Mock result was presented as BGE evidence.

## 2. Official model acquisition and provenance

The current FlagEmbedding reranker API and example usage were checked against
the [official FlagEmbedding reranker documentation](https://github.com/FlagOpen/FlagEmbedding/blob/master/examples/inference/reranker/README.md).
The model source and license were checked against the official
[BAAI/bge-reranker-v2-m3 model card](https://huggingface.co/BAAI/bge-reranker-v2-m3).

| Item | Evidence |
| --- | --- |
| Model | `BAAI/bge-reranker-v2-m3` |
| Snapshot revision | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| Weight file | `model.safetensors`, 2,271,071,852 bytes |
| SHA-256 | `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` |
| License | Apache-2.0 |
| Cache root | `D:\Dev\caches\huggingface` |
| Snapshot path | `D:\Dev\caches\huggingface\models--BAAI--bge-reranker-v2-m3\snapshots\953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| Repository delivery | Model weights are not repository files and were not committed. |

The real BGE-M3 embedding snapshot used for the same closure is
`5617a9f61b028005a4858fdac845db406aefb181`. Both model assets remain on the D
drive cache rather than in the source tree.

## 3. Real reranker load and score probe

The adapter used `FlagAutoReranker.from_finetuned` from FlagEmbedding 1.4.2
and called the concrete provider's real `compute_score` path. Offline health
loading returned `status=ok`, `loaded=true`, device `cpu`, and precision
`fp32`. The same health check generated a numeric score for a real query /
passage pair; the probe score was `0.0000163246`.

The benchmark runtime report records the observed CPU timings:

- load latency: `2742.689 ms`;
- score-probe latency: `3112.167 ms`;
- provider version: `FlagEmbedding:1.4.2`;
- model revision: `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`.

These are one local CPU run's observations, not a performance SLA.

## 4. Rerank before/after evidence

The configured rerank candidate limit is 10 and final K is 5. The trace
candidate pool is smaller when layer and metadata quotas produce fewer eligible
items; the closure samples contain 5–7 candidates and never rerank the whole
corpus. Internal ranks below are zero-based and come from the real rerank
stage. `a -> b` means `before_rank -> after_rank`.

| Query type | Query ID | Dense+Rerank evidence |
| --- | --- | --- |
| Exact keyword | GQ_001 | `CHUNK_8f85f2c0472e21acd2fa 0->0 (0.952325)`; `CHUNK_c3718c65fcf4151af391 1->1 (0.952325)`; `CHUNK_fe0153fc5c3472e79982 3->2 (0.877820)`; `CHUNK_8a23f59abc838d8f66e0 2->3 (0.748809)`; `CHUNK_f4b8d47cca28f33baaf9 4->4 (0.007068)`. |
| Semantic paraphrase | GQ_004 | `CHUNK_8f85f2c0472e21acd2fa 0->0 (0.990080)`; `CHUNK_c3718c65fcf4151af391 1->1 (0.990080)`; `CHUNK_8a23f59abc838d8f66e0 3->2 (0.003409)`; `CHUNK_10c1a30901fe3b68faa7 4->3 (0.000310)`; `CHUNK_f4b8d47cca28f33baaf9 2->4 (0.000310)`. |
| Policy | GQ_005 | `CHUNK_73dea0ea11c13057ae5b 0->0 (0.730757)`; `CHUNK_b34d75824a36a99466fc 1->1 (0.730757)`; `CHUNK_81cfc83a8ee77e0d2fcc 2->2 (0.146810)`; `CHUNK_8f85f2c0472e21acd2fa 4->3 (0.003309)`; `CHUNK_c3718c65fcf4151af391 3->4 (0.003309)`. |

This shows both unchanged positions and real movements. The corresponding
Hybrid+Rerank traces also contain the real rerank stage, candidate pool, and
before/after ranks. The benchmark JSON is the complete machine-readable source
for all trace samples.

## 5. Dense+Rerank result

The real BGE-M3 dense path followed by the real BGE reranker completed all 30
Golden queries with status **PASS**:

| H@1 | Recall@5 | MRR | nDCG@5 | P50 | P95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.900 | 0.900 | 0.917 | 0.910 | 1926.742 ms | 2635.553 ms |

## 6. Hybrid+Rerank result

The real BGE-M3 dense plus BM25S hybrid path followed by the real BGE
reranker completed all 30 Golden queries with status **PASS**:

| H@1 | Recall@5 | MRR | nDCG@5 | P50 | P95 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0.867 | 0.917 | 0.900 | 0.913 | 2007.943 ms | 3027.209 ms |

On this small synthetic set, reranking did not improve Hit@1, MRR, or nDCG
against the corresponding non-reranked path. Hybrid+Rerank did improve
Recall@5 and Precision@5, while adding approximately 7–8x CPU latency. This
supports an evaluation-driven enable/disable decision; it is not evidence that
reranking should always be the default.

## 7. Full 30-query benchmark

The benchmark was regenerated on `2026-09-04T18:00:35.877Z` using config hash
`sha256:5e925553a4dc5eff802f2bfa0e049e00bc9ce16d3f2971b0347121c67508474c`.
It contains 30 queries over 14 eligible Knowledge chunks, including 2 negative
queries, and six configurations. Values below are rounded from
`reports/rag_eval_round1.json`; that JSON retains the full precision metrics.

| Configuration | Status | H@1 | H@3 | H@5 | R@5 | R@10 | P@5 | MRR | nDCG@5 | P50 ms | P95 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| BM25S | PASS | 0.867 | 0.933 | 0.933 | 0.892 | 0.892 | 0.313 | 0.900 | 0.891 | 0.633 | 1.151 |
| Dense (Mock; test-only) | PASS | 0.767 | 0.867 | 0.900 | 0.825 | 0.825 | 0.273 | 0.814 | 0.799 | 10.104 | 12.024 |
| Dense (BGE-M3) | PASS | 0.933 | 0.933 | 0.933 | 0.900 | 0.900 | 0.313 | 0.933 | 0.919 | 262.804 | 392.259 |
| Hybrid (BGE-M3 + BM25S) | PASS | 0.933 | 0.933 | 0.933 | 0.908 | 0.908 | 0.320 | 0.933 | 0.923 | 256.747 | 382.123 |
| Dense+Rerank (BGE) | PASS | 0.900 | 0.933 | 0.933 | 0.900 | 0.900 | 0.313 | 0.917 | 0.910 | 1926.742 | 2635.553 |
| Hybrid+Rerank (BGE + BM25S) | PASS | 0.867 | 0.933 | 0.933 | 0.917 | 0.917 | 0.327 | 0.900 | 0.913 | 2007.943 | 3027.209 |

The Qdrant named dense/sparse and native-RRF implementation remains a
test-only PoC; a real BGE sparse Qdrant benchmark is P1 and is not part of this
six-configuration Full PASS gate.

## 8. Root governance correction

The root gate requires the module `TASK.md` to contain exactly these governance
headings: `职责`, `输入`, `输出`, `禁止事项`, `接口`, `验收标准`, `交付物`.
The minimal correction added those headings to
`05_rag-engine/TASK.md`. No root Frozen Contract, schema, OpenAPI, or root
governance file was modified.

## 9. Root Contract/Governance suite

The official repository-wide check was run with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\00_architecture\tests\run_contract_checks.ps1
```

Result: **13 tests passed, 0 failed**; the OpenAPI validator also reported
`OK`. The module's final isolated test command ran with the reranker integration
flag explicitly enabled:

```powershell
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
$env:SMHAI_RUN_RERANKER_INTEGRATION='1'
.venv\Scripts\python.exe -m pytest -q
```

Result: **22 passed, 3 warnings**. The warnings are upstream/deprecation
notices from jsonschema and Chroma. No test was deleted or skipped; the
reranker tests are opt-in by design and were explicitly enabled for closure.

## 10. Regression evidence

- BM25S baseline: **PASS**; the existing lexical path remains available.
- Real BGE-M3 Dense: **PASS**; 1024-dimensional dense output and non-empty
  lexical weights were observed.
- Real BGE-M3 + BM25S Hybrid: **PASS**; the existing hybrid path remains
  available.
- Citation regression: **PASS**; citation IDs equal `final_context` IDs in
  order, and cited IDs remain `CHUNK_` identifiers.
- RetrievalTrace regression: **PASS**; dense/sparse/fusion/rerank/final stages,
  scores, ranks, model/provider revisions, and latency are serializable.
- Negative behavior: GQ_029 and GQ_030 remain explicit negative evidence;
  reranking changes order but does not abstain.

## 11. Data, safety, and runtime boundary

Only the approved and rights-verified synthetic/authorized Knowledge export was
indexed. No real student data, names, student IDs, raw assessment responses,
consultation records, or clinical records were used. No LLM query rewrite,
answer generation, diagnosis, or clinical interpretation was introduced.

The closure ran on Windows with CPU-only Torch (`2.14.0+cpu`); CUDA was
unavailable, so GPU performance and RTX 3060 behavior remain unvalidated. No
Vale configuration exists in the project, so no Vale pass is claimed.

## 12. Deferred items

1. Run the Qdrant real BGE dense+sparse/native-RRF benchmark as P1.
2. Validate GPU performance later on the target RTX 3060 environment.
3. Keep real-corpus approval, rights decisions, human safety review, clinical
   validation, and production release acceptance outside this Round 1 closure.
