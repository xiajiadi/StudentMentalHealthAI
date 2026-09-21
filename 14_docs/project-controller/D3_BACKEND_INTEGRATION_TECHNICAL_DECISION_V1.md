# D3-4 Trusted Backend Orchestration & Evidence Binding Technical Decision V1

Status: FROZEN FOR BOUNDED IMPLEMENTATION
Date: 2026-09-16
Owner: Project Controller / Execution Lead
Baseline: cb28fe38b2e1df1b06c96610419691dd2d7924db
Scope: 09_backend orchestration only

This document materializes the Controller's frozen D3-4 technical decisions.
D3INT-01 through D3INT-60 below are the decision identifiers for this
technical decision. They are not execution-mission section numbers. The
implementation is engineering-only and synthetic/demo bounded. It does not
grant psychology approval, legal or consent approval, real-student disclosure
authorization, real-pilot authorization, or production enablement.

## Frozen technical decisions

### D3INT-01 — Backend ownership

09_backend is the application orchestration boundary. CAT, D3-2, RAG,
D3-3, D3-1, Safety, Runtime, and Database retain their module ownership.

### D3INT-02 — Service topology

The accepted topology remains Backend -> CAT HTTP -> RAG HTTP -> Safety HTTP ->
LLM Runtime HTTP. D3 deterministic modules are used as local Backend-side
library calls only where their accepted packages are available.

### D3INT-03 — No new services

D3-4 creates no new FastAPI service, policy service, identity service, mesh,
token service, or model service.

### D3INT-04 — Accepted module immutability

D3-1, D3-2, D3-3, CAT, RAG, Safety, Runtime, Database, and frozen Root source
remain unchanged. All product changes are confined to 09_backend.

### D3INT-05 — Frozen Root boundary

The Root Contract, frozen JSON schemas, and frozen OpenAPI remain read-only.
A public contract change requires a separate Controller decision.

### D3INT-06 — Synthetic engineering boundary

Only synthetic, approved public, or de-identified fixtures may be used in this
slice. No real student data, real relationship record, or clinical record is
allowed.

### D3INT-07 — Real pilot boundary

Real pilot execution remains BLOCKED until psychology approval, rights and
licensing, ethics/consent/privacy, and calibration/validation gates are
separately satisfied.

### D3INT-08 — D2 intake exclusion

The D2 new 14-source/58-fragment intake is not eligible evidence for this
orchestration and is not used by the generation path.

### D3INT-09 — Existing authentication boundary

The existing opaque server-side session is the only principal source for the
bounded flow. D3-4 does not redesign authentication or introduce a new
authorization infrastructure.

### D3INT-10 — Typed trusted context

Backend creates a process-local typed TrustedRequestContext containing
transaction_id, principal_id, product_role, subject_id, purpose, relationship,
execution_mode, and disclosure_state. A plain caller mapping cannot create the
trusted object.

### D3INT-11 — Principal derivation

principal_id is derived from the verified opaque server session and the server
account record. Caller identity fields are never authoritative.

### D3INT-12 — Role derivation

product_role is derived from server account/authz state. Request target_role,
role, or audience strings cannot elevate or change the trusted role.

### D3INT-13 — Subject derivation

subject_id is resolved by Backend from the persisted assessment and authorized
object scope. A caller supplied subject_id is a consistency assertion only.

### D3INT-14 — Purpose derivation

purpose is derived from the trusted use case and role mapping. Caller purpose,
purpose_of_use, or similar fields cannot authorize a new purpose.

### D3INT-15 — Relationship derivation

relationship is derived from server-controlled ownership, assignment, or a
controlled synthetic relationship. Caller relationship strings are untrusted.

### D3INT-16 — Execution mode derivation

execution_mode comes from server configuration and workflow state. Caller
synthetic, real_user, or mode fields cannot switch the flow to a privileged mode.

### D3INT-17 — Disclosure derivation

disclosure_state comes from server policy and the trusted role/relationship
combination. disclosure_authorized and consent-like request fields cannot grant
disclosure.

### D3INT-18 — Caller privilege fields

role, purpose, relationship, student_id-as-authority, synthetic, real_user,
review_status, rights_status, safety_action, disclosure_authorized,
population_scope, risk_scope, and citation approval are never trusted from the
caller.

### D3INT-19 — Forgery response

The implementation must ignore, validate, or reject caller privilege fields
according to the existing public contract; server state always wins and
conflicting authority assertions fail closed.

### D3INT-20 — Assessment binding

Before D3-2, Backend binds assessment_id to the persisted assessment record,
resolved subject, instrument identity/version, completed status, and trusted
request origin.

### D3INT-21 — Assessment ownership / IDOR

Student SELF requests require principal ownership of the subject and assessment.
A foreign assessment ID or cross-subject binding fails closed.

