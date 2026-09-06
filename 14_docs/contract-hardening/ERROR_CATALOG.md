# Candidate API Error Catalog

Date: 2026-09-06
Runtime source: `09_backend/src/smhai_backend/core/errors.py`
Media type: `application/problem+json`

The candidate keeps the existing single RFC 9457-style error path. Every
documented problem uses the typed `ProblemDetails` schema and the stable
machine key `code`; clients must not branch on `detail` or `title`.

## Problem envelope

```json
{
  "type": "urn:smhai:problem:<code>",
  "title": "<human-readable title>",
  "status": 422,
  "detail": "request validation failed",
  "instance": null,
  "code": "validation_failed",
  "retryable": false,
  "request_id": "REQ_<synthetic-id>",
  "trace_id": "TRACE_<synthetic-id>",
  "errors": [
    {"loc": ["body", "field"], "code": "string_type", "message": "..."}
  ]
}
```

`errors` is present for field validation failures and contains location,
validator code, and safe message text only. Submitted values are not echoed.
`instance` is nullable because the current runtime does not fabricate a
resource URI. `retryable` is an instance-level decision; it is not inferred by
clients from the HTTP status alone. `Retry-After` is emitted when a rate limit
or dependency path supplies it. The 405 handler preserves the framework's
`Allow` header.

## Stable codes

| Code | Default HTTP status | Meaning and client action |
|---|---:|---|
| `auth_invalid_credentials` | 401 | Credentials were rejected; do not retry blindly. |
| `auth_session_expired` | 401 | Session is absent or expired; return to login/session recovery. |
| `auth_session_revoked` | 401 | Session was revoked; require a new login. |
| `csrf_failed` | 403 | Browser mutation origin or CSRF token failed; refresh session state and retry only after user action. |
| `forbidden` | 403 | Actor is authenticated but lacks the required permission. |
| `resource_not_found` | 404 | The requested resource is not available to this actor. |
| `validation_failed` | 422 | Request shape or field constraints failed; use `errors` for field repair. |
| `workflow_conflict` | 409 | The requested state transition is not valid for the current resource state. |
| `rate_limited` | 429 | Retry only according to `Retry-After` and client backoff policy. |
| `dependency_timeout` | 504 | An upstream dependency timed out; `retryable` is true when the runtime marks it transient. |
| `dependency_unavailable` | 503 | A required upstream dependency is unavailable; inspect `retryable`. |
| `dependency_invalid_response` | 502 | An upstream response failed contract validation; do not blindly replay. |
| `internal_error` | 500 | Unexpected server failure; client behavior is limited to safe retry policy and request correlation. |

## Documentation coverage

Route decorators call `problem_responses(...)`, which always includes the
typed validation response and a typed 400 malformed-request response, then
adds the route's declared domain codes. Runtime handlers still own the actual
status/code selection, so the catalog is not a second error implementation.

The validation regression test sends an extra synthetic field and verifies
that the response is `validation_failed`, uses `application/problem+json`,
contains typed field errors, and does not contain the submitted sentinel.
