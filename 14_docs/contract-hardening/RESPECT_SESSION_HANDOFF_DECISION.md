# Respect Session Handoff Decision

Date: 2026-09-07
Installed Redocly CLI / Respect: `2.51.2`

## Decision

Use a narrow loopback-only session bridge for the three synthetic closure
workflows. The bridge is a test harness, not a production application change:

1. Respect performs the real login request.
2. The bridge receives the upstream `Set-Cookie` response.
3. An in-memory `SimpleCookie` jar extracts only the cookie name/value pair.
4. Subsequent requests send `Cookie: name=value`, plus the workflow's real
   CSRF header and the loopback request context.
5. The bridge never persists or logs the session secret and ignores any
   incoming Respect `Cookie` header.

The application retains its opaque server-side session, HttpOnly cookie,
rotation/revocation behavior, CSRF checks, and origin/security middleware.
No production route, authentication mode, cookie setting, or authorization
rule was changed for this tool limitation.

## Respect capability research

The exact installed CLI supports server overrides, runtime input values,
workflow outputs, JSON/HAR output, and `x-security` evaluation. The official
documentation describes server overrides in the form
`sourceDescriptionName=https://test.com` and runtime inputs through `--input`:

- https://redocly.com/docs/respect/commands/respect
- https://redocly.com/docs/respect/extensions/x-security
- https://redocly.com/docs/respect/guides/test-api-sequences

The installed Respect source was also inspected. Its `apiKey` security value
is used as a complete request header value. Passing a raw `Set-Cookie` string
therefore produces an invalid `Cookie` header containing attributes such as
`HttpOnly` and `Path`; the backend correctly rejects that request. Respect's
native handoff was retained as the first attempted mechanism and was not
silently treated as successful.

## Closure evidence

The bridge implementation is
`scripts/respect_session_bridge.py`. Fresh sanitized JSON evidence is:

- `evidence/respect-normal-closure.json`: 1 workflow, 4 steps, 16/16 checks;
  HTTP `200 → 201 → 200 → 202`, `PROCEED`, executed synthetic generation,
  and two citations.
- `evidence/respect-crisis-closure.json`: 1 workflow, 4 steps, 17/17 checks;
  HTTP `200 → 201 → 200 → 202`, `CRISIS_ROUTE`, no content/citations,
  `RETR_not_run`, `NOT_RUN`, null model identity, and a review reference.
- `evidence/respect-reviewer-closure.json`: 1 workflow, 2 steps, 8/8
  checks; HTTP `200 → 200`.

The committed files contain no session value, CSRF value, or credential value.
The full HAR captures remain outside the repository under the isolated closure
run directory and are not part of Git evidence.