### D3INT-22 — Instrument and origin integrity

D3-2 receives the accepted completed assessment and its original instrument
identity/version. Backend does not rewrite, recalculate, or silently normalize
CAT evidence.

### D3INT-23 — Student mapping

Student self maps to STUDENT_SELF, SELF_UNDERSTANDING, SELF, and the bounded
synthetic self disclosure state.

### D3INT-24 — Teacher mapping

Teacher support maps to TEACHER_SUPPORT, EDUCATIONAL_SUPPORT, and only a trusted
assigned-support relationship. Current teacher output contains no personalized
psychological claims.

### D3INT-25 — Parent demo mapping

Parent demo maps to PARENT_DEMO, SYNTHETIC_PARENT_DEMO, SYNTHETIC_DEMO, and
coarse synthetic behavior only.

### D3INT-26 — Parent real-user and age boundary

Parent REAL_USER disclosure is blocked. Age, including age 17, never grants
parent disclosure. Restoring a real parent path requires a separate decision.

### D3INT-27 — Admin boundary

SYSTEM_ADMIN has no implicit psychological-content access or psychology
superuser path. Admin requests are denied or reduced to a coarse safe envelope.

### D3INT-28 — Role monotonicity

Backend may reduce or suppress information at each boundary but may not promote
a D3-2 claim, a D3-3 projection, or a citation into a stronger disclosure.

### D3INT-29 — Explicit stage machine

The canonical logical stages are REQUEST_AUTHENTICATED,
REQUEST_AUTHORIZED, INPUT_SAFETY_EVALUATED, ASSESSMENT_BOUND,
INTERPRETATION_READY, RETRIEVAL_BOUND, ROLE_PROJECTED, PROMPT_ASSEMBLED,
GENERATION_BUFFERED, OUTPUT_SAFETY_EVALUATED, and PERSISTED.

### D3INT-30 — Stage preconditions

Every stage records and checks its predecessor and trusted context. Out-of-order
invocation, duplicate completion, or missing predecessor fails closed.

### D3INT-31 — Input Safety first

Input Safety is authoritative and runs before normal assessment interpretation,
RAG retrieval, role projection, prompt rendering, or LLM generation.

### D3INT-32 — Safety bypass

CRISIS_ROUTE, REVIEW_REQUIRED, and BLOCK stop normal D3-2/D3-3/D3-1/RAG/LLM
work. The Safety decision is preserved; D3-4 never overrides or infers it.

### D3INT-33 — D3-2 composition

D3-2 receives the trusted accepted assessment evidence and trusted
execution/Safety context and returns the canonical role-neutral interpretation
result.

### D3INT-34 — D3-2 non-recalculation

Backend never recalculates theta or SE, invents construct meaning, derives
severity/risk, creates cutoffs, or turns measurement values into psychology
claims.

### D3INT-35 — Accepted RAG boundary

Retrieval uses only the accepted RAG client/service and its current
knowledge.v1 contract. BGE-M3, BM25S, RRF, reranker, corpus, and retrieval
algorithm are not changed.

### D3INT-36 — Trusted retrieval filters

Population, role, risk, review, rights, and other retrieval filters are formed
from TrustedRequestContext and accepted server configuration. Caller privilege
filters are ignored or rejected.

### D3INT-37 — Actual provenance only

Backend documents and binds only provenance fields actually present in the RAG
response: source/document identity and citation, chunk identity/content/hash,
locator/location, review/rights state, population/role/risk scope, and any
trace/index/corpus/retrieval/run/rank/score fields actually exposed. Missing
fields are not invented.

### D3INT-38 — RetrievalEvidenceBundle

Backend creates an immutable RetrievalEvidenceBundle representing the exact
chunks selected for this request, including the available trusted identity,
content, locator, eligibility, scope, and retrieval trace fields.

### D3INT-39 — Snapshot semantics

A trusted snapshot is the exact immutable evidence set bound to this request.
Backend may include an accepted index, corpus build, or snapshot identity when
RAG exposes one, but never fabricates a global snapshot identifier.

### D3INT-40 — Deterministic bundle hash

bundle_hash is SHA-256 over canonical UTF-8 JSON for the bundle metadata with
sorted keys and compact separators, excluding bundle_hash itself. Any metadata
or content tamper invalidates the bundle.

### D3INT-41 — One bundle per transaction

One synchronous generation transaction uses one frozen bundle through RAG
verification, D3-3, D3-1, generation audit, citation validation, and citation
display resolution. No post-generation retrieval is allowed for citations.

### D3INT-42 — D3-3 composition

D3-3 receives the trusted D3-2 result, Backend-built trusted audience context,
and opaque citation references derived only from the verified bundle. Caller
citation identifiers never become trusted by shape alone.

