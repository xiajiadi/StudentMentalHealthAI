# D3-3 Role Projection and Minimum Disclosure Technical Decision V1

Status: FROZEN FOR BOUNDED IMPLEMENTATION

Authority: Project Controller canonical D3R mapping in the D3-3 Canonical
Decision Fidelity Closure mission. This document materializes the 48
Controller-frozen technical decisions. It does not grant Controller
acceptance, psychology approval, legal or consent approval, real-pilot
readiness, rights clearance, clinical validity, or production readiness.

Scope: D3-3 Role Projection and Minimum Disclosure in 07_prompt-engine.
D3-4 Backend Integration, Safety architecture changes, real consent
workflows, real student data, and production delivery remain out of scope.

Source of truth: repository and accepted evidence. D1 remains
RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK. D2's new 14-source/58-
fragment intake remains rights-unknown, review-pending, and unpublished.
Parent production delivery remains paused. Real student data and a real pilot
remain forbidden/blocked.

## Historical correction record

The prior version in product commit 403acbe37da81e8fb2d5ebb58d6866b4926340b8
used D3R-01 through D3R-48 for execution-mission sections and acceptance
gates. That numbering was not the Controller's canonical D3R meaning. This
closure corrects the document to the exact Controller mapping below without
changing D3-3 product behavior. The prior file and its mistake remain
recoverable in Git history at the product commit above.

## Canonical Controller D3R-01 through D3R-48

### D3R-01 — Module ownership and D3-1 boundary

D3-3 belongs to 07_prompt-engine as an independent Role Projection
submodule; accepted D3-1 core behavior must not be redefined.

### D3R-02 — Deterministic execution

D3-3 is deterministic and MUST NOT call an LLM.

### D3R-03 — D3-2 content authority

The sole content authority is the D3-2 AssessmentInterpretationResult.
D3-3 MUST NOT reread CAT theta/SE.

### D3R-04 — No new psychological meaning

D3-3 MUST NOT interpret, enrich, or infer new psychological meaning.

### D3R-05 — Projection monotonicity

Projected content claims must be a subset of approved canonical source claims.

### D3R-06 — No new claim code

D3-3 MUST NOT create a new psychological claim code.

### D3R-07 — Not an authentication replacement

Role Projection is NOT an authentication/authorization replacement. D3-4
Backend owns real identity and relationship verification.

### D3R-08 — Trusted audience context

D3-3 requires TrustedAudienceContext or a semantically equivalent trusted
context.

### D3R-09 — Caller fields are not authoritative

audience_role, purpose, relation, execution_mode, and disclosure
authorization must not become authoritative merely because a raw caller
supplied them.

### D3R-10 — Attribute-aware authorization

Authorization logic uses role plus subject/object/context attributes and
purpose, not role-only RBAC.

### D3R-11 — Fail-closed policy

Role Projection Policy is fail-closed.

### D3R-12 — No implicit policy fallback

No exact policy means no default, nearest, latest, or wildcard projection.

### D3R-13 — Versioned policy hash

Projection Policy uses versioned JSON plus canonical SHA-256.

### D3R-14 — Exact policy identity

Policy exact identity includes at least role, purpose, execution mode, and
policy id/version/hash as required by implementation.

### D3R-15 — Deny by default

Projection is deny-by-default.

### D3R-16 — Student relation

STUDENT_SELF requires trusted subject relation SELF.

### D3R-17 — Student content allowlist

Student sees only D3-2 approved claims and limitations explicitly permitted
by Student policy.

### D3R-18 — Student governance metadata boundary

Student Prompt-facing payload must not contain internal policy hash,
review-decision identity, internal evidence references, Safety action, or
equivalent governance metadata.

### D3R-19 — Student public-safe limitations

Student may receive explicitly public-safe typed limitations.

### D3R-20 — Teacher default deny

TEACHER_SUPPORT defaults to no individualized psychological assessment
claims.

### D3R-21 — Future Teacher claim source

Future Teacher personalized disclosure may only originate from an explicitly
approved EDUCATIONAL_SUPPORT-type claim.

### D3R-22 — Teacher context requirements

Teacher also requires trusted relation, purpose, and disclosure policy; role
alone is insufficient.

### D3R-23 — No current SUPPORT_TOPIC

Current V0.9 has no approved SUPPORT_TOPIC; shipped Teacher policy therefore
produces zero personalized psychological claims.

### D3R-24 — Synthetic Parent mode

PARENT_DEMO is allowed only for SYNTHETIC_DEMO.

### D3R-25 — Parent real-user block

Parent REAL_USER disclosure remains BLOCKED.

### D3R-26 — No age-only authorization

