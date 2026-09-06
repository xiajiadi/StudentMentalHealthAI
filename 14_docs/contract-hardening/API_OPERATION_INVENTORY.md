# Hardened Candidate API Operation Inventory

Date: 2026-09-06 (Asia/Shanghai)
Source: `create_app().openapi()` from the Backend application
Candidate: `00_architecture/contracts/candidates/openapi.hardened.candidate.json`
Candidate SHA-256: `556ED7A3F777D83C0DE828DF08B7AC51A730ACEDCBE42B9153D4B4414C5F1940`

The source-generated candidate is OpenAPI 3.1.0 with 21 paths and 21
operations. Operation IDs are unique and deterministic. All 21 meaningful 2xx
responses have a non-empty JSON schema; the source does not use an unexplained
`{}` success schema. The machine-readable operation map is
`evidence/operation-id-map.json`.

`session+csrf` means that runtime mutation protection requires the configured
session cookie and CSRF header. FastAPI emits dependency-derived security
requirements alongside the explicit combined requirement; the candidate is
not a promise that either credential is sufficient on its own.

| Method | Path | operationId | 2xx | Success schema | Runtime boundary |
|---|---|---|---:|---|---|
| POST | `/api/v1/assessments` | `createAssessment` | 201 | `ApiEnvelope_AssessmentDto_` | session+csrf |
| GET | `/api/v1/assessments/{assessment_id}` | `getAssessment` | 200 | `ApiEnvelope_AssessmentDto_` | session |
| POST | `/api/v1/assessments/{assessment_id}/complete` | `completeAssessment` | 200 | `ApiEnvelope_AssessmentDto_` | session+csrf |
| POST | `/api/v1/assessments/{assessment_id}/responses` | `recordAssessmentResponse` | 200 | `ApiEnvelope_AssessmentStateDto_` | session+csrf |
| GET | `/api/v1/assessments/{assessment_id}/state` | `getAssessmentState` | 200 | `ApiEnvelope_AssessmentStateDto_` | session |
| GET | `/api/v1/auth/csrf` | `authCsrf` | 200 | `ApiEnvelope_CsrfResponse_` | session |
| POST | `/api/v1/auth/login` | `authLogin` | 200 | `ApiEnvelope_LoginResponse_` | public |
| POST | `/api/v1/auth/logout` | `authLogout` | 200 | `ApiEnvelope_LogoutResponse_` | session+csrf |
| GET | `/api/v1/auth/me` | `authMe` | 200 | `ApiEnvelope_ActorDto_` | session |
| POST | `/api/v1/generations` | `createGeneration` | 202 | `ApiEnvelope_GenerationProjection_` | session+csrf |
| GET | `/api/v1/health` | `getHealth` | 200 | `ApiEnvelope_ApiHealthDto_` | public |
| GET | `/api/v1/reports/{report_id}` | `getReport` | 200 | `ApiEnvelope_ReportDto_` | session |
| POST | `/api/v1/reports/{report_id}/reviews` | `reviewReport` | 200 | `ApiEnvelope_ReviewActionResponseDto_` | session+csrf |
| POST | `/api/v1/retrievals` | `createRetrieval` | 200 | `ApiEnvelope_RetrievalResponseDto_` | session+csrf |
| GET | `/api/v1/reviews` | `listReviews` | 200 | `ApiEnvelope_list_ReviewProjectionDto__` | session |
| GET | `/api/v1/reviews/{review_id}` | `getReview` | 200 | `ApiEnvelope_ReviewProjectionDto_` | session |
| POST | `/api/v1/safety/checks` | `checkSafety` | 200 | `ApiEnvelope_SafetyResponseDto_` | session+csrf |
| POST | `/api/v1/support/requests` | `createSupport` | 202 | `ApiEnvelope_SupportResult_` | session+csrf |
| GET | `/health/dependencies` | `healthDependencies` | 200 | `ApiEnvelope_dict_str__DependencyStatusDto__` | public |
| GET | `/health/live` | `healthLive` | 200 | `HealthLiveDto` | public |
| GET | `/health/ready` | `healthReady` | 200 | `ApiEnvelope_HealthReadyDto_` | public |

## Stable operation ID compatibility

The nine operation IDs already used by the accepted integration candidate were
preserved: `getHealth`, `createAssessment`, `recordAssessmentResponse`,
`completeAssessment`, `createRetrieval`, `checkSafety`, `createGeneration`,
`getReport`, and `reviewReport`. The remaining IDs are explicit source-level
names rather than FastAPI-generated names.

## Source and generation checks

- The candidate exporter imports the actual Backend app and serializes
  `create_app().openapi()`; the previous runtime patch/merge path was removed.
- `09_backend/tests/test_contract_api_hardening.py` checks OpenAPI 3.1.x,
  unique IDs, typed success responses, Problem Details, and security schemes.
- The candidate was regenerated twice for the SDK and the generated trees were
  byte-identical. See `evidence/sdk-generation-manifest.json`.
