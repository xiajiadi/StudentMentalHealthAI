# Software Integration Round 1 — Contract Reconciliation

Status: `STAGE 1 COMPLETE`  
Decision baseline: `SOFTWARE_INTEGRATION_TECHNICAL_DECISION_V1.md`  
All values below are synthetic engineering projections unless the row explicitly names a frozen contract.

## Reconciliation rules

1. The frozen root schemas and `api.v1` envelope remain authoritative for their existing paths.
2. Accepted module APIs are authoritative inside their module; transport adapters translate rather than redesign them.
3. Backend owns application sequencing, auth, authorization, error mapping, and publication gates.
4. Database stores the Safety action/reference it receives; it does not recalculate action.
5. Where the existing Vue view model is richer than the frozen API response, a candidate additive state/read projection is used. The root assessment object itself is not extended.

## Frontend operation → implementation chain

| Frontend operation | Backend route | Backend application port | Internal client/adapter | Actual module implementation | Persistent artifact / response | Authoritative contract |
| --- | --- | --- | --- | --- | --- | --- |
| `login` | `POST /api/v1/auth/login` | `AuthService.login` | `RealDatabaseAdapter.users` + `sessions` | `11_database.AccountRepository` + `AuthSessionStore` | `accounts`, `auth_sessions`; envelope with actor/CSRF, HttpOnly cookie | Backend candidate auth DTO; root envelope/error conventions |
| `getStudentHome` | `GET /api/v1/auth/me` plus local view projection | `AuthService.actor_for_session` | RealApiProvider mapping | Existing Backend actor/session state | No new content persistence; returns empty/known synthetic view state | Frontend `FrontendApi` view model; Backend auth candidate |
| `startAssessment` | `POST /api/v1/assessments` then `GET /api/v1/assessments/{id}/state` | `AssessmentService.create` + state query | `HttpCatClient.start` | `CATService.create_session` + `next_item` | `assessment_sessions`; assessment envelope plus additive state projection | Frozen `assessment.v1` for assessment object; candidate state DTO |
| `submitAssessmentResponse` | `POST /api/v1/assessments/{id}/responses` | `AssessmentService.submit` | `HttpCatClient.submit_response` | `Session.submit_response` and provider adapter | encrypted `assessment_responses`; state envelope/current item | Frozen `ResponseEvent`; frozen state envelope shape plus additive properties |
| `completeAssessment` | `POST /api/v1/assessments/{id}/complete` | `AssessmentService.complete` | `HttpCatClient.complete` | `CATService.complete` + `AssessmentMapper.assessment` | encrypted `assessment_results`; `assessment.v1` response | Frozen `assessment.v1` and `AssessmentSuccess` |
| normal support request | `POST /api/v1/support/requests` | `SupportOrchestrator.create` | `HttpSafetyClient`, `HttpRagClient`, `HttpLLMRuntimeClient` | real Safety, `RetrievalService`, `RuntimeService` | `support_runs`, authoritative `safety_decisions`, encrypted approved output, `support_evidence`, audit | frozen generation/knowledge contracts and candidate support DTO |
| crisis support request | same support route | same port, pre-generation branch | real `HttpSafetyClient`; no RAG/LLM call | existing Safety service `CRISIS_ROUTE` | `BLOCKED` support run, safety decision, review case/event, no approved output | Safety action vocabulary; Backend candidate support result |
| `getStudentReport` | `GET /api/v1/reports/{report_id}` plus `GET /api/v1/assessments/{id}` | `SupportOrchestrator.report_for_actor` + `AssessmentService.get_for_actor` | RealDatabaseAdapter report/assessment reads | Database projection over support/assessment tables | report projection, encrypted output only when Safety-approved | Frozen report/generation envelope; candidate assessment read route |
| `getTeacherOverview` | authorized candidate overview/read projection or empty synthetic projection | `AuthorizationProvider` + report/review query | RealApiProvider mapper | existing Backend authorization; Database read adapter | safe counts/references only | Frontend view model + candidate read DTO; no raw responses |
| `getReviewQueue` | `GET /api/v1/reviews` | `SupportOrchestrator.pending_reviews` | RealDatabaseAdapter.review projections | `ReviewRepository` + `review_cases` | safe review projection list | Candidate review DTO; Safety review reference remains authoritative |
| `getReviewDetail` | `GET /api/v1/reviews/{review_id}` | `SupportOrchestrator.review_detail` | RealDatabaseAdapter.review read | `ReviewRepository` read projection | review case/event state and safe metadata | Candidate review DTO |
| `submitReview` | `POST /api/v1/reports/{report_id}/reviews` | `SupportOrchestrator.review` | real Safety review transition + DB review adapter | existing Safety review service and `ReviewRepository.update_case` | review status/events, report projection status, audit | Candidate review request/response; DB review state vocabulary |

## DTO discrepancies and resolution

### CAT item state vs frozen assessment object

The frozen `assessment.v1` object has no current question field. The existing Vue provider requires a student-safe current item. Resolution: preserve the frozen assessment object exactly and add a candidate `GET /assessments/{id}/state` response containing only `item_id`, prompt, published options, answer count, and completion state. CAT internal theta/SE/parameters are never returned to the browser.

### Backend response state vs frontend `AssessmentState`

The current Backend response envelope only guarantees `assessment_id` and `status`; the Vue view also needs subject, current index, current item, answer count, completion flag, and max items. Resolution: add these optional/additive fields to the candidate state DTO and map them in `RealApiProvider`. Existing root fields and status semantics remain unchanged.

### Database report table vs Backend `ReportRecord`

The Database schema intentionally has no report/generation table. Resolution: `ReportRecord` is a Backend projection over `support_runs` plus encrypted `APPROVED_OUTPUT` message, `support_evidence`, and Safety/review rows. No table is added and no raw candidate is persisted before Output Safety approval.

### Database hashed CSRF vs Backend raw CSRF view

The Database stores only the CSRF hash. Resolution: real sessions derive the session-bound CSRF token from the opaque session token and a runtime secret, store only its hash through `AuthSessionStore`, and compare supplied headers by hash. The raw token is returned only at login/CSRF retrieval and held in the browser/provider memory.

### In-memory idempotency vs database claim/complete

Memory idempotency remains for unit mode. Real mode maps Backend scope/key/fingerprint to `IdempotencyStore.claim` and `complete` inside short transactions. A different request fingerprint under the same scope/key is a workflow conflict.

### RAG configured reranker vs integration default

The RAG config contains a reranker model, while the accepted Round 1 behavior keeps default reranking off. The transport service explicitly replaces the plan flag with `False`; no model or algorithm is changed. Reranker enable remains an explicit future profile.

### LLM Runtime streaming API vs student behavior

The Runtime exposes both `generate` and `stream_generate`. Round 1 maps only buffered `generate`; the Backend never streams partial output to a student and does not retry after partial output.

## Conflict status

No discrepancy currently requires a frozen root contract change, Database schema redesign, Safety policy change, CAT algorithm change, RAG strategy redesign, or LLM model strategy redesign. If implementation evidence contradicts this statement, the work must stop and create `15_demo/integration/reports/INTEGRATION_BLOCKER.md` rather than silently changing an accepted boundary.