### D3INT-43 — D3-1 composition

D3-1 receives the typed PromptFacingProjection, TrustedPromptContext, and
TrustedChunkContext values built from trusted orchestration state and the same
bundle. Raw HTTP mappings are not passed into trusted seams.

### D3INT-44 — Prompt minimization

The rendered prompt contains only the minimum generation data. It excludes
secrets, raw session/auth tokens, internal Safety details, rights internals,
AuditEnvelope, raw theta/SE, and unnecessary identity data.

### D3INT-45 — Citation membership

Every citation emitted by the candidate must identify a chunk/source belonging
to the prompt-bound bundle with matching trusted identity and content hash.
Unknown, tampered, or cross-request citations fail validation.

### D3INT-46 — Same-bundle resolution

Visible citation metadata is resolved from the already-bound bundle. The
generation path never performs generation -> fresh RAG -> citation lookup.

### D3INT-47 — Eligibility fail-closed

Pending, unknown, rejected, unverified, rights-ineligible, review-ineligible,
population-incompatible, role-incompatible, or risk-incompatible evidence is
not promoted to generation; the flow abstains or blocks.

### D3INT-48 — Provenance separation

Psychometric provenance and RAG knowledge provenance remain separate domains.
They may be linked by transaction_id in audit but are not one approval system.

### D3INT-49 — Runtime input boundary

The formal product Runtime call receives only the accepted rendered D3-1 prompt
and its approved generation metadata. There is no raw client prompt -> Runtime
route.

### D3INT-50 — Buffered output

The candidate is fully buffered. Output Safety runs before normal response
exposure and before normal persistence. Direct streaming or partial publication
cannot bypass the gate.

### D3INT-51 — Persistence and idempotency

Persistence reuses the accepted repository/schema and preserves existing
idempotency semantics. D3-4 does not create a database migration or treat a
failed/blocked candidate as an approved result.

### D3INT-52 — Audit envelope

Internal audit evidence carries transaction/stage identities, safe
pseudonymous principal/subject references, D3-2 policy identity, D3-3 policy
identity, D3-1 template identity/version/hash, bundle_hash, opaque evidence
IDs, Input Safety identity, Runtime identity, and Output Safety identity where
available.

### D3INT-53 — Audit/prompt separation

AuditEnvelope is never passed to Prompt Engine or exposed in a public DTO.
Secrets, credentials, raw sessions, unnecessary theta/SE, and hidden
Teacher/Parent data are never logged or returned.

### D3INT-54 — No weak fallback

Missing D3 policy, missing trusted context, unavailable RAG/Safety/Runtime,
invalid structured output, ineligible evidence, and integrity mismatches fail
closed. No generic JSON repair, policy weakening, cloud fallback, or blind
retry is introduced.

### D3INT-55 — Dependency failure semantics

Safety-down, RAG-down, Runtime-down, invalid upstream shape, and persistence
failure follow the accepted error/status envelope and leave no normal approved
content. Crisis remains zero normal RAG/prompt/LLM calls.

### D3INT-56 — Review and disclosure paths

Review actions use the authenticated reviewer actor and bound case/object
scope. Teacher, Parent, and Admin paths cannot use review metadata or caller
fields to escalate disclosure.

### D3INT-57 — Trust and bypass test obligations

Tests cover caller forgery, assessment IDOR, fake Safety action, direct retrieval,
raw prompt, preview/regenerate/retry or legacy entrypoints when present,
streaming bypass, and every canonical generation route.

### D3INT-58 — Evidence-chain test obligations

Tests cover D3-2/D3-3/D3-1 composition, deterministic bundle hash, metadata and
chunk tamper, unknown/cross-retrieval citation, eligibility, D2 exclusion,
TOCTOU, same-bundle display, teacher/parent/admin boundaries, and idempotent
replay.

### D3INT-59 — Verification obligations

Fresh Backend tests, Ruff, Pyright, compile/import, accepted D3-1/D3-2/D3-3,
CAT, RAG, Safety, Root, OpenAPI, frozen-root, and bounded real HTTP evidence
must be recorded. GPU performance qualification is not reopened.

### D3INT-60 — Acceptance and publication boundary

A local candidate commit may be created only after all hard gates pass and may
contain only D3-4 Backend source/tests plus D3-4 decision/spec/evaluation/
evidence. Merge, push, and an accepted tag remain Controller-only and are not
performed by this mission.

## Decision boundary

This decision authorizes a bounded Backend implementation only. If the actual
D3 seams cannot be imported without changing accepted modules, if minimum
trusted RAG provenance is unavailable, if Root/OpenAPI/DB schema/auth
infrastructure must change, or if real consent/legal/Teacher/Parent disclosure
is required, the result is CONTROLLER_DECISION_REQUIRED. No such change may be
made silently.
