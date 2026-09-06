# Software Integration Round 1 — Interface Inventory

Status: `STAGE 0 COMPLETE`  
Inspection date: `2026-09-05`  
Repository root: `D:\Projects\StudentMentalHealthAI`  
Git: not initialized; inventory relies on actual files, runtime inspection, and SHA-256 hashes.

## A. Backend (`09_backend`)

| Surface | Current evidence |
| --- | --- |
| Entrypoint | `src/smhai_backend/main.py`; module-level `app = create_app()`, `main()` runs Uvicorn. Factory: `src/smhai_backend/app_factory.py`. |
| Route groups | Health (`/health/live`, `/health/ready`, `/health/dependencies`, `/api/v1/health`); Auth (`/api/v1/auth/*`); Assessments (`POST /api/v1/assessments`, response, complete); Support (`/retrievals`, `/safety/checks`, `/support/requests`, `/generations`, reports, reviews). |
| Current operationIds | FastAPI-generated: `live_health_live_get`, `ready_health_ready_get`, `dependencies_health_dependencies_get`, `api_health_api_v1_health_get`, `login_api_v1_auth_login_post`, `logout_api_v1_auth_logout_post`, `me_api_v1_auth_me_get`, `csrf_api_v1_auth_csrf_get`, `create_assessment_api_v1_assessments_post`, `record_response_api_v1_assessments__assessment_id__responses_post`, `complete_assessment_api_v1_assessments__assessment_id__complete_post`, `create_retrieval_api_v1_retrievals_post`, `check_safety_api_v1_safety_checks_post`, `create_support_api_v1_support_requests_post`, `create_generation_api_v1_generations_post`, `get_report_api_v1_reports__report_id__get`, `review_report_api_v1_reports__report_id__reviews_post`, `list_reviews_api_v1_reviews_get`, `get_review_api_v1_reviews__review_id__get`. |
| Provisional OpenAPI | `09_backend/reports/backend_round1_openapi.json`; the frozen root comparison artifact is `00_architecture/openapi.v1.json`. |
| Auth/session/CSRF | Opaque HttpOnly cookie; in-memory `InMemorySessionStore` currently holds raw session/CSRF values. `AuthService` verifies Argon2 hashes. `validate_mutation_origin` and `validate_csrf` protect unsafe browser calls. The Database module has hashed session/CSRF persistence surfaces but Backend does not yet use them. |
| Problem Details | `core/errors.py`: RFC 9457-shaped `application/problem+json`, stable `code`, `retryable`, `request_id`, `trace_id`; no raw stack trace returned. |
| Trace | `RequestContextMiddleware` accepts/creates `REQ_*` and `TRACE_*`, stores context, and emits response headers. Internal HTTP client forwards both headers and optional `traceparent`. |
| Capability clients | CAT/RAG/LLM are `ContractFake` implementations. Safety has both `ContractFakeSafetyClient` and `HttpSafetyClient`; only Safety can currently be selected as real HTTP. |
| CAT client port | `CatClient.start`, `submit_response`, `complete`, `health`; `CatStart` currently stores assessment/subject/instrument identity and start time only. Backend assessment service keeps the CAT session in process memory. |
| RAG client port | `RagClient.retrieve(assessment, target_role, query, top_k, trace_id, retrieval_id_hint)` → `RetrievalResult`; `KnowledgeChunk` validates the `knowledge.v1` projection. |
| LLM client port | `LLMRuntimeClient.generate(prompt, model_id, provider_class, trace_id)` → `CandidateResponse`; current fake emits structured JSON; the port intentionally does not call Ollama. |
| Safety client port | Input, retrieval, and output checks; health; review finalization. `HttpSafetyClient` maps to `/internal/safety/check-input`, `/check-retrieval`, `/check-output`, `/health`, and review transitions. |
| Persistence ports | `UserRepository`, `SessionStore`, `AssessmentRepository`, `ConversationRepository`, `ReportRepository`, `ReviewProjectionRepository`, `AuditRepository`, `IdempotencyStore`, and a placeholder `UnitOfWork` in `domains/ports.py`; all concrete objects wired by `container.py` are in-memory. |
| Idempotency | `core/idempotency.py`: request-body fingerprint plus optional `Idempotency-Key`, process-local replay only. No durable claim/complete path is wired. |
| Workflow | `SupportOrchestrator` orders input Safety → RAG → retrieval Safety → LLM buffered candidate → output Safety → structured parse → result. Non-proceed input stops before RAG/LLM. Current durable state is only a `ReportRecord`/review projection in memory. |
| Composition | `container.py` is the single current wiring point, but it unconditionally builds in-memory persistence and Fake CAT/RAG/LLM. Real integration mode is not implemented. |

