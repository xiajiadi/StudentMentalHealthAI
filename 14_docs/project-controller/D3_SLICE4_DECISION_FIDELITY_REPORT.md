# D3 Slice 4 Decision Fidelity Report

**Status:** READY_FOR_CONTROLLER_REVIEW
**Review date:** 2026-09-21
**Baseline:** d3-slice3-r1-accepted / cb28fe38b2e1df1b06c96610419691dd2d7924db
**Branch:** exp/d3-backend-integration-v1
**Worktree:** D:\Projects\StudentMentalHealthAI-d3-backend-integration

This report compares the implementation and the fresh evidence with the
Frozen Technical Decision D3_BACKEND_INTEGRATION_TECHNICAL_DECISION_V1.md.
The table below is the machine-counted registry of the 60 D3INT decision rows.
Execution Mission section numbers are not decision identifiers.

## Result

| Metric | Count |
|---|---:|
| Expected | 60 |
| PASS | 60 |
| PARTIAL | 0 |
| MISSING | 0 |
| CONFLICT | 0 |
| Semantic deviations | 0 |
| Mission deviations | 0 |

The authorized 07_prompt-engine seam now consumes the exact typed D3-3
PromptFacingProjection. The formal Backend path calls render_projected, the
projection is embedded only through the existing bounded assessment context,
and the direct causal regression passes. The causal seam decision therefore
has no remaining semantic deviation.

The final four decision rows were re-evaluated against the frozen decision text
and the fresh 2026-09-21 evidence. Existing routes and their negative tests are
the complete current route surface; all required evidence is recorded. The
sealed accepted 7B Runtime returned a Normal candidate with GPU residency,
Output Safety PROCEED, and post-safety persistence. The output-unsafe, K12
population, no-eligible-evidence, crisis, and Safety-down real HTTP cases are
also materially closed.

## Decision-by-decision reconciliation

