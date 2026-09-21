# D3 Slice 4 Trusted Backend Integration Evidence

**Disposition:** READY_FOR_CONTROLLER_REVIEW
**Fresh validation date:** 2026-09-21
**Baseline:** `d3-slice3-r1-accepted` / `cb28fe38b2e1df1b06c96610419691dd2d7924db`
**Branch:** `exp/d3-backend-integration-v1`
**Worktree:** `D:\Projects\StudentMentalHealthAI-d3-backend-integration`
**Seam Commit 1:** `0dc5c7762baf3ba1292de6e6e9d540e4aeafc58d`
**Integration Commit 2:** authorized local publication boundary after read-only review
**Controller acceptance:** not granted

This is engineering-only, synthetic/demo-bounded evidence. It does not grant
psychology approval, legal/consent or rights approval, real-student disclosure
authorization, real-pilot authorization, or production enablement. D4 was not
started. The fresh machine evidence is
`12_evaluation/d3-slice4-backend-integration-r1/d3_slice4_backend_integration_evaluation.json`;
the raw real HTTP record is
`12_evaluation/d3-slice4-backend-integration-r1/D3VAL_REAL_HTTP_EVIDENCE.json`.

## Frozen decision fidelity

- D3SEAM-01..20: **20/20 PASS**.
- D3INT-01..60: **60/60 PASS**.
- D3VAL-01..16: **16/16 PASS** in
  `D3_SLICE4_CONTROLLED_VALIDATION_DECISION_V1.md`, status **FROZEN FOR FINAL VALIDATION**.
- Semantic deviations: **0**.
- Mission deviations: **0**.
- The typed `PromptFacingProjection` is consumed through `render_projected` in
the formal Backend route. Template bytes, template hashes, D3-2/D3-3/D3-1
policy identities, and the accepted D3 Slice 3 baseline remain unchanged.
- The product-tree fingerprint covered 79 files before and after GPU validation;
  both SHA-256 values are
  `079e78633997f3b3bad06578296170f7b93a8dd4387e6aa74455879e6a9024a4`.

## Scope and population boundary

The only D3-4 product source changes remain the reviewed uncommitted changes
under `09_backend`; the separately Controller-authorized 07 projection seam is
Commit 1 above. That seam is the explicit D3SEAM exception for the typed
projection-consumption API; it changed no prompt template or policy bytes. No forbidden product module,
root contract, OpenAPI contract, database schema, accepted D2 publication, or
06 Runtime source/config was edited. No K12-to-University mapping was added.
The accepted D2 publication was copied read-only from:

`D:\Projects\StudentMentalHealthAI\04_knowledge-pipeline\data\published\round1\embedding_ready.jsonl`

Its SHA-256 is
`2d5736ae741d675ca5856b8004665ea3043aeccea34e2b007498ff04c2b501a2`, with
14 published chunks carrying `K12学生`. The copy was byte-identical. Generated
indexes, model files, caches, logs, virtual environments, and temporary runtime
state are outside the worktree and are not committed.

The compatible evaluation fixture is:

`12_evaluation/d3-slice4-backend-integration-r1/fixtures/university_freshmen_synthetic_validation_corpus.jsonl`

It is `SYNTHETIC_VALIDATION_ONLY`, contains two neutral engineering records,
uses exactly `UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO`, and contains no real people,
health claims, diagnosis, severity, crisis claim, clinical recommendation, or
psychology-validity claim. Fixture SHA-256:
`519efd711d49240f4515713d47a58a250cc84a70457f4997646d98d7ace1ade5`.
The separate role-negative fixture is
`12_evaluation/d3-slice4-backend-integration-r1/fixtures/rag_ineligible_validation_corpus.jsonl`,
SHA-256 `0998157f36c38a635fc146695f2fd8293f95cdd8c6a8143e07de16b2367452a2`.

## Fresh real HTTP validation

The topology used Backend, CAT, real RAG, real Safety, and the sealed accepted
C Runtime. The Normal runtime identity was verified before the request:

- RuntimeService `0.1.0-gpi-r1`, loopback endpoint `http://127.0.0.1:8160`.
- Ollama `0.33.3`, provider model `qwen2.5:7b-instruct-q4_K_M`.
- The accepted Runtime registry uses the historical logical alias
  `qwen2.5-0.5b-engineering`; that alias resolves to the verified 7B provider
  above and does not select a lightweight 0.5B provider.