## B. Database (`11_database`)

| Surface | Current evidence |
| --- | --- |
| Public factory | `DatabaseSettings`, `create_engine`, `create_session_factory`, `FernetDataProtectionProvider`, and `SqlAlchemyUnitOfWork` exported by `database_layer/__init__.py`. |
| UoW lifecycle | Async `SqlAlchemyUnitOfWork.__aenter__` creates one `AsyncSession`, begins one transaction, attaches repositories, and `__aexit__` commits/rolls back/closes. |
| Repository surfaces | Accounts, subjects, consent, auth sessions, assessments/responses/results, support session/run/messages/evidence/safety decisions, reviews/events, idempotency, and audit. Repositories add/flush/query; UoW owns commit/rollback. |
| Model ownership | `database_layer/models.py` owns 19 domain tables, internal numeric IDs, UUID public IDs, operational statuses, and foreign keys. Backend must not import or reinterpret ORM state in business services. |
| Migrations | Alembic under `11_database/migrations`, current accepted head `20260905_0001`; no schema change is required by the integration decision. |
| Auth/assessment/support/review/audit tables | `accounts`, `roles`, `account_roles`, `subjects`, `subject_access_grants`, `auth_sessions`; `assessment_sessions`, `assessment_responses`, `assessment_results`; `support_sessions`, `support_messages`, `support_runs`, `support_evidence`, `safety_decisions`; `review_cases`, `review_events`; `idempotency_records`, `audit_events`. |
| Adapter readiness | Real MySQL 8.4/SQLAlchemy 2.0/aiomysql and encryption are accepted independently. Backend has no concrete adapter yet; existing `BACKEND_PERSISTENCE_MAPPING.md` records this gap. |
| Encryption boundary | `FernetDataProtectionProvider` encrypts JSON payloads before repository persistence. Keys are supplied by a provider/file outside the repository; ciphertext and key/cipher/schema versions are stored, never raw key material. |

## C. CAT (`01_cat-engine`)

| Surface | Current evidence |
| --- | --- |
| Public API | `CATService.create_session`, `next_item`, `submit_response`, `record_missing`, `complete`, `assessment`; `ItemBank.from_json`, `CATConfig.from_dict`, provider-neutral `Session`/`ItemSelection`/`CATResult`/`CATTraceRecord`. |
| Accepted defaults | Synthetic published bank and config: GRM, EAP, MFI, min 3/max 8, SE threshold 0.55, explicit prior/seed/exposure/content-balancing fields. The adapter must load these unchanged. |
| DTOs | Item has `item_id`, stem, response options/scoring, model parameters, source/status. Result has theta/SE only at the engine boundary and maps through `AssessmentMapper` to `assessment.v1`; the student UI must not expose internal measurement parameters. |
| State | Stateful, in-process `Session` holding provider opaque state; `AdaptiveTestingProvider` wraps `adaptivetesting==1.2.1` and lazily owns third-party types. A one-worker service registry is the minimal transport boundary. |
| Transport needed | Start session, return current item, submit one response, return next item/state, complete, liveness/readiness/capabilities. HTTP must translate to the existing service and never implement CAT math. |

## D. RAG (`05_rag-engine`)

| Surface | Current evidence |
| --- | --- |
| Public API | `RetrievalService.retrieve(RetrievalPlan, raw_query, request_id, trace_id, retrieval_id)` and `retrieve_for_assessment`; `RetrievalResult.to_api_envelope` returns `retrieval_id` and `knowledge.v1` chunks. |
| Bootstrap | Loads `04_knowledge-pipeline/data/published/round1/embedding_ready.jsonl`, eligible corpus/review metadata, RAG config, real BGE-M3 embedding, Chroma dense store, and BM25S for hybrid mode. Existing CLI contains the accepted bootstrap helpers. |
| Output/trace | `RetrievalResult` includes hits, context, citation bundle, and `RetrievalTrace`; the API projection preserves chunk IDs and citations. |
| Reranker | `RetrievalPlan` supports reranking, but the current query builder derives `rerank_enabled` from the configured model. Integration must explicitly replace this with `False`; reranker default enable remains deferred. |
| Transport needed | Assessment/routing context + query → existing plan builder/service → contract chunk projection + trace; no generation. One worker. |

## E. LLM Runtime (`06_llm-runtime`)

