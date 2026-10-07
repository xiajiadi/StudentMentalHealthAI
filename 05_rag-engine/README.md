# 05 · RAG Engine

This module provides a provider-neutral retrieval and context engine for the
StudentMentalHealthAI project. It consumes the Knowledge pipeline's reviewed
`embedding_ready.jsonl`; it does not ingest documents, generate answers, or
interpret psychological scores.

## Scope

- deterministic Assessment/role query planning;
- policy/theory/intervention layer routing and metadata eligibility filters;
- BGE-M3 dense adapter, Chroma dense baseline, BM25S lexical baseline;
- Qdrant local dense/sparse/hybrid PoC;
- RRF fusion and candidate-only BGE reranking;
- stable index manifests, context bundles, citations, and retrieval traces;
- deterministic golden-query metrics and benchmark artifacts.

## Local setup

The runtime is isolated in this module. From `05_rag-engine`:

```powershell
uv sync --extra runtime --extra test
```

Model weights are not part of the module. The provider uses `HF_HOME` when it
is set; on this machine it is configured under `D:\Dev\caches\huggingface`.
If BGE-M3 or the reranker cannot load, the module reports that integration as
pending/blocked and keeps deterministic mocks only for unit tests.

For an explicit local sparse-only demo, set `SMHAI_RAG_CONFIG` to
`config/rag.m0-demo-bm25.v1.json` and set `SMHAI_RAG_CORPUS`,
`SMHAI_RAG_DOCUMENTS`, and `SMHAI_RAG_REVIEW_QUEUE` to the matching export from
the M0 demo fixture. This profile builds and serves BM25S directly; it does not
load embeddings or fall back to a mock provider. Keep its corpus isolated to
the synthetic M0 demo export.

## Run tests and benchmark

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q src tests
.venv\Scripts\python.exe -m rag_engine.cli --help
```

The exact Round 1 commands and results are recorded in
`reports/RAG_ROUND1_ACCEPTANCE.md` after execution.

## Contract boundary

The root `knowledge.v1`, `assessment.v1`, `config.v1`, `logging.v1`, and API
contracts remain unchanged. Retrieval-only fields live in internal domain
models and are not written back into the frozen schemas.

See:

- [RAG_TECHNICAL_DECISION_V1.md](RAG_TECHNICAL_DECISION_V1.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TASK.md](TASK.md)