- Accepted digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`.
- Contract model `MODEL_local_gpu_acceptance`, cloud fallback `false`.
- The Backend request builder supplied `MODEL_local_primary`; the Runtime
  registry selected logical alias `qwen2.5-0.5b-engineering`, whose contract
  response identity is `MODEL_local_gpu_acceptance` and whose provider is the
  accepted 7B model above.
- GPU preflight recorded NVIDIA GeForce RTX 3060, driver `596.36`,
  `/api/ps size_vram=5133943438`, and post-request `nvidia-smi` memory use
  `5029 MiB`.

| Case | Fresh result | Evidence |
| --- | --- | --- |
| Normal compatible University fixture | **PASS**, HTTP 202 | `data.status=generated`, `normal_generation=true`; Input Safety PROCEED; all eleven ledger stages reached in order; real RAG returned 2 eligible chunks; accepted GPU Runtime returned a candidate in 4.208 seconds; Output Safety PROCEED; report persisted after Output Safety. |
| Accepted K12 population negative | **PASS_FAIL_CLOSED**, HTTP 502 | Real RAG returned 5 accepted K12 chunks; trusted University eligibility produced 0 bundle items; D3-3=0, D3-1=0, Runtime=0, citations=0, fallback=none. No mapping was added. |
| Output-unsafe candidate | **PASS_OUTPUT_SAFETY_REVIEW_REQUIRED**, HTTP 202 | Safe input reached Input Safety PROCEED; evaluation-only HTTP Runtime returned the exact accepted in-process clinical-overreach candidate; candidate was buffered; real Output Safety returned `REVIEW_REQUIRED`; content was null and no normal content was persisted. |
| RAG no eligible evidence | **PASS_FAIL_CLOSED**, HTTP 502 | Real RAG returned 1 teacher-scoped synthetic chunk; student trusted filtering produced 0 eligible bundle items; D3-1=0, Runtime=0, citations=0, fallback=none. |
| Crisis | **PASS**, HTTP 202 | `CRISIS_ROUTE`; normal RAG/prompt/Runtime were bypassed; generation `NOT_RUN`; citations empty. |
| Safety-down | **PASS_FAIL_CLOSED**, HTTP 503 | Safety listener was stopped after the preceding cases; safe support request failed before normal generation and returned no content. |

The raw case record preserves call order, D3 stage order, ledger stages,
retrieval traces, corpus versions, report counts, and response bodies. The
Normal transaction is bound by request ID
`REQ_ef2712c0255d7f6c0889c832c5c3a095`, trace ID
`TRACE_ca48a4646305e90081af196ce46c39c8`, transaction ID
`TX_ca48a4646305e90081af196ce46c39c8`, context ID
`CTX_ca48a4646305e90081af196ce46c39c8`, and bundle hash
`a1f7ca1223666731bb94d8cdfd0a65b3620cbfaf3d45ea55409eeeff6307914b`.
Prompt assembly occurred before the Runtime call; the candidate was buffered,
Output Safety returned PROCEED, and persistence followed. Crisis and Safety-down
zero-call claims use their trace-correlated ledgers; the service-level
cumulative call-order snapshot is not used as per-case proof.

The GPU Normal request used the existing product 60-second timeout without
change. Runtime latency from `PROMPT_ASSEMBLED` to `GENERATION_BUFFERED` was
`4208 ms`; the end-to-end HTTP transaction took `11.623 s`.

The output-unsafe HTTP harness is evaluation-only:

`12_evaluation/d3-slice4-backend-integration-r1/fixtures/output_unsafe_runtime_harness.py`

It does not change `06_llm-runtime`, product configuration, or the Normal case.
The candidate is the exact structured candidate used by the accepted in-process
Backend/Safety test (`theta indicates a diagnosis`, a cited synthetic guidance
suggestion, and `synthetic fixture` disclaimer). The real HTTP result is
`REVIEW_REQUIRED`, with `candidate_buffered=true`, `output_safety_reached=true`,
`normal_persistence=false`, and `normal_response_content=0`.

## Fresh static and regression gates

| Scope | Result |
| --- | ---: |
| Prompt Engine full | 154 passed |
| D3-2 Assessment Adapter | 41 passed |
| CAT | 24 passed |
| RAG | 18 passed, 4 skipped, 2 warnings |
| Safety | 20 passed, 1 skipped, 3 warnings |
| Backend D3 focused | 47 passed |
| Backend contracts | 16 passed |
| Backend full | 65 passed |
| Ruff touched scope | 0 errors |
| Ruff format touched scope | clean; 18 files already formatted |
| Pyright touched D3-4/seam scope | 0 errors |
| Full Pyright | baseline 2 / candidate 2 / new D3-4 0; both baseline errors are in `09_backend/src/smhai_backend/adapters/database.py` lines 103-104 |
| Compile/import | pass |
| Root contract | 13/13 |
| OpenAPI | PASS |
| Frozen Root | 8/8 unchanged |
| `git diff --check` | exit 0 |

## Commit and release boundary

The product tree remained unchanged during GPU validation. The authorized local
Integration Commit 2 may now be created from this reviewed worktree; merge,
push, and tag remain forbidden. Real student data was not used. D4 was not
started.

Remaining P1 items are the documented two baseline Pyright errors, the historical
GPU resource snapshot / fixed-output-budget robustness follow-up, and the D5
cleanup PID follow-up. There is no remaining P0 for this validation scope.

**Controller recommendation:** `READY_FOR_CONTROLLER_REVIEW`.