Age alone MUST NOT automatically authorize parent disclosure.

### D3R-27 — Future real Parent policy

Future real parent disclosure requires separate legal, ethical, and consent
policy.

### D3R-28 — Admin is not a psychology audience

SYSTEM_ADMIN is not a psychological-content audience and has no implicit
full-content access.

### D3R-29 — Unknown values fail closed

Unknown role, relation, or purpose fails closed.

### D3R-30 — Canonical purposes

Current purposes include at least SELF_UNDERSTANDING, EDUCATIONAL_SUPPORT,
and SYNTHETIC_PARENT_DEMO.

### D3R-31 — Trusted purpose

Purpose comes from trusted context, not caller self-assertion.

### D3R-32 — Safety bypass stop

D3-2 BYPASS_SAFETY does not enter normal projection; D3-3 returns coarse
BYPASS_SAFETY.

### D3R-33 — Safety detail non-disclosure

CRISIS_ROUTE, REVIEW_REQUIRED, and BLOCK details must not leak to
Teacher/Parent Prompt-facing payloads.

### D3R-34 — No notifications

D3-3 does not notify a parent or teacher and does not perform crisis
notification.

### D3R-35 — Explicit prompt allowlist

Prompt-facing projection uses explicit field allowlists, not
serialize-all-then-delete filtering.

### D3R-36 — Typed surface separation

PromptFacingProjection and AuditProjection are separate typed surfaces.

### D3R-37 — No sensitive denial detail

Prompt-facing payload does not contain suppressed claim count, hidden claim
names, or detailed sensitive denial reason.

### D3R-38 — Existence side-channel protection

Non-self projection must protect against sensitive-result-existence side
channels.

### D3R-39 — Audit does not enter Prompt

Audit may retain policy, reason, suppression, and provenance information, but
audit data must never automatically enter Prompt input.

### D3R-40 — Raw and clinical field boundary

Public projection contains no raw theta/SE, diagnosis, severity, clinical
risk, or crisis inference.

### D3R-41 — Structured projection only

D3-3 produces structured projection only; natural-language generation remains
D3-1 responsibility.

### D3R-42 — No RAG or D2 query

D3-3 does not call RAG and does not query the D2 corpus.

### D3R-43 — No external policy runtime

No new OpenFGA, OPA, FHIR server, LangChain, or similar runtime dependency.

### D3R-44 — Transparent bounded implementation

Implementation uses transparent typed Python, versioned JSON policy, schema,
and deterministic tests.

### D3R-45 — Internal contract and Frozen Root

D3-3 contract remains a module-owned internal contract; Frozen Root is
unchanged.

### D3R-46 — Root promotion deferred

Root contract promotion remains deferred to D3-4.

### D3R-47 — Synthetic data boundary

Only synthetic/research engineering data is allowed; real student data
remains forbidden.

### D3R-48 — Engineering PASS boundary

D3-3 engineering PASS does not imply legal compliance certification,
psychology approval, real disclosure authorization, real-pilot readiness, or
production readiness.

## Bounded implementation interpretation

The implementation consumes a role-neutral D3-2
AssessmentInterpretationResult and a trusted audience context. It performs
exact policy selection, hash verification, role/purpose/relation/mode/
authorization checks, source-status checks, explicit allowlisted projection,
and monotonic claim filtering. It emits separate Prompt-facing and audit
surfaces.

The shipped policies are synthetic-only and accept the conservative
MEASUREMENT_ONLY source status with an empty claim allowlist:

| Role | Purpose | Relation | Public behavior |
|---|---|---|---|
| STUDENT_SELF | SELF_UNDERSTANDING | SELF | READY_FOR_PROMPT with safe D3-2 limitations and opaque citations |
| TEACHER_SUPPORT | EDUCATIONAL_SUPPORT | ASSIGNED_SUPPORT | NO_PERSONALIZED_DISCLOSURE with zero personalized claims |
| PARENT_DEMO | SYNTHETIC_PARENT_DEMO | SYNTHETIC_DEMO | Synthetic/demo entry with coarse empty public disclosure |

SYSTEM_ADMIN and UNKNOWN are denied. Parent REAL_USER is blocked and age 17
does not grant access. A trusted BYPASS_SAFETY source stops normal
projection; Safety action remains audit-only. D3-3 does not perform
authentication, relationship lookup, consent/legal workflow, CAT
measurement, RAG, LLM generation, notifications, or D3-4 integration.

The citation shape is intentionally opaque: source_chunk_id plus optional
locator. Binding it to a trusted RAG/document snapshot, content hash, rights
state, population scope, and role/risk scope is deferred to D3-4.