| Surface | Current evidence |
| --- | --- |
| Public API | `RuntimeService.health`, `list_models`, `discover`, `load_model`, `unload_model`, buffered `generate`, and separate `stream_generate`. `GenerationRequest` carries frozen IDs, prompt/retrieval references, model policy, structured schema, and trace IDs. |
| Registry/provider | `ModelRegistry` loads `config/models.v1.json`; `RuntimeService` selects provider, retries according to runtime config, records trace, and applies configured local fallback. |
| Accepted runtime | Ollama local provider with `qwen2.5:0.5b` primary and `qwen2.5:1.5b` engineering fallback; `cloud_fallback=false`. Llama.cpp/GPU remains deferred. |
| Integration rule | Add a buffered HTTP adapter around `RuntimeService`; Backend never calls Ollama. Streaming is not exposed to students in Round 1. |

## F. Safety (`08_safety-engine`)

| Surface | Current evidence |
| --- | --- |
| HTTP endpoints | `GET /health/live`, `/health/ready`, `/health`; `POST /internal/safety/check-input`, `/decide`, `/check-output`, `/check-retrieval`; review get/create/transition endpoints under `/internal/safety/reviews`. |
| Readiness | `/health/ready` evaluates actual component health and returns `503` when not ready; `/health` reports `READY`/`DEGRADED`. |
| Models | Pydantic `SafetyContext`, input/output/retrieval request DTOs, `SafetyDecision`, review models; action vocabulary is `PROCEED`, `PROCEED_WITH_BOUNDARY`, `BLOCK`, `REVIEW_REQUIRED`, `CRISIS_ROUTE`. |
| Semantics | Crisis returns a controlled response/template reference and requires human review. Existing policy is fail-closed; no auto-notification is introduced. Retrieval Safety remains an honest partial capability where the current service reports it. |
| Integration | Existing real service is used unchanged through `HttpSafetyClient`; Backend stores the resulting action/reference and does not recalculate policy. |

## G. Frontend (`10_frontend`)

| Surface | Current evidence |
| --- | --- |
| API boundary | `src/api/client.ts` defines `FrontendApi`; `src/services/mock-api.ts` implements `MockApiProvider` and is currently exported as `frontendApi`. |
| Service/state | Views call the provider; Pinia owns session and CAT UI state (`stores/session.ts`, `stores/assessment.ts`). No raw HTTP calls exist in views. |
| Auth/CSRF | Mock only. The real provider must use `credentials: include`, keep CSRF in memory, attach `X-CSRF-Token` to unsafe requests, and never use localStorage for session/auth. |
| Error model | Mock uses `MockApiError`; Backend emits Problem Details. A centralized RealApiProvider mapping is required. |
| API base | No runtime API base/client configuration exists yet; Vite dev server is on `127.0.0.1:4173`. Browser requests must remain relative `/api/*`; Vite proxies those paths to Backend. |
| Tests | Vitest scripts: `npm run test:unit`; quality/build: `npm run typecheck`, `npm run lint`, `npm run build`; Playwright: `npm run test:e2e`, existing `e2e/vertical-slice.spec.ts` and visual artifact spec. |
| Client generation | No generated client currently exists. Node/npm check: `v24.15.0`/`12.0.2`; selected exact generator is `@hey-api/openapi-ts@0.99.0`. |

## H. Frozen root contract

| Evidence | Value |
| --- | --- |
| Official command | `powershell -ExecutionPolicy Bypass -File 00_architecture/tests/run_contract_checks.ps1` |
| Frozen status | `CONTRACTS.md` publishes root `v0.1.0 FROZEN`; root schemas/OpenAPI are read-only for this mission. |
| Root OpenAPI | `00_architecture/openapi.v1.json`, paths under `/api/v1`, stable operation IDs such as `createAssessment`, `recordAssessmentResponse`, `completeAssessment`, `createRetrieval`, `checkSafety`, `createGeneration`, `getReport`, `reviewReport`. |
| Baseline SHA-256 | `openapi.v1.json` `235C8FDB0B35F2DE870127A18D4CD8C72A1C7795AF02656B2A6C7274AB071897`; `assessment.v1.schema.json` `56B9FC990261D0B826EEEA0E84417754798EF3A980F50A414CCB565168375A52`; `knowledge.v1.schema.json` `5334533DB35B30840F57E8012208037A6809BFED7CE08094BDA1517C801D8BCF`; `generation.v1.schema.json` `8365D7EA825A30D9429361107750E87E8C6446D0A6576C47F3A8ECE564DCA62C`. |
| Current official count | The exact count is produced by the official script; it is not inferred from module reports. Integration must rerun and record its exit code/count. |

## Stage 0 conclusion

The primary gaps are concrete and bounded: transport adapters for CAT/RAG/LLM, a real-mode Backend composition root, async-compatible Backend persistence adapters over the existing Database UoW, candidate OpenAPI export, generated frontend client/provider, and a Windows-first harness. No frozen schema, CAT algorithm, RAG strategy, LLM strategy, Safety policy, or Database schema change is required by the current reconciliation.

