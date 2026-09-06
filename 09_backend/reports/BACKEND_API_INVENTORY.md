# Backend API Inventory

Date: 2026-09-05

The root route /api/v1/health is implemented against the existing frozen
contract. The other routes are Backend-local provisional APIs and are not
silently added to the root OpenAPI.

| Method | Path | Auth / function and data scope | Sensitive? | CSRF | Rate limit | Response DTO | Main errors | Owner | Status |
|---|---|---|---|---|---|---|---|---|---|
| GET | /health/live | No | No | No | No | liveness object | 400/500 | health | provisional |
| GET | /health/ready | No | No | No | No | readiness envelope | 500 | health | provisional |
| GET | /health/dependencies | No; capability-only matrix | Low operational | No | No | dependency matrix envelope | 500 | health | provisional |
| GET | /api/v1/health | No | Low operational | No | No | frozen health envelope | 500 | health | frozen path |
| POST | /api/v1/auth/login | No; creates session | Credential input | Origin/Fetch Metadata | login bucket | LoginResponse | 401, 403, 422, 429 | auth | provisional |
| POST | /api/v1/auth/logout | Authenticated actor | Session mutation | Synchronizer token plus origin checks | No | LogoutResponse | 401, 403 | auth | provisional |
| GET | /api/v1/auth/me | Authenticated actor | Actor identity | No | No | ActorDto envelope | 401 | auth | provisional |
| GET | /api/v1/auth/csrf | Authenticated actor | CSRF token | No | No | CsrfResponse envelope | 401 | auth | provisional |
| POST | /api/v1/assessments | Student and own subject only | Assessment input | Synchronizer token plus origin checks | No | AssessmentDto envelope | 401, 403, 409, 422, 502 | assessment | frozen path |
| POST | /api/v1/assessments/{assessment_id}/responses | Student and own assessment | Response input | Synchronizer token plus origin checks | No | AssessmentStateDto envelope | 401, 403, 409, 422, 502 | assessment | frozen path |
| POST | /api/v1/assessments/{assessment_id}/complete | Student and own assessment | Assessment result | Synchronizer token plus origin checks | No | AssessmentDto envelope | 401, 403, 409, 422, 502 | assessment | frozen path |
| POST | /api/v1/retrievals | Authenticated actor with subject scope | Query and citations | Synchronizer token plus origin checks | No | retrieval projection envelope | 401, 403, 422, 502, 503, 504 | support | frozen path |
| POST | /api/v1/safety/checks | Authenticated actor with assessment scope | Safety candidate metadata | Synchronizer token plus origin checks | No | safety decision projection | 401, 403, 422, 502, 503, 504 | support | frozen path |
| POST | /api/v1/support/requests | Authenticated actor with subject scope | User message; candidate buffered | Synchronizer token plus origin checks | support bucket | SupportResult | 401, 403, 409, 422, 502, 503, 504 | support | provisional |
| POST | /api/v1/generations | Authenticated actor with subject scope | Generation request/result | Synchronizer token plus origin checks | support bucket | generation.v1 result envelope | 401, 403, 409, 422, 502, 503, 504 | support | frozen path |
| GET | /api/v1/reports/{report_id} | Actor plus subject scope; teacher projection is reduced | Report content | No | No | ReportDto | 401, 403, 404 | support | frozen path |
| POST | /api/v1/reports/{report_id}/reviews | REVIEWER or ADMIN; review function scope | Review action | Synchronizer token plus origin checks | No | review action envelope | 401, 403, 404, 409, 502, 422 | support | frozen path |
| GET | /api/v1/reviews | REVIEWER or ADMIN | Review metadata | No | No | ReviewProjectionDto list | 401, 403 | support | provisional |
| GET | /api/v1/reviews/{review_id} | REVIEWER or ADMIN | Review metadata | No | No | ReviewProjectionDto | 401, 403, 404 | support | provisional |

## Shared response and error rules

Every request receives bounded request_id and trace_id correlation. Application
errors use RFC 9457 Problem Details with application/problem+json; validation
errors do not echo submitted values. Success payloads are Backend-owned
projections, never raw CAT, RAG, LLM, or Safety objects.

The POST endpoints that create or mutate workflow state accept Idempotency-Key
where a duplicate side effect is possible. Retrieval and Safety check POSTs are
side-effect-free projections. Login rotates and revokes session state as part
of its authentication protocol rather than using a workflow idempotency key.

## Frontend integration note

The frontend should use the provisional OpenAPI report or typed client
generation against the running local Backend app. The recommended development
process is to generate into a frontend-local ignored directory, review the
generated API surface, and then explicitly promote a client artifact. Backend
Round 1 does not write into 10_frontend.
