# Backend Round 1 Security Evidence

Date: 2026-09-05  
Scope: `09_backend` provisional API, in-memory adapters, and the real loopback
Safety client

## Result

The targeted Backend security checks passed. The evidence is limited to the
process-local Round 1 implementation; it is not production persistence,
distributed abuse protection, or a school-specific authorization decision.

| Control | Result | Evidence |
|---|---|---|
| Session cookie flags | PASS | `core/config.py`, `domains/auth/router.py`; production validation requires `__Host-smhai_session`, Secure, HttpOnly, SameSite=Lax, Path=/, and no Domain |
| Session rotation and revocation | PASS | `InMemorySessionStore.rotate/revoke`; `test_auth_argon2_rotation_csrf_and_logout_invalidation` |
| CSRF synchronizer token | PASS | session-bound random token, `X-CSRF-Token`, Origin/Referer and Fetch Metadata checks; auth and CSRF tests |
| CORS and trusted hosts | PASS | configuration-owned allowlists; wildcard origins rejected; `CORSMiddleware` and `TrustedHostMiddleware` in `app_factory.py` |
| BOLA | PASS | Student B cannot read Student A's report in `test_bola_bopla_and_bfla` |
| BOPLA / mass assignment | PASS | request schemas use `extra="forbid"`; hidden `subject_id` input is rejected; blocked candidate is not returned |
| BFLA | PASS | Student access to review list/action is denied by `NativeAuthorizationProvider` and tested |
| Rate limiting | PASS | separate login/support in-memory buckets return 429 and Retry-After; `test_idempotency_and_rate_limit` |
| Problem Details | PASS | `application/problem+json`, stable code, type, title, status, detail, request_id, trace_id; `test_problem_details_and_origin_fetch_metadata` |
| Log privacy | PASS | vertical slice captures structured request logs and asserts no password, session/CSRF token, raw message, or crisis marker; no request body is logged |
| SSRF prevention | PASS | module URLs are validated configuration fields; credentials/fragments and non-http(s) URLs are rejected; no user-controlled fetch endpoint |
| Safety fail closed | PASS | Safety unavailable returns 503 and the support service makes zero RAG/LLM calls; `test_safety_down_fails_closed` |
| Output publication gate | PASS | unsafe synthetic candidate yields `needs_review`, `content=null`, and the candidate marker is absent from the response |

## Session and credential evidence

The browser receives only an opaque `secrets.token_urlsafe(32)` reference. The
session record, user identity, expiry, and CSRF token remain server-side. Login
revokes an existing cookie session before creating a new one. Logout revokes the
server record and deletes the cookie. Passwords use `pwdlib.PasswordHash.recommended()`
with Argon2; neither plaintext passwords nor password hashes are logged.

Development/test uses `smhai_dev_session` with Secure disabled only for local
HTTP. Production configuration rejects insecure cookies and requires the
`__Host-` production name. Registration, password reset, OAuth/OIDC, MFA, and
distributed session storage are deferred.

## Authorization evidence

`NativeAuthorizationProvider` evaluates action/function, object, and subject
data scope. It does not trust an opaque identifier as authorization. Student
resources require the actor's own subject; teacher/reviewer projections use
their in-memory accessible subject set; review operations require REVIEWER or
ADMIN. Safety disclosure semantics remain owned by Safety and are not recreated
in Backend.

## Dependency and safety evidence

Every module client has configuration-owned base URL, explicit connect/read/
write/pool timeouts, bounded connection limits, and no generic retry. Loopback
clients use `trust_env=False`. Backend maps upstream responses into typed
projections. Support ordering is input Safety -> RAG -> retrieval Safety -> LLM
Runtime -> output Safety. A non-proceed Safety decision stops the normal path;
CRISIS_ROUTE publishes only the approved Safety response and review reference.

The real loopback Safety service was exercised through `HttpSafetyClient` on
2026-09-05. Its capability health was READY; the normal flow returned
PROCEED and generated a buffered result, while the crisis flow returned
CRISIS_ROUTE, created a review projection, and recorded zero RAG and LLM calls.
The real service was already an independent module process; Backend did not
start or stop it.

## Limitations

- Session, audit, repositories, idempotency, and rate limiting are process-local
  in-memory adapters and are not suitable for multiple workers or production.
- Real CAT, RAG, and LLM Runtime HTTP surfaces were not present in the inspected
  Round 1 modules; their explicit ContractFake adapters remain integration
  requests.
- Production TLS, egress policy, distributed quotas, persistent relationships,
  and deployment process management require later acceptance evidence.
