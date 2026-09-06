# Contract/API Hardening Technical Decision v1

**Status:** candidate implementation baseline; root contract v0.1.0 remains FROZEN
**Date:** 2026-09-06
**Scope:** Stage 0 + Contract/API hardening Round 1

## Decision

The browser-facing candidate contract will be generated directly from the FastAPI application with FastAPI/Pydantic v2 as the source of truth. The candidate remains OpenAPI 3.1.x and is written to `00_architecture/contracts/candidates/openapi.hardened.candidate.json`. The frozen `00_architecture/openapi.v1.json` and all frozen `*.v1.schema.json` files are read-only for this round.

The API boundary will use one typed envelope, explicit response DTOs for meaningful 2xx responses, deterministic operation IDs, and the existing RFC 9457 error handler. Request DTOs remain strict (`extra=forbid`); response DTOs ignore unknown fields to permit compatible additive evolution. Human-readable `detail` is presentation text only. Client behavior is keyed by the stable problem `type` and `code`.

Provenance will be carried as a first-class candidate projection from retrieval chunks through orchestration, persistence evidence, report reconstruction, and the API. A citation keeps its stable citation/chunk/document identity, rank, locator, source version, and content hash where available. Legacy persisted rows may have null fields; the adapter will expose null rather than infer or fabricate them.

Crisis/no-call paths will explicitly emit `generation_status=NOT_RUN`, `candidate_source=NOT_RUN`, and `model_id/model_version/runtime_version=null`. If a model candidate was actually produced and then blocked by Safety, the projection retains that execution identity and labels the source `CONTROLLED_SYNTHETIC` where the returned content is a controlled fixture. The existing frozen generation payload remains structurally compatible; the candidate adds execution-state metadata in its projection rather than changing the frozen root schema.

Session and CSRF authentication will remain cookie/header based. OpenAPI will describe the existing session cookie and CSRF header through FastAPI security schemes while runtime validation continues to use the configured cookie/header names. No API version negotiation or `/v1` migration is introduced.

## Alternatives considered

| Choice | Decision | Reason |
| --- | --- | --- |
| Manually patch generated OpenAPI | Reject | It hides source/runtime drift and violates the source-of-truth gate. |
| Add a second error framework | Reject | The existing RFC 9457 handler already owns runtime behavior. |
| Make every response `additionalProperties=false` | Reject | It would turn compatible additive response fields into unnecessary breaks. |
| Put provenance only in generated content | Reject | It is lost when content is blocked, reviewed, persisted, or reconstructed. |
| Change the frozen v0.1 contract | Reject | Root governance requires versioning, migration, and approval for breaking changes. |
| Use Arazzo 1.1 | Reject for this round | Redocly Respect currently documents Arazzo 1.0.1 support; workflows therefore use 1.0.1. |

## Observable acceptance criteria

1. The source-generated candidate has a unique deterministic operation ID for every operation and a real schema for every meaningful 2xx response.
2. Unknown request fields are rejected with the existing `application/problem+json` shell and typed validation details without echoing request values.
3. Candidate OpenAPI, Redocly lint, oasdiff comparison, Schemathesis execution, and three Arazzo workflow descriptions are produced or explicitly marked NOT_RUN with the blocking evidence.
4. A normal synthetic workflow preserves citation identity through API and report readback; blocked/crisis workflows do not claim a model ran.
5. The generated Hey API SDK is regenerated twice with exact `@hey-api/openapi-ts` 0.99.0 and the frontend adapter consumes the candidate response/error shape without hand-editing generated files.
6. Secret scans cover the pre-Git tree, post-ignore tree, staged/baseline history, and post-hardening tree. Findings are redacted and classified.

## Explicit boundaries

- Synthetic/deidentified fixtures only; no real student or minor data.
- No diagnosis, treatment, clinical claim, automatic notification, root contract promotion, remote operation, release, or UI redesign.
- MySQL schema changes are limited to the proven provenance evidence gap. If MySQL is unavailable, database integration remains pending rather than represented as PASS.