| ID | Status | Reconciliation evidence |
|---|---|---|
| D3INT-01 | PASS | Backend orchestration remains the 09_backend boundary; CAT, D3, RAG, Safety, Runtime, and Database ownership is retained. |
| D3INT-02 | PASS | The service ports preserve Backend to CAT/RAG/Safety/Runtime topology; D3 packages are local typed calls. |
| D3INT-03 | PASS | No new FastAPI, policy, identity, mesh, token, or model service was added. |
| D3INT-04 | PASS | The frozen accepted-module boundary remains unchanged for all listed modules and frozen artifacts. The separately Controller-authorized projection seam is the explicit 07_prompt-engine exception in Commit 1; it changed no template or policy bytes, and all D3-4 product changes remain under 09_backend. |
| D3INT-05 | PASS | Root contract checks pass 13/13 and frozen-root comparison is 8/8 unchanged. |
| D3INT-06 | PASS | Tests and fixtures are synthetic/de-identified only; no real student or clinical records are used. |
| D3INT-07 | PASS | Real pilot remains blocked in the technical decision/specification and no pilot path is enabled. |
| D3INT-08 | PASS | The D2 14-source/58-fragment intake is not copied, promoted, or used by the generation path. |
| D3INT-09 | PASS | The existing opaque server session and native account authorization remain the principal boundary. |
| D3INT-10 | PASS | TrustedRequestContext is capability-guarded and typed; plain mappings and direct construction are rejected. |
| D3INT-11 | PASS | Principal is taken from the verified Actor/server account; forged principal assertions fail closed. |
| D3INT-12 | PASS | Product role and D3 audience are derived from server role; caller role assertions cannot elevate. |
| D3INT-13 | PASS | Subject is resolved from the persisted assessment and authorization scope; caller subject is only checked for consistency. |
| D3INT-14 | PASS | Purpose is a fixed Backend mapping: SELF_UNDERSTANDING, EDUCATIONAL_SUPPORT, synthetic parent, or admin boundary. |
| D3INT-15 | PASS | Relationship is server-derived as SELF, ASSIGNED_SUPPORT, SYNTHETIC_DEMO, or NONE. |
| D3INT-16 | PASS | Execution mode is server policy; caller synthetic/real-user fields cannot switch it. |
| D3INT-17 | PASS | Disclosure state is server policy; caller consent-like fields cannot grant disclosure. |
| D3INT-18 | PASS | Role, purpose, relation, mode, disclosure, safety, review, rights, population, risk, and citation privilege fields are non-authoritative. |
| D3INT-19 | PASS | Conflicting caller assertions are rejected by trusted-context derivation; server state wins. |
| D3INT-20 | PASS | Binding checks assessment ID, completed status, subject, instrument/version, origin, and the explicit compatibility fixture. |
| D3INT-21 | PASS | Student foreign-assessment and generation subject IDOR tests return a closed denial before RAG/LLM. |
| D3INT-22 | PASS | The accepted completed assessment identity is passed through the D3-2 typed seam without recalculation or silent normalization. |
| D3INT-23 | PASS | Student self maps to STUDENT_SELF / SELF_UNDERSTANDING / SELF / SYNTHETIC_SELF. |
| D3INT-24 | PASS | Teacher maps to TEACHER_SUPPORT / EDUCATIONAL_SUPPORT / ASSIGNED_SUPPORT and the accepted coarse no-claim boundary. |
| D3INT-25 | PASS | Parent demo maps to PARENT_DEMO / SYNTHETIC_PARENT_DEMO / SYNTHETIC_DEMO; no real disclosure is enabled. |
| D3INT-26 | PASS | Parent REAL_USER is explicitly rejected; age is not used as disclosure authority. |
| D3INT-27 | PASS | Admin D3 psychology composition is rejected and report reads are reduced to a coarse envelope without generation/citations. |
| D3INT-28 | PASS | D3-3 claim and citation surfaces are checked for monotonicity; no projection promotes a source claim. |
| D3INT-29 | PASS | StageLedger implements the eleven named logical stages. |
| D3INT-30 | PASS | Stage predecessor, duplicate, trusted-context, terminal, and safety-stop preconditions are enforced. |
| D3INT-31 | PASS | Input Safety runs before assessment binding, D3-2, RAG, D3-3, D3-1, or Runtime on the normal path. |
| D3INT-32 | PASS | CRISIS_ROUTE, REVIEW_REQUIRED, and BLOCK terminate the normal path with zero normal downstream calls. |
| D3INT-33 | PASS | D3-2 receives a bound completed assessment and a typed trusted interpretation context. |
| D3INT-34 | PASS | Backend does not calculate theta/SE, severity, cutoffs, or construct meaning; measurement terms are absent from the rendered prompt. |
| D3INT-35 | PASS | Accepted RAG client and current knowledge.v1 projection are used; no BGE-M3/BM25S/RRF/reranker/corpus changes. |
| D3INT-36 | PASS | Retrieval eligibility is server-derived from the trusted context, assessment risk, and observed RAG metadata. |
| D3INT-37 | PASS | Bundle provenance copies only observed chunk and trace fields; no synthetic global index/snapshot identity is introduced. |
| D3INT-38 | PASS | RetrievalEvidenceBundle is a recursive immutable, request-linked exact evidence set. |
| D3INT-39 | PASS | Snapshot semantics mean the exact bound request evidence; snapshot_id remains null when RAG does not expose one. |
| D3INT-40 | PASS | Canonical sorted compact UTF-8 JSON is hashed with SHA-256 excluding bundle_hash; tamper tests pass. |
| D3INT-41 | PASS | One bundle is reused through D3-3, D3-1, audit, citation validation, and display; no citation re-retrieval occurs. |
| D3INT-42 | PASS | D3-3 receives D3-2 output, server-built audience context, and opaque bundle-derived prompt citations. |
| D3INT-43 | PASS | `render_projected` receives the exact typed PromptFacingProjection; its public four-field payload is embedded in the existing bounded assessment context, and the causal test observes the permitted projection difference in the rendered prompt. |
| D3INT-44 | PASS | Prompt construction excludes session material, credentials, audit envelope, raw theta/SE, and unnecessary identity/policy internals. |
| D3INT-45 | PASS | Candidate citation membership, retrieval identity, bundle hash, document identity, content hash, and locator are validated. |
| D3INT-46 | PASS | Visible citation metadata is resolved from the same frozen bundle object with a final integrity check. |
| D3INT-47 | PASS | Missing, pending, unknown, rights-ineligible, review-ineligible, or scope-incompatible evidence fails closed. |
| D3INT-48 | PASS | Psychometric and RAG provenance remain separate; only safe transaction linkage appears in audit. |
| D3INT-49 | PASS | Runtime receives only the accepted rendered prompt and server generation metadata; no raw prompt route exists. |
| D3INT-50 | PASS | Candidate output is buffered; Output Safety runs before normal exposure and normal persistence. |
| D3INT-51 | PASS | Existing repository/schema and idempotency ports are reused; concurrent in-memory claims prevent duplicate generation. |
| D3INT-52 | PASS | Audit carries transaction/stage/policy/template/bundle/opaque evidence/Safety/Runtime identities where available. |
| D3INT-53 | PASS | AuditEnvelope is kept outside prompt/public DTOs; admin projection removes generation and citations. |
| D3INT-54 | PASS | D3 and evidence refusal paths fail closed; no JSON repair, policy weakening, cloud fallback, or blind retry was added. |
| D3INT-55 | PASS | Source-level dependency and publication failure paths preserve no normal approved content; bounded tests cover output/persistence failure cleanup. |
| D3INT-56 | PASS | Review actions use authenticated reviewer/admin scope; role disclosure boundaries remain enforced. |
| D3INT-57 | PASS | The current route inventory is complete; support and generation converge on the canonical orchestrator, retrieval is side-effect free, and no preview/regenerate/retry/raw Runtime/legacy route exists. Negative tests cover every route that is present. |
| D3INT-58 | PASS | Fresh D3/backend tests cover trusted composition, bundle hash/tamper, unknown and cross-retrieval citations, eligibility, D2 exclusion, TOCTOU, same-bundle display, role boundaries, and idempotency. |
| D3INT-59 | PASS | Fresh test, static, compile/import, accepted-module, CAT, RAG, Safety, Backend, Root, OpenAPI, frozen-root, and bounded real-HTTP results are recorded with their actual pass/fail outcomes and environment facts. |
| D3INT-60 | PASS | The seam commit is local, the GPU Normal hard gate is green, and the reviewed tree is ready for the authorized local Integration Commit 2; merge, push, and accepted tag remain untouched. |

