# Software Integration Round 1 — Technical Decision V1

Status: `v1.0 PROVISIONALLY FROZEN`  
Decision date: `2026-09-06`  
Scope: V0.9 local synthetic vertical slice.

## 1. Decision summary

Keep the existing modular architecture and add only the missing integration edges:

- one explicit Backend composition root selects memory/fake or real implementations;
- CAT, RAG, and LLM Runtime receive thin loopback HTTP adapters around their accepted Python APIs;
- Backend real persistence uses the existing MySQL/SQLAlchemy repositories and async Unit of Work;
- Safety remains the existing real Safety HTTP service and policy authority;
- the browser calls only the Backend same-origin `/api/*` surface;
- TypeScript transport is generated from the actual candidate Backend OpenAPI with an exact-pinned Hey API generator, while product mapping remains in a hand-written `RealApiProvider`;
- each database operation is short and local; no transaction spans an upstream HTTP/model call;
- root `v0.1.0` contracts remain unchanged.

This decision is intentionally composition-first. It does not introduce a service mesh, event bus, heavyweight DI framework, new database tables, or a second authentication system.

## 2. Current-state diagram

```text
Vue 3 + Pinia
  └─ MockApiProvider
       └─ in-process fixture state

FastAPI Backend
  ├─ in-memory users/sessions/assessment/reports/reviews/audit/idempotency
  ├─ ContractFakeCatClient
  ├─ ContractFakeRagClient
  ├─ ContractFakeLLMRuntimeClient
  └─ optional HttpSafetyClient ──> Safety service

Capability modules
  ├─ CAT: Python service API only
  ├─ RAG: Python service API/CLI only
  ├─ LLM Runtime: Python service API/CLI only ──> Ollama
  └─ Safety: real FastAPI service ──> local safety components

Database
  └─ accepted MySQL repositories/UoW, not wired to Backend
```

## 3. Target runtime diagram

```text
Browser
  │ same-origin relative /api/*; HttpOnly session cookie; in-memory CSRF token
  ▼
Vue Frontend :4173
  └─ Vite proxy /api/*
       ▼
FastAPI Backend/BFF :8080
  ├─ Application services + native authorization + Problem Details
  ├─ RealDatabaseAdapter
  │    └─ database_layer.SqlAlchemyUnitOfWork
  │         └─ MySQL 8.4 (synthetic integration database)
  ├─ LongLivedCatClient ───────HTTP loopback──────> CAT :8180
  ├─ LongLivedRagClient ───────HTTP loopback──────> RAG :8170 ──> BGE-M3/Chroma/BM25S
  ├─ LongLivedLLMClient ───────HTTP loopback──────> LLM Runtime :8160 ──> Ollama :11434
  └─ HttpSafetyClient ──────────HTTP loopback──────> Safety :8190

All capability processes bind loopback and run with one worker in the local baseline.
Backend owns application trace correlation; capability responses echo request/trace IDs where supported.
```

## 4. Module ownership

| Area | Owner | Round 1 change |
| --- | --- | --- |
| Frozen schemas and root OpenAPI | `00_architecture` | Read-only; compare only. |
| CAT selection, scoring, stopping, mapping | `01_cat-engine` | Thin FastAPI transport/bootstrap only. |
| Source parsing/publishing | `04_knowledge-pipeline` | Read-only input boundary. |
| Retrieval/index/reranking/citation | `05_rag-engine` | Thin FastAPI transport/bootstrap only; reranker off by integration default. |
| Model registry/provider/retry/trace | `06_llm-runtime` | Thin buffered FastAPI transport only; no cloud fallback. |
| Safety policy and review semantics | `08_safety-engine` | Reuse existing service unchanged. |
| Application orchestration/BFF | `09_backend` | Composition root, clients, persistence adapter, route/state corrections, candidate OpenAPI, integration tests. |
| Browser UI/transport | `10_frontend` | Generated SDK, RealApiProvider, proxy, error/CSRF/idempotency wiring; retain MockApiProvider. |
| Relational schema/encryption/UoW | `11_database` | Prefer read-only use of existing public API; only stable read/write repository additions if required by the adapter. |
| Harness/fixtures/evidence | `15_demo/integration` | Windows-first lifecycle, synthetic fixtures, reports. |

## 5. Application plane vs capability service plane

The application plane is Backend: authentication/session, authorization, workflow ordering, publication gates, user-facing error semantics, idempotency scope, and durable projections. Capability services own only their accepted technical domain:

