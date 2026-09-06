# OWASP API Security Mapping

Date: 2026-09-05  
Scope: Backend Round 1 provisional API and the frozen health route

| OWASP API Security Top 10 item | Relevant? | Control | Test / evidence | Remaining limitation |
|---|---|---|---|---|
| API1 Broken Object Level Authorization | Yes | NativeAuthorizationProvider checks the subject data scope on assessment, retrieval, support, report, and review resources; public IDs are opaque but never trusted as authorization | tests/test_backend_round1.py::test_bola_bopla_and_bfla proves student_b cannot read student_a's report | Relationship data is in-memory; school-specific relationship policy awaits Database/authorization decisions |
| API2 Broken Authentication | Yes | Argon2 via pwdlib, generic invalid-credential response, opaque server-side session cookie, session rotation, revocation, expiry handling | test_auth_argon2_rotation_csrf_and_logout_invalidation | No OAuth/OIDC, MFA, password reset, or distributed session store |
| API3 Broken Object Property Level Authorization | Yes | Strict Pydantic request DTOs with extra=forbid; output DTOs are explicit and review projections exclude internal subject/timestamp fields; raw candidate content is not returned when blocked | test_bola_bopla_and_bfla; strict request validation returns a Problem Details 422 | Future persistent adapters must preserve field-level projection rules |
| API4 Unrestricted Resource Consumption | Yes | Bounded request fields, bounded retrieval top_k, explicit dependency deadlines/timeouts, per-bucket single-process rate limits, no unbounded streaming | test_idempotency_and_rate_limit; explicit timeout tests in HTTP client and support orchestrator | Limiter is process-local and not a distributed production control |
| API5 Broken Function Level Authorization | Yes | Function checks are native and route dependencies require authenticated actors; review list/action requires REVIEWER or ADMIN | test_bola_bopla_and_bfla student review request returns 403 | Admin provisioning and full school role model are deferred |
| API6 Unrestricted Access to Sensitive Business Flows | Yes | Mutating flows require CSRF, support/generation are rate-limited and idempotency-aware, crisis route creates a review projection and never publishes normal generation | vertical slice and crisis assertions | Abuse detection and distributed quotas need production infrastructure |
| API7 Server Side Request Forgery | Yes | Only validated configuration-owned module base URLs construct HTTP clients; no request field can select a URL; localhost defaults disable proxy environment use | configuration validators and test_long_lived_httpx_local_policy_and_explicit_timeouts | Production egress policy belongs Deployment/network controls |
| API8 Security Misconfiguration | Yes | Explicit CORS allowlist, TrustedHost, security headers, production cookie validator, docs config, no public debug endpoint or raw stack response | app factory settings tests and Problem Details tests | Production HTTPS and deployment headers require deployment acceptance |
| API9 Improper Inventory Management | Yes | BACKEND_API_INVENTORY.md lists every route, auth, CSRF, rate limit, DTO, owner, status, and frozen/provisional boundary; provisional OpenAPI is generated from the actual app | inventory and OpenAPI validation checks | Root contract evolution still requires a formal change request |
| API10 Unsafe Consumption of APIs | Yes | Long-lived HTTPX adapter maps statuses and JSON shape, uses explicit timeouts, propagates correlation, performs no blind retry, and validates Safety decisions; mandatory Safety failures close the generation path | real Safety harness plus fake contract tests and integration matrix | CAT/RAG/LLM formal HTTP contracts are still open integration requests |

## Cross-cutting evidence

- Error responses use application/problem+json and include type, title, status,
  detail, request_id, and trace_id without internal exception details.
- Operational logs carry correlation and safe metadata only; passwords, cookies,
  prompts, candidates, and raw psychological messages are excluded.
- Safety is a mandatory gate: input, retrieval, and output checks are ordered
  in the support service, and CRISIS_ROUTE bypasses RAG and LLM.
