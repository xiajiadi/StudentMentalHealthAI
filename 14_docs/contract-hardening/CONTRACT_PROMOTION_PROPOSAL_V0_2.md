# Contract v0.2 Promotion Proposal

**Decision state: PROPOSAL ONLY — HOLD / NOT READY FOR PROMOTION**
**Date:** 2026-09-06
**Candidate:** `00_architecture/contracts/candidates/openapi.hardened.candidate.json`
**Candidate SHA-256:** `5E3B5BB8327146D82ECC3210DCE76FE1244E53EED95764C31DDA29B953641673`

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