- CAT owns adaptive item selection and assessment result calculation.
- RAG owns query construction, retrieval, context, citation, and retrieval trace.
- LLM Runtime owns model resolution, local provider calls, retry/fallback semantics, buffered candidate generation, and runtime trace.
- Safety owns policy decisions, fail-closed behavior, crisis route, and Safety review references.
- Database owns persistence integrity and encryption mechanics, not authorization or Safety interpretation.

## 6. Composition strategy

`09_backend/src/smhai_backend/container.py` remains the only selection point.

| Mode | Persistence | CAT | RAG | LLM Runtime | Safety | Use |
| --- | --- | --- | --- | --- | --- | --- |
| `test`/unit | in-memory | contract fake | contract fake | contract fake | contract fake | Fast existing unit and route tests. |
| `real`/integration | real MySQL | real HTTP | real HTTP | real HTTP | real HTTP | Primary synthetic acceptance path. |

The application services depend on protocols, not concrete module classes. To preserve the existing unit tests while supporting async Database repositories, port calls accept either an immediate value or an awaitable and the application service resolves it at its boundary. This is an adapter compatibility measure, not a second abstraction chain.

Long-lived HTTP clients are created once per capability and closed by Backend lifespan. Local calls use explicit timeouts and `trust_env=False`; non-idempotent workflow calls are not automatically retried by Backend.

## 7. Backend ↔ Database mapping

```text
AuthService / AssessmentService / SupportOrchestrator
  → Backend persistence protocols
  → RealDatabaseAdapter (one short UoW per method)
  → existing database_layer repositories
  → SQLAlchemy AsyncSession
  → MySQL
```

The adapter maps Backend public references (`USER_*`, `SUBJ_*`, `ASSESS_*`, `GEN_*`, `RETR_*`, `REPORT_*`, `REVIEW_*`) to the Database internal numeric foreign keys and stores the public reference/projection in the existing fields or encrypted JSON payloads. No ORM query is placed in a Backend domain service.

The current Database tables support the projection without a new `reports` or `generations` table:

- `assessment_sessions`, `assessment_responses`, `assessment_results` persist the CAT lifecycle;
- `support_sessions` and `support_runs` persist the workflow/resource references and status;
- `support_messages` stores only `USER_INPUT` or Safety-approved output, encrypted;
- `support_evidence` stores citation references, not raw corpus text;
- `safety_decisions` stores the authoritative Safety action/reference, encrypted detail;
- `review_cases` and `review_events` store human-review projection and transitions;
- `idempotency_records` provides durable claim/replay identity;
- `audit_events` stores allowlisted metadata only.

The real adapter never reports a successful save before the UoW commits. If persistence fails, the application returns an explicit unavailable/error state and does not claim the result was saved.

## 8. Backend ↔ CAT transport mapping

The CAT adapter exposes a private service surface:

```text
GET  /health/live
GET  /health/ready
GET  /capabilities
POST /internal/cat/sessions
POST /internal/cat/sessions/{assessment_id}/responses
POST /internal/cat/sessions/{assessment_id}/complete
GET  /internal/cat/sessions/{assessment_id}
```

The service loads the accepted synthetic bank/config once at startup, creates a `CATService` with `AdaptiveTestingProvider`, stores the provider-neutral `Session` in a one-worker registry, and returns a transport projection of the current item. The router performs validation and error translation only; it does not score responses or choose stopping rules.

Backend `CatClient` translates these DTOs to `CatStart`, current-item state, response state, and the frozen assessment result. Backend remains responsible for durable assessment metadata and access control.

## 9. Backend ↔ RAG transport mapping

The RAG adapter exposes:

```text
GET  /health/live
GET  /health/ready
GET  /capabilities
POST /internal/rag/retrievals
```

The request contains the frozen assessment projection, target role, user query, top-k, request ID, trace ID, and retrieval ID hint. The service uses the accepted published `embedding_ready.jsonl` corpus, real BGE-M3 embedding, current Chroma index, and BM25S hybrid path. It explicitly constructs the plan with `rerank_enabled=False` for this integration profile. The response uses `RetrievalResult.to_api_envelope`, preserving `knowledge.v1` chunks, citation IDs, and retrieval trace metadata.

## 10. Backend ↔ LLM Runtime mapping

The LLM adapter exposes:

```text
GET  /health/live
GET  /health/ready
GET  /capabilities
GET  /internal/llm/models
POST /internal/llm/generate
```