### Decision precedence note

The accepted-module immutability boundary applies to D3-4 integration scope and
frozen module artifacts. The separate Controller-authorized D3SEAM decision
explicitly permits the Commit 1 07_prompt-engine projection-consumption API
seam; it does not alter D3-1 semantics, template bytes, or policy hashes. This
is the recorded exception used when reconciling the accepted-module row.

## Deviations and decisions required

No D3INT semantic deviation remains after the authorized projection seam. The
GPU-backed Normal closure preserved the frozen policy and product boundaries:

- The compatible Normal case uses the two-row
  `SYNTHETIC_VALIDATION_ONLY` University fixture and the sealed accepted
  Runtime identity; no K12-to-University mapping was added.
- The accepted 7B Q4_K_M Runtime was GPU-resident with
  `/api/ps size_vram=5133943438`, returned a candidate in `4208 ms`, and used
  the unchanged product 60-second timeout. No timeout, model, Runtime, RAG, or
  Safety policy was changed.
- The accepted K12 population negative and the teacher-role negative both
  return raw RAG hits but produce zero eligible trusted bundle items before
  D3-3/Runtime.
- The output-unsafe case uses safe input, the exact accepted synthetic
  clinical-overreach candidate, real Output Safety `REVIEW_REQUIRED`, and no
  normal content persistence.

The product-tree fingerprint was identical before and after GPU validation:
79 files and SHA-256 `079e78633997f3b3bad06578296170f7b93a8dd4387e6aa74455879e6a9024a4`.
No product or policy change is authorized by this closure.

## Readiness limitations

- The controlled D2 corpus was the canonical main-worktree publication, SHA-256
  `2D5736AE741D675CA5856B8004665EA3043AECCEA34E2B007498FF04C2B501A2`; the
  temporary copy was byte-identical and removed after validation.
- The University fixture SHA-256 is
  `519efd711d49240f4515713d47a58a250cc84a70457f4997646d98d7ace1ade5` and the
  role-negative fixture SHA-256 is
  `0998157f36c38a635fc146695f2fd8293f95cdd8c6a8143e07de16b2367452a2`.
- RAG full suite: `18 passed, 4 skipped, 2 warnings`.
- Safety full suite: `20 passed, 1 skipped, 3 warnings`.
- Full Backend Pyright retains exactly the two baseline SQLAlchemy import
  errors in `adapters/database.py`; candidate and baseline are both 2 and
  new D3-4 errors are 0.
- Prompt Engine `154 passed`; D3-2 `41 passed`; CAT `24 passed`; Backend `65
  passed`; D3 focused `47 passed`; Backend contracts `16 passed`; Root `13/13`;
  OpenAPI PASS; frozen-root `8/8`; Ruff, format, compile/import, and diff
  checks pass.
- GPU Normal is HTTP 202 with `data.status=generated`, eleven completed ledger
  stages, Runtime candidate buffering, Output Safety PROCEED, and persistence;
- Real HTTP output-unsafe is `REVIEW_REQUIRED` after candidate buffering;
  K12 population and role-negative cases are fail-closed with zero eligible
  bundle items and zero Runtime calls; crisis is PASS with zero normal
  RAG/prompt/Runtime calls; Safety-down is HTTP 503 fail-closed.

## Controller conclusion

The projection-consumption seam is closed with D3SEAM 20/20 and D3INT 60/60,
with zero semantic or mission deviations. D3VAL-01..16 are PASS and frozen.
Root, OpenAPI, frozen-root, accepted module source, template bytes, and template
hashes remain unchanged. The sealed accepted Runtime Normal hard gate is green
with GPU residency, complete stage ledger, Output Safety PROCEED, and
post-safety persistence. The reviewed tree is ready for the authorized local
Integration Commit 2. The output-unsafe, population, evidence, crisis, and
Safety-down gates have fresh real HTTP evidence.

No merge, push, tag, or D4 work was performed.
