# Contract/API Hardening Round 1 Acceptance

**Final status: PARTIAL PASS**
Date: 2026-09-06 (Asia/Shanghai)
Scope: Stage 0 reconstruction plus candidate-only API hardening

## Controller summary

The accepted Software Integration Round 1 baseline was reconstructed and
committed locally. The browser-facing candidate is now generated directly from
FastAPI/Pydantic, has typed success responses and stable operation IDs, keeps a
single typed RFC 9457 error path, preserves provenance through report
readback, and distinguishes `NOT_RUN` from controlled synthetic execution.

The result is not a promotion acceptance. oasdiff found compatibility breaks
against both comparison documents, two Respect workflows need a supported
opaque-cookie handoff, and live MySQL evidence was unavailable. The root v0.1.0
contract was not modified or promoted.

## Baseline and frozen boundary

- Required baseline commit: `65c3df2c28f955a3cbadfc3e01c466d6d89f81a6`
  (`chore: establish Software Integration R1 accepted baseline`).
- Required tag: `integration-r1-accepted`.
- Local cleanup commit after baseline: `dfbf1bd`; no remote is configured.
- Frozen root OpenAPI SHA-256:
  `235C8FDB0B35F2DE870127A18D4CD8C72A1C7795AF02656B2A6C7274AB071897`.
- Frozen v1 schema and root governance hashes remained unchanged; the official
  root gate is 13/13.
- Candidate SHA-256:
  `5E3B5BB8327146D82ECC3210DCE76FE1244E53EED95764C31DDA29B953641673`.

## Candidate contract result

- OpenAPI 3.1.0, 21 paths, 21 operations.
- 21 unique deterministic operation IDs; the nine accepted integration IDs
  were preserved.
- 21/21 meaningful 2xx responses have explicit non-empty JSON schemas.
- Request DTOs remain strict; response DTOs are explicitly typed without a
  global `additionalProperties=false` policy.
- Redocly CLI 2.51.2: 0 errors, 0 warnings.
- Problem Details is documented as `application/problem+json` with typed
  field errors and no request-value echo.

## Provenance and execution state

The machine probe recorded a normal synthetic response with HTTP 202,
`EXECUTED`, `CONTROLLED_SYNTHETIC`, two citations, full citation identity, and
report citation equality. The crisis response recorded HTTP 202,
`NOT_RUN`, `NOT_RUN`, and null model/model-version/runtime-version. Evidence:
`evidence/provenance-machine-evidence.json`.

## Verification matrix

| Check | Result | Evidence |
|---|---|---|
| Root contract gate | 13/13 | command output; frozen hashes |
| Backend tests | 16 passed | module-local pytest |
| Backend Ruff / Pyright | passed | module-local quality checks |
| Database module tests | 10 passed, 6 skipped | MySQL service unavailable for integration subset |
| Frontend typecheck | passed | `10_frontend` |
| Frontend lint | passed | `10_frontend` |
| Frontend unit tests | 9/9 passed | 3 files |
| Frontend build | passed | production Vite build |
| Schemathesis coverage/fuzzing | 614/614 passed across 21/21 operations | `evidence/schemathesis-coverage-fuzzing.*` |
| Schemathesis Stateful | 6/6 passed in 1 inferred-link scenario | `evidence/schemathesis-stateful.*` |
| Arazzo/Respect reviewer queue | 1 workflow, 2 steps, 8 checks passed | `evidence/respect-review.json` |
| Arazzo/Respect normal and crisis | blocked after login at 403 | `evidence/respect-normal.json`, `evidence/respect-crisis.json` |
| oasdiff compatibility | exit 1 for both comparisons | `OASDIFF_COMPATIBILITY_REPORT.md` |
| Hey API SDK | 0.99.0 exact; 16 files; two generations byte-identical | `evidence/sdk-generation-manifest.json` |
| Gitleaks | 0 findings in post-hardening tree and history | `evidence/gitleaks-*.json` |

## Material limitations

- The oasdiff findings require an owner-approved compatibility/migration
  decision before any v0.2 promotion.
- Respect does not retain the opaque cookie emitted by login. The attempted
  explicit forwarding sent the full `Set-Cookie` attribute string, and the API
  correctly rejected the mutation. No session-security weakening was added.
- The final database run did not have a live MySQL service. The migration and
  source/module tests pass; live persistence evidence remains pending.
- No fresh Playwright/browser E2E run was required for this candidate-only
  round; previously accepted browser evidence remains historical and is not
  counted as a fresh hardening check.

## Promotion decision

Promotion is **proposal-only and on hold**. See
`CONTRACT_PROMOTION_PROPOSAL_V0_2.md`. No root contract edit, remote operation,
release, or v0.2 promotion was performed.