`POST /internal/llm/generate` maps the transport request to the existing `GenerationRequest` and calls buffered `RuntimeService.generate`. It returns the candidate text and serialized `RuntimeTrace`. Backend does not call Ollama or consume a stream. The service uses the existing `ModelRegistry`, local Ollama provider, accepted primary/fallback model configuration, and `cloud_fallback=false`.

## 11. Backend ↔ Safety mapping

Backend uses the existing `HttpSafetyClient` against `/internal/safety/check-input`, `/check-retrieval`, `/check-output`, `/health`, and review transitions. Input Safety is mandatory before RAG; Output Safety is mandatory before parsing/persisting/exposing candidate content. Retrieval Safety is called where the existing service supports it and remains reported as partial capability if the service says so.

`CRISIS_ROUTE`, `BLOCK`, and `REVIEW_REQUIRED` stop normal generation. The crisis response is a controlled Safety-provided response/template projection; it is not generated by LLM Runtime. Backend persists the action/reference and creates the Database review projection when required. It never recalculates Safety action or sends notifications.

## 12. Frontend generated-client design

```text
candidate Backend OpenAPI
  → @hey-api/openapi-ts@0.99.0
  → 10_frontend/src/api/generated/  (generated-only, no hand edits)
  → RealApiProvider
       ├─ credentials: include
       ├─ in-memory CSRF token
       ├─ stable Idempotency-Key per logical write
       ├─ Problem Details → FrontendApiError
       └─ API DTOs → existing view models/Pinia state
```

The current Node `24.15.0` satisfies the exact generator's declared engine. The generator is invoked by deterministic npm scripts against `15_demo/integration/contracts/openapi.integration.candidate.json`; a drift script generates to a temporary directory, compares the canonical manifest, and reports whether the checked output changed. The SDK is transport infrastructure, not a replacement for the existing `FrontendApi` boundary.

`MockApiProvider` remains the default for existing UI/unit tests. Real integration mode is selected by `VITE_API_MODE=real`; browser calls remain relative so the Vite proxy preserves same-origin behavior.

## 13. Same-origin browser topology

Development:

```text
Browser http://127.0.0.1:4173
  ├─ /, /student/*, /reviewer/*
  └─ /api/* ── Vite proxy ──> http://127.0.0.1:8080/api/*
```

The Backend retains explicit development CORS for diagnostics, but the primary browser path does not depend on credentialed cross-origin CORS or wildcard origins.

## 14. Contract lifecycle and operation IDs

`00_architecture/openapi.v1.json` and frozen schemas are never overwritten. The candidate is exported from the actual Backend app. Existing frozen operation IDs are retained explicitly (`createAssessment`, `recordAssessmentResponse`, `completeAssessment`, `createRetrieval`, `checkSafety`, `createGeneration`, `getReport`, `reviewReport`). New auth/health/state/review operations receive stable explicit IDs in Backend route declarations. The candidate is validated, compared with the previous provisional Backend OpenAPI and root OpenAPI, and then fed to Hey API generation.

An additive candidate path is not silently promoted to the frozen root contract. If a true incompatible change is discovered, the integration report remains `PARTIAL PASS` and records a promotion proposal instead of editing root artifacts.

## 15. Short-transaction workflow model

```text
TX-A: claim durable idempotency + create REQUESTED support run + minimal metadata
  COMMIT

NO DATABASE TRANSACTION while waiting on Safety/RAG/LLM/model processes

Input Safety
  ├─ non-proceed → TX-B persist BLOCKED/review action + audit → COMMIT
  └─ proceed → RAG → retrieval Safety → buffered LLM → output Safety

TX-B: persist authoritative Safety decision, approved output only, evidence refs,
      result projection, audit, and idempotency completion
  COMMIT

Failure: short transaction persists FAILED/unavailable safe metadata → COMMIT
```

The current schema's `REQUESTED`, `COMPLETED`, `BLOCKED`, and `FAILED` vocabulary is used. Raw candidate text is not persisted when Output Safety does not permit it.

## 16. Normal flow sequence

