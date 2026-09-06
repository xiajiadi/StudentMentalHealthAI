# Contract v0.2 Promotion Proposal

**Decision state: PROPOSAL ONLY — NOT PROMOTED**
**Date:** 2026-09-06
**Candidate:** `00_architecture/contracts/candidates/openapi.hardened.candidate.json`
**Candidate SHA-256:** `556ED7A3F777D83C0DE828DF08B7AC51A730ACEDCBE42B9153D4B4414C5F1940`

This document records a controller-facing proposal. It does not promote or
modify the frozen root contract. `00_architecture/openapi.v1.json` and the
frozen v1 schemas remain byte-unchanged and the official root gate remains
13/13.

## What is proposed for future review

Review the hardened candidate as the basis for a future v0.2 API contract with:

- source-generated OpenAPI 3.1.0 from FastAPI/Pydantic;
- explicit browser-facing response DTOs and deterministic operation IDs;
- one typed RFC 9457 Problem Details family;
- cookie/CSRF security declarations matching runtime enforcement;
- end-to-end citation provenance and execution-state metadata;
- exact Hey API 0.99.0 SDK generation and frontend adapter migration.

## Hold reasons

1. oasdiff reports 226 breaking-level findings against the accepted integration
   candidate and 43 against the frozen root comparison. The findings include
   removed required response properties, nullable/optional Problem Details
   fields, and tightened generation request requirements. A migration or
   compatibility decision is required before promotion.
2. Redocly Respect successfully executed the reviewer queue workflow, but the
   normal and crisis workflows could not carry the opaque `Set-Cookie` value
   through the subsequent CSRF-protected step. Explicit cookie forwarding was
   attempted; Respect sent the full `Set-Cookie` attribute string and the API
   correctly rejected the request with `csrf_failed`. This is a tool/workflow
   evidence gap, not a basis for weakening session security.
3. Live MySQL integration was not available in the final run; six database
   integration tests remain skipped. The source migration and module tests pass.

## Required promotion gates

Before any owner considers v0.2 promotion:

1. Decide whether to preserve the affected legacy fields or publish a formal
   migration/versioning plan; update the candidate and rerun oasdiff.
2. Make the three Arazzo workflows executable with a supported cookie/session
   handoff, or record an approved alternative live workflow harness.
3. Run the database migration and provenance round trip against a real local
   MySQL service and retain machine-readable evidence.
4. Re-run the root hash gate, source export, Redocly, Schemathesis, SDK
   determinism, frontend consumer checks, and secret/history scans from the
   proposed promotion commit.
5. Obtain the contract owner's explicit approval. No promotion, remote
   operation, release, or root-file edit is authorized by this round.

## Acceptance Closure Update

Closure date: 2026-09-07 (Asia/Shanghai)

The previously recorded hold reasons are historical controller state. The
closure reran the required gates against the current candidate and resolved
the evidence gaps without changing the frozen root contract:

- oasdiff raw output remains visible: integration → hardened `76 ERR / 7 WARN`
  and frozen root → hardened `15 ERR / 7 WARN`. Every finding is classified;
  unintentional, unclassified, and pending-owner counts are all zero. The
  `createGeneration` corrections remain candidate-only and still require an
  owner-approved future v0.2 decision.
- Respect 2.51.2 executed all three workflows through the actual Backend
  implementation using an in-memory, loopback-only cookie-pair bridge. The
  bridge forwards only `name=value`, preserves the server's HttpOnly cookie,
  and does not alter production authentication. Sanitized evidence is stored
  under `evidence/respect-*-closure.json`.
- A real isolated MySQL 8.4.8 environment completed the migration stairway,
  provenance persistence, encrypted-message boundary, API readback, and
  post-restart readback. No real student data was used.
- The current candidate was regenerated into the Hey API SDK twice with exact
  `@hey-api/openapi-ts` 0.99.0 output; 16/16 files match the canonical frontend
  directory and no generated file was hand-edited. The current evidence is
  `evidence/sdk-generation-closure.json`.
- Fresh real-mode Playwright completed login, normal support, crisis routing,
  and reviewer approval: `4 passed, 0 failed, 0 skipped`.

The proposal remains **PROPOSAL ONLY — NOT PROMOTED**. Contract-owner approval,
formal v0.2 versioning, and any remote/tag/release action remain outside this
closure.
