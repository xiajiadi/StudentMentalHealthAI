# D3 Prompt Projection Seam Technical Decision V1

**Status:** FROZEN FOR BOUNDED REPAIR
**Decision owner:** Project Controller
**Scope:** D3-4A projection consumption only
**Baseline:** `d3-slice3-r1-accepted` / `cb28fe38b2e1df1b06c96610419691dd2d7924db`
**Seam commit:** `0dc5c7762baf3ba1292de6e6e9d540e4aeafc58d`

This decision authorizes the smallest accepted-module seam needed for the
formal Backend path to consume the already accepted D3-3
`PromptFacingProjection`. It does not approve psychology, legal, consent,
rights, real-student, real-pilot, or production use. It does not start D4.

## Decisions

| ID | Frozen decision |
|---|---|
| D3SEAM-01 | D3-3 `PromptFacingProjection` is the upstream prompt-facing authority for the formal normal Backend path. |
| D3SEAM-02 | D3-1 exposes a dedicated projection-aware `render_projected` seam; the existing `render` API remains only for standalone/internal compatibility tests. |
| D3SEAM-03 | The formal Backend path calls `render_projected` and has no legacy `render` call. |
| D3SEAM-04 | The seam accepts the exact typed `PromptFacingProjection`; a mapping, denial envelope, audit projection, or forged object is rejected. |
| D3SEAM-05 | Only `READY_FOR_PROMPT` projections may cross the seam. |
| D3SEAM-06 | The seam revalidates the projection against the trusted request role, execution context, and request-bound retrieval order. |
| D3SEAM-07 | Trusted prompt chunks are immutable snapshots derived from the same `RetrievalEvidenceBundle`; no fresh retrieval is performed for citation resolution. |
| D3SEAM-08 | Every projection citation must be present exactly once in the same trusted chunk set and match chunk, document, content hash, and locator identity. |
| D3SEAM-09 | Only the four public projection fields (`status`, `claims`, `limitations`, `citations`) are embedded in the bounded prompt context. |
| D3SEAM-10 | Audit, policy, internal role metadata, session material, credentials, and other non-public fields never enter the prompt projection. |
| D3SEAM-11 | Raw `theta` and `SE` remain outside the rendered prompt. |
| D3SEAM-12 | D3-2 policy identity, D3-3 policy identity, role, purpose, relationship, and disclosure are validated at their owning seams and are not reconstructed by D3-1. |
| D3SEAM-13 | A projection cannot resurrect a claim removed by D3-3; D3-1 formats the supplied public projection only. |
| D3SEAM-14 | Teacher remains coarse and zero-personalized; Parent `REAL_USER` remains blocked; Admin has no psychology prompt path. |
| D3SEAM-15 | Student synthetic `READY_FOR_PROMPT` projections render successfully when trusted context and same-bundle evidence are valid. |
| D3SEAM-16 | Existing refusal, abstention, schema, policy, citation, and template validation behavior remains fail closed. |
| D3SEAM-17 | Existing D3-1 template bytes, versions, registry entries, policy hashes, and template hashes are frozen. |
| D3SEAM-18 | No D3-1 psychology semantics, D3-2 semantics, D3-3 semantics, RAG source/algorithm, Safety source/architecture, Runtime, Root contract, OpenAPI, or database schema changes are authorized by this decision. |
| D3SEAM-19 | The D3INT-43 causal regression must show that changing one permitted projection value changes only the bounded projection section while context, trusted chunks, and template remain constant. |
| D3SEAM-20 | This seam decision is engineering-only. It does not grant Controller acceptance of D3-4, real-student disclosure, real-pilot authorization, psychology approval, or production enablement. |

## Implementation binding

The accepted 07 source now validates the exact projection type, public allowlist,
READY status, trusted chunk identity/order, and citation identity before
rendering. The projection is copied into the existing assessment context JSON,
so the template bytes remain unchanged while the projection is causally
consumed. The 09 Backend D3 chain passes the typed projection from D3-3 into
that seam and includes a regression that raises if the formal path calls the
legacy renderer.

The seam gates passed in the candidate worktree: Prompt Engine full suite,
D3-3 focused checks, Ruff check, Ruff format check for touched files, targeted
Pyright, compile/import, and `git diff --check`. Integration Commit 2 `b1a99326885be0fd93adbf8a46db8c14740bef63` is the separate
local publication boundary after the final GPU Normal evidence review; this seam
decision does not create it. The D3-4 evidence and evaluation records contain
the GPU-backed Normal closure.
