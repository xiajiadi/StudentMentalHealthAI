# Synthetic RAG Boundary Reconciliation

Status: **accepted boundary restored; product closure remains PARTIAL_PASS**

## Boundary used by the final run

The final RAG service loaded the accepted Round 1 publication, not the D2 Runtime Reconstruction corpus:

- Publication: `D:\Projects\StudentMentalHealthAI\04_knowledge-pipeline\data\published\round1\embedding_ready.jsonl`
- Target ignored runtime copy: `04_knowledge-pipeline\data\published\round1\embedding_ready.jsonl`
- Publication SHA-256: `2d5736ae741d675ca5856b8004665ea3043aeccea34e2b007498ff04c2b501a2`
- RAG corpus version: `sha256:4553317e36b1064880df01643a3171f7937e0ec420ead380c5d6702f2396aad2`
- Documents: `7`
- Chunks: `15`
- Embedding-ready rows: `14`
- D2 candidate used: `false`
- D2 worktree used: `false`

The target fixture hashes and the exact accepted publication hash are recorded in [synthetic_rag_boundary.json](../../12_evaluation/gpu-product-integration-closure-r1/synthetic_rag_boundary.json). The exact publication was available read-only in the preserved main workspace, so the compiler was not rerun to create a second publication identity. The recorded reconstruction command is retained for provenance only.

## Why the exact artifact matters

The RAG regression expects the accepted intervention chunk `CHUNK_67b56abe21fe9860a26d`. The exact publication returned that identity and passed the RAG suite:

```text
18 passed, 4 skipped, 3 warnings in 2.28s
```

The earlier target-local deterministic reconstruction produced a different output hash (`63c013d4432c8408a6983f0b867631d3c891bcd534c6f94eb7d96fb66cf31b20`) because fixture byte identity differed. It was not used for the final product closure evidence. This avoids silently substituting a different corpus while preserving the accepted RAG regression boundary.

## Final service identity

The final RAG service reported:

- dense provider: BGE-M3 (`BAAI/bge-m3`), CPU/fp32, dimension 1024;
- sparse provider: BM25S;
- retrieval mode: hybrid with RRF;
- reranker: OFF;
- no ContractFake RAG path.

## Reconciliation result

The boundary itself is accepted and regression-green. However, the exact chunk identities are part of the Backend prompt. With those identities, the formal Qwen2.5 7B generation produced invalid JSON at the RuntimeService structured-output boundary. That is recorded separately as [PRODUCT_INTEGRATION_BLOCKER.md](PRODUCT_INTEGRATION_BLOCKER.md); this document does not replace the exact artifact with the earlier reconstruction merely to make the normal flow pass.