```text
Browser → RealApiProvider: login
RealApiProvider → Backend: POST /auth/login
Backend → MySQL: account/session short transaction
Backend → Browser: HttpOnly cookie + in-memory CSRF token

Browser → Backend: create assessment / response / complete
Backend → CAT: start, select, submit, complete
Backend → MySQL: assessment/session/response/result short transactions

Browser/RealApiProvider → Backend: support request
Backend → MySQL: claim idempotency + REQUESTED run, commit
Backend → Safety: input check
Backend → RAG: real retrieval
Backend → Safety: retrieval check
Backend → LLM Runtime: buffered generate
Backend → Safety: output check
Backend → MySQL: approved result/evidence/audit/idempotency, commit
Backend → Browser: citations + controlled generation projection + trace reference
```

## 17. Crisis flow sequence

```text
Browser → Backend: synthetic message containing SYNTHETIC_CRISIS_SIGNAL
Backend → Safety: input check
Safety → Backend: CRISIS_ROUTE + review/template reference
Backend: stops workflow
Backend: does not call RAG or LLM Runtime
Backend → MySQL: BLOCKED/review projection + authoritative Safety action, commit
Backend → Browser: safe crisis/review state; no free-form generation
```

This proves deterministic synthetic engineering routing only. It is not clinical detection or sensitivity evidence.

## 18. Failure semantics

| Failure | Required behavior |
| --- | --- |
| Safety unavailable | Fail closed with structured `dependency_unavailable`/safe application state; no RAG or LLM call. |
| CAT unavailable | No invented item/result; explicit assessment unavailable/error. |
| RAG unavailable | No generation; report dependency unavailable and do not claim citations. |
| LLM Runtime unavailable | No student output; persist failed/unavailable state only if persistence succeeds. |
| Output Safety rejects candidate | Return review/blocked state without candidate content and never persist it as `APPROVED_OUTPUT`. |
| Database unavailable | Do not claim saved; return structured persistence/dependency error. |
| Backend restart | New process reconstructs durable assessment/report/review projections from MySQL; capability session continuation is only required while the CAT process session exists. |
| Duplicate write | Durable idempotency scope/key either replays the original result or rejects a different fingerprint. |

## 19. Synthetic fixture strategy

One deterministic pack under `15_demo/integration/fixtures/` names `INT-NORMAL-001`, `INT-ATTENTION-001`, `INT-CRISIS-001`, `INT-OUTPUT-UNSAFE-001`, `INT-SAFETY-DOWN-001`, `INT-RAG-DOWN-001`, `INT-LLM-DOWN-001`, and optional `INT-NO-EVIDENCE-001`. Every fixture declares `SYNTHETIC / ENGINEERING ONLY`; IDs are stable and contain no real student identity.

The unsafe-output fixture is a dedicated safety-gate test input. It is not used to claim that the real local model naturally emits unsafe content; the normal path still requires real LLM Runtime and real Output Safety.

## 20. Test strategy

1. Existing module unit tests remain the first regression layer.
2. CAT/RAG/LLM transport adapters get isolated ASGI/client tests.
3. Backend composition tests prove real labels and no Fake in real mode.
4. Database tests use a named synthetic MySQL database and the existing migration head.
5. Candidate OpenAPI is validated; oasdiff compares provisional-to-candidate and root-to-candidate with surface differences explained.
6. Schemathesis runs against a live disposable Backend with synthetic auth/CSRF setup and explicit exclusions only where destructive.
7. Frontend typecheck/lint/build and existing unit tests run unchanged in Mock mode; real provider tests use a local HTTP fixture.
8. Playwright drives login, normal, crisis, Safety-down, and persistence-visible states through the browser.
9. The official root contract suite and all current module commands run after integration.
10. Evidence is generated from command results and harness observations; no PASS value is hand-authored.

## 21. Deferred scope

RAG abstention/no-evidence semantics, Qdrant production benchmark, reranker default enable, Qwen3Guard Stream, GPU/RTX3060 tuning, llama.cpp execution, full Docker/Kubernetes/service mesh, production service authentication, OpenTelemetry collector, Argilla, expert-approved crisis wording, notifications, clinical validation, real-school escalation, real student pilot, multilingual validation, production review reconciliation daemon, broad load benchmarking, and final visual polish remain deferred.

## 22. Explicitly rejected technologies for Round 1

- microservice platform, Kubernetes, service mesh, and an event bus;
- direct Browser-to-capability calls or Backend-to-Ollama calls;
- a second ORM/Database port chain;
- JWT/localStorage authentication;
- wildcard credentialed CORS;
- multiple workers for model/index-heavy services;
- automatic cloud LLM or cloud Safety fallback;
- destructive reset/kill operations in the Windows harness.

