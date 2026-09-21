# D3 Slice 4 Trusted Backend Integration R1 Implementation Specification

Status: APPROVED_FOR_BOUNDED_IMPLEMENTATION
Date: 2026-09-16
Baseline: cb28fe38b2e1df1b06c96610419691dd2d7924db
Technical decision: D3_BACKEND_INTEGRATION_TECHNICAL_DECISION_V1.md
Supplemental seam decision: D3_PROMPT_PROJECTION_SEAM_TECHNICAL_DECISION_V1.md

This specification derives its scope from D3INT-01 through D3INT-60. It
authorizes a bounded implementation in 09_backend only. It does not change the
Root Contract/OpenAPI, accepted D3 modules, RAG/Safety/Runtime algorithms,
database schema, psychology review status, legal/consent status, or real-pilot
boundary.

## 1. Actual current routes and canonical entrypoint

The current public Backend routes are:

- POST /api/v1/support/requests
- POST /api/v1/generations
- POST /api/v1/retrievals
- POST /api/v1/safety/checks
- GET /api/v1/reports/{report_id}
- POST /api/v1/reports/{report_id}/reviews
- GET /api/v1/reviews and GET /api/v1/reviews/{review_id}
- the existing auth, assessment, health, and lifecycle routes.

POST /api/v1/support/requests is the canonical normal-generation entrypoint.
POST /api/v1/generations is a contract-shaped adapter into that same entrypoint,
not a second orchestration implementation. POST /api/v1/retrievals is a
side-effect-free projection route; it must not become a trusted citation source
for a later generation unless its result is explicitly bound to the same
request transaction. No preview, regenerate, retry, legacy, or raw Runtime
route is present; any future such route must delegate to the canonical
orchestrator or be rejected.

## 2. Controlled integration seam

D3 code is present in the accepted baseline under:

- 03_assessment-adapter/src/assessment_adapter
- 07_prompt-engine/src/prompt_engine

Backend may import those accepted packages through a bounded local integration
adapter. The adapter must preserve their typed construction seams and exact
asset paths. It must not copy or reimplement CAT, D3-2, D3-3, D3-1, RAG, Safety,
or Runtime algorithms. A plain request mapping must never be passed where a
trusted D3 context object is required.

The actual accepted call signatures are:

InterpretationAdapter.interpret(
    InterpretationRequest,
    TrustedInterpretationContext
) -> InterpretationResult

prompt_engine.role_projection.project(
    source_result,
    policy_reference,
    TrustedAudienceContext,
    citations
) -> RoleProjectionResult

prompt_engine.role_projection.prompt_input(
    PromptFacingProjection
) -> dict

prompt_engine.engine.render_projected(
    assessment,
    generation_request,
    chunks,
    policy_ref,
    TrustedPromptContext,
    PromptFacingProjection
) -> RenderedPrompt

The existing ``render`` wrapper remains only for standalone/internal
compatibility tests; the formal Backend path uses ``render_projected``.

The integration adapter is responsible only for server-derived context,
exact identity checks, typed conversion, and error mapping.

## 3. Server-derived trusted request context

Construct TrustedRequestContext after session authentication and object
authorization. Values are derived as follows:

- transaction_id: Backend generated per orchestration transaction and correlated
  with the request/trace context.
- principal_id: verified opaque session -> server account.
- product_role: server account role and native authorization state.
- subject_id: persisted assessment subject after object-scope authorization.
- purpose: fixed role/use-case mapping in Backend.
- relationship: persisted ownership, trusted assignment, or controlled
  synthetic relationship.
- execution_mode: server configuration/workflow, synthetic demo for this slice.
- disclosure_state: server role/relationship policy, never caller supplied.

Request role, purpose, relation, mode, consent-like, review/rights, safety, scope,
and citation fields are either forbidden by the DTO or treated as
non-authoritative assertions. Mismatches fail closed.

## 4. Assessment binding

Before D3-2, load the assessment record, require completed status, verify the
path/body assessment_id, resolve subject_id from the record, and compare any
caller subject assertion. Verify instrument identity/version and the trusted
synthetic fixture mapping explicitly. Do not change CAT theta, SE, risk, stopping
evidence, or construct meaning.

The accepted D3-2 policy is exact and currently identifies
CURRENT_SYNTHETIC_GRM, synthetic_item_bank.v1 / demo.v1, and
SYNTHETIC_STUDENT_DEMO. The existing legacy Backend fixture uses
synthetic_demo/instrument.synthetic/1.0. The integration must use an explicit,
versioned compatibility fixture or reject the legacy identity; it may not
silently normalize a mismatched assessment into a D3 policy.

## 5. Purpose, relation, disclosure matrix

The only server mappings in this slice are:

| server role/use case | D3-3 audience | purpose | relation | mode | disclosure |
| Student self | STUDENT_SELF | SELF_UNDERSTANDING | SELF | SYNTHETIC_DEMO | SYNTHETIC_SELF |
| Teacher support | TEACHER_SUPPORT | EDUCATIONAL_SUPPORT | ASSIGNED_SUPPORT | SYNTHETIC_DEMO | SYNTHETIC_SUPPORT |
| Parent demo | PARENT_DEMO | SYNTHETIC_PARENT_DEMO | SYNTHETIC_DEMO | SYNTHETIC_DEMO | SYNTHETIC_PARENT_DEMO |
| Admin | SYSTEM_ADMIN | no psychology purpose | none | any | NOT_AUTHORIZED |

Teacher output is coarse and contains no personalized psychological claims.
Parent REAL_USER is blocked; synthetic parent demo is coarse only. Admin has no
psychological superuser access. Age does not authorize parent disclosure.

## 6. Canonical orchestration state machine

The orchestrator records this order and refuses out-of-order calls:

REQUEST_AUTHENTICATED
-> REQUEST_AUTHORIZED
-> INPUT_SAFETY_EVALUATED
-> ASSESSMENT_BOUND
-> INTERPRETATION_READY
-> RETRIEVAL_BOUND
-> ROLE_PROJECTED
-> PROMPT_ASSEMBLED
-> GENERATION_BUFFERED
-> OUTPUT_SAFETY_EVALUATED
-> PERSISTED

Input Safety actions CRISIS_ROUTE, REVIEW_REQUIRED, and BLOCK terminate the
normal path before D3-2, RAG, D3-3, D3-1, or Runtime. Safety remains
authoritative. A dependency-down or integrity failure produces the accepted
problem/error envelope and no normal approved content.

## 7. RAG and RetrievalEvidenceBundle

Call the accepted RagClient once for a normal transaction, with filters derived
from trusted role, content mapping, risk, review, and rights policy. Do not
modify RAG. Convert the response into an immutable bundle containing only
observed fields:

- retrieval_id and request/trace linkage;
- chunk_id, document_id, text/content hash;
- citation title, organization, locator and location;
- review_status, rights_status, population_scope, role_scope, risk_scope;
- trace, index/corpus/build/snapshot/run/rank/score values only when exposed.

A bundle is the exact evidence set for this request. It is not an invented
global index snapshot. Compute bundle_hash as sorted compact UTF-8 JSON with
bundle_hash omitted, then SHA-256. Keep the original canonical payload and
hash; a changed identity, text, scope, rights/review state, or citation fails.

The same frozen bundle feeds retrieval Safety, D3-3 opaque citations, D3-1
trusted chunks, audit, candidate citation validation, and public citation
resolution. No generation-time or post-generation RAG query is permitted.

## 8. D3 composition

D3-2 receives the verified completed assessment and the trusted
interpretation context. Its role-neutral result is not recalculated or
reinterpreted by Backend.

D3-3 receives that result, the server-built TrustedAudienceContext, and
citation references created from the verified bundle. Only prompt_input from
the PromptFacingProjection may proceed. AuditProjection is retained separately.

D3-1 receives the approved role projection, a TrustedPromptContext, and
TrustedChunkContext values derived from the same bundle. The projection-aware rendered prompt is
the only Runtime input. Raw theta/SE, AuditEnvelope, session material,
internal Safety details, and rights internals stay out of the prompt.

## 9. Citation and TOCTOU rules

After Runtime returns a buffered candidate, parse only the accepted structured
generation shape. Every cited chunk must be a member of the bound bundle and
match its identity/content hash. Unknown, duplicate, cross-request, or tampered
citations fail closed. Visible metadata is resolved from the same bundle object.
Mutation or substitution of the bundle after verification invalidates the final
check; the resolver cannot use a second object.

## 10. Safety, output, persistence, and audit

Input Safety precedes all normal generation work. Retrieval Safety remains the
accepted additional gate. The Runtime candidate is fully buffered, then Output
Safety runs, then normal content is exposed and persisted. Unsafe candidates
are not returned or persisted as normal output. No direct streaming path exists.

Persistence reuses existing repository ports and generation.v1 semantics. No
database schema or migration is introduced. Existing idempotency keys replay
the same result and do not invoke RAG/LLM a second time; conflicts remain
explicit.

AuditEnvelope is internal and contains transaction/stage identities, safe
principal/subject references, D3-2/D3-3 policy identities, D3-1 template
identity/version/hash, bundle_hash, opaque evidence IDs, Safety identities,
Runtime identity, and Output Safety identity where available. It never enters
the prompt or public DTO and contains no secrets or unnecessary raw
measurements.

## 11. Test matrix

The D3-4 tests must prove:

1. all caller privilege-forgery fields are ignored/rejected;
2. cross-subject assessment and generation IDOR fail closed;
3. only one canonical generation route reaches Runtime;
4. preview/regenerate/retry/legacy and direct Runtime/raw prompt paths are
   absent or delegated;
5. all three pre-LLM Safety stop actions cause zero normal RAG, D3, prompt, and
   LLM calls;
6. valid RAG response binds a deterministic bundle and hash;
7. metadata/chunk hash/unknown/cross-retrieval/rights/review/D2 citations fail;
8. same-bundle citation resolution passes and post-generation retrieval count
   remains zero;
9. D3-2 -> D3-3 -> D3-1 receives typed trusted contexts and preserves
   role/claim monotonicity;
10. teacher, parent, admin, and REAL_USER boundaries hold;
11. raw theta/SE and AuditEnvelope are absent from the prompt;
12. buffered Output Safety precedes normal persistence and unsafe output is not
   normally exposed;
13. TOCTOU mutation is detected;
14. idempotent replay does not repeat side effects;
15. Backend, static, compile/import, accepted regressions, Root/OpenAPI,
   frozen-root, and available bounded real HTTP checks are recorded.

All tests use synthetic/public/de-identified fixtures only.

## Current closure status

D3SEAM-01 through D3SEAM-20 and D3INT-01 through D3INT-60 are recorded as
fidelity PASS in the companion evidence. Overall D3-4 remains
PARTIAL_PASS/NOT_READY_FOR_CONTROLLER_ACCEPTANCE because the controlled real
HTTP normal and output-unsafe hard gates are unresolved.
