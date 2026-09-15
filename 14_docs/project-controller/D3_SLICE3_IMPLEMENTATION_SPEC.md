# D3 Slice 3 · Role Projection and Minimum Disclosure Implementation Spec

Status: APPROVED_FOR_BOUNDED_IMPLEMENTATION

This specification is the implementation baseline for D3-3 under
D3_ROLE_PROJECTION_TECHNICAL_DECISION_V1.md. It is a module-owned internal
boundary. It does not promote a Root Contract, change OpenAPI, approve a
psychological interpretation, authorize real disclosure, or start D3-4.

The current evidence boundary remains explicit: D3-1 and D3-2 are accepted
engineering baselines supplied by the Controller mission; D1 is
RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK; the D2 new intake is
rights-unknown and review-pending; parent production is paused; synthetic/demo
use is the only current projection mode; and real student data and a real
pilot are blocked.

## 1. Scope and ownership

D3-3 belongs to 07_prompt-engine. The preferred implementation is a new
standalone role-projection submodule or subpackage that consumes a typed,
role-neutral D3-2 result and emits typed role-scoped projections. Accepted
D3-1 behavior remains unchanged. A minimal package import/export change is
permitted only if the existing package layout requires it and the D3-1
regression remains green.

D3-3 owns:

- trusted audience context types and construction boundary;
- role, purpose, relation, and disclosure authorization validation;
- the versioned role-projection policy registry and canonical policy hash;
- exact policy selection;
- monotonic claim filtering and explicit field allowlists;
- separate PromptFacingProjection and AuditProjection output types;
- status/reason-code mapping and existence-side-channel protection; and
- deterministic tests and module documentation for this boundary.

D3-3 does not own:

- CAT measurement, theta, SE, stopping evidence, score computation, or
  psychological interpretation;
- Safety calculation, Safety mutation, crisis routing, notifications, or
  relationship lookup;
- natural-language generation;
- Backend authentication, persistence, API/OpenAPI, Root Contract promotion,
  or D3-4 orchestration;
- real consent/legal workflows, age-based parent authorization, psychology
  claim approval, or real data; or
- the unreviewed D2 14-source/58-fragment intake.

## 2. Data flow and trust boundaries

The bounded flow is:

    role-neutral D3-2 InterpretationResult
            + trusted TrustedAudienceContext
            + caller request identity
            + exact RoleProjectionPolicyPack reference
            -> deterministic source/status/policy/context checks
            -> monotonic allowlisted projection
            -> PromptFacingProjection + AuditProjection

The D3-2 result is the source of approved typed claims. D3-3 may retain,
remove, redact, or suppress those claims. It must never invent, upgrade,
reinterpret, infer, or merge a stronger psychological claim. D3-3 itself
produces no natural language; D3-1 remains the language-generation boundary,
and D3-4 is the future integration boundary.

The input result, request mapping, and policy registry data are untrusted until
validated. The audience context is trusted only when created through the
controlled internal seam. This is a process-local capability-like boundary,
not cryptographic isolation against code that can import private names,
rewrite memory, or bypass the API in the same process.

## 3. TrustedAudienceContext

The internal typed context must carry the authoritative values below:

| Field | Required meaning |
|---|---|
| audience_role | STUDENT_SELF, TEACHER_SUPPORT, or PARENT_DEMO; SYSTEM_ADMIN and UNKNOWN are not psychological-content audiences |
| purpose_of_use | SELF_UNDERSTANDING, EDUCATIONAL_SUPPORT, or SYNTHETIC_PARENT_DEMO |
| subject_relation | A typed relation such as SELF, ASSIGNED_SUPPORT, or SYNTHETIC_DEMO |
| execution_mode | A trusted mode, with parent demo restricted to synthetic mode |
| disclosure_authorization | Typed state sufficient for projection; not a legal-consent workflow |
| context_version | Version of the trusted context shape/semantics |
| capability | Opaque internal trust marker that cannot be supplied by a plain caller mapping |

Public projection APIs must accept this typed context, not an arbitrary dict or
JSON object. A plain mapping that attempts to assert a privileged role,
purpose, relation, execution mode, or authorization must fail closed with a
stable abstention. A private/test builder may construct the context only at
the controlled integration seam and must validate every field.

The context must not be derived from caller-provided role strings alone. Real
identity, relationship, authentication, and consent lookup are deferred to
D3-4 Backend. D3-3 must not claim to have performed them.

## 4. Role, purpose, and relation semantics

Role and purpose are a matched pair. Relation is a separate trusted
requirement. The implementation must reject mismatches before claim
projection.

| Audience role | Purpose | Required relation | Current mode | Current disclosure |
|---|---|---|---|---|
| STUDENT_SELF | SELF_UNDERSTANDING | SELF | Synthetic/demo policy scope; future explicitly approved scope only | Own approved claims and approved public limitations |
| TEACHER_SUPPORT | EDUCATIONAL_SUPPORT | Trusted support relation such as ASSIGNED_SUPPORT | Explicitly allowed mode only | Default deny for individualized psychological claims |
| PARENT_DEMO | SYNTHETIC_PARENT_DEMO | SYNTHETIC_DEMO | SYNTHETIC_DEMO only | Synthetic/demo projection only |
| SYSTEM_ADMIN | None for psychological content | None | Any | Deny / NO_PERSONALIZED_DISCLOSURE |
| UNKNOWN | None | None | Any | Deny |

The following combinations are invalid:

- STUDENT_SELF without SELF;
- TEACHER_SUPPORT with SELF_UNDERSTANDING;
- PARENT_DEMO outside synthetic mode or without SYNTHETIC_DEMO;
- any role or purpose self-asserted by an untrusted caller;
- SYSTEM_ADMIN or UNKNOWN as a psychology-content audience; and
- any role/purpose/relation not explicitly represented by the selected
  versioned policy.

The implementation may use semantically equivalent typed enum names, but it
must preserve these distinctions and fail closed on unknown values.

## 5. Disclosure authorization

D3-3 models only the authorization state needed to decide whether a projection
is allowed. It does not implement legal consent, guardian consent, age
determination, identity proof, or a real relationship workflow.

The current boundary is:

- real parent disclosure: blocked;
- real teacher psychological disclosure: blocked unless a future policy
  explicitly authorizes an approved educational-support claim;
- synthetic parent demo: may proceed only when the trusted context and
  policy both require synthetic mode and relation; and
- age, including age 17, never grants parent access by itself.

The authorization state and its detailed failure reason are audit inputs. A
PromptFacingProjection must expose only the coarse public result permitted by
the status table below. Detailed states such as CONSENT_MISSING remain
audit-only when revealing them could disclose sensitive state.

## 6. RoleProjectionPolicyPack

The policy registry is a versioned, read-only JSON asset owned by
07_prompt-engine. Each policy record contains at least:

    policy_id
    policy_version
    policy_hash
    audience_role
    purpose_of_use
    allowed_modes[]
    allowed_source_statuses[]
    allowed_claim_codes[]
    allowed_limitation_codes[]
    public_field_allowlist[]
    required_relation
    disclosure_requirement
    synthetic_only
    review metadata
    effective_version

Review metadata must remain metadata. It cannot turn D1
RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK into an approval, and it
cannot turn D2 rights-unknown/review-pending material into an approved source.
The current policy set is conservative and contains exactly the three
audience/purpose pairs:

1. STUDENT_SELF / SELF_UNDERSTANDING;
2. TEACHER_SUPPORT / EDUCATIONAL_SUPPORT; and
3. PARENT_DEMO / SYNTHETIC_PARENT_DEMO.

The current Teacher policy has no individualized psychological claim codes.
SUPPORT_TOPIC is not fabricated or implicitly authorized. The current Parent
policy is synthetic/demo only. No Admin psychology policy exists.

## 7. Canonical policy hashing and exact selection

Policy identity is selected exactly. The selection tuple includes the
requested policy ID, policy version, policy hash, audience role, purpose,
required relation, source identity/status, and trusted execution mode as
applicable to the policy fields. The selected policy must bind the same
audience/purpose/relation/mode and allowed source status as the trusted
context and D3-2 result.

Canonical hash computation follows the existing project convention:

1. parse the JSON object;
2. reject duplicate keys and malformed/unknown policy shape;
3. remove the top-level policy_hash;
4. serialize UTF-8 with sorted keys, ensure_ascii=false, and compact
   separators (',' , ':');
5. compute SHA-256; and
6. compare the stored sha256: value exactly.

The registry must recompute and verify the hash when loading. The projection
engine must defensively recompute it for the selected typed policy before use,
so direct same-process dataclass mutation or a reused/fake hash fails closed.
There is no default, latest, first-match, wildcard, or generic policy
fallback. Missing, mismatched, or tampered identity returns
ABSTAIN_POLICY_MISSING or ABSTAIN_POLICY_MISMATCH as appropriate.

## 8. Source status and Safety boundary

D3-3 consumes the canonical D3-2 status without reinterpreting it. Only
explicitly allowed normal source statuses can reach normal role projection.
BYPASS_SAFETY and relevant ABSTAIN_* source statuses stop normal projection.

If the source indicates a Safety bypass, D3-3:

- returns BYPASS_SAFETY or the specified source-status abstention;
- does not calculate, modify, or regenerate a Safety decision;
- does not route a crisis;
- does not notify a parent or teacher;
- may preserve the trusted source status in AuditProjection; and
- does not expose the internal Safety action or sensitive reason to a
  Teacher/Parent PromptFacingProjection.

Safety action values are not psychological claim codes. D3-3 must not infer
crisis, risk, severity, or treatment from them.

## 9. Projection monotonicity

The content-claim invariant is:

    PromptFacingProjection.content_claim_codes
        ⊆
    D3-2.approved_claim_codes

Every output content claim must exist in the source approved claim set and
must also be permitted by the exact role policy. Projection metadata is not a
psychological/content claim and is excluded from this subset comparison.

Allowed operations are retain, remove, redact, and suppress. No operation may:

- create a claim code absent from D3-2;
- upgrade a claim's scope or strength;
- infer a claim from theta, SE, score, band, precision, or status;
- merge several claims into a stronger claim; or
- convert a limitation or source status into a psychological claim.

The property must be tested with synthetic and randomized claim sets where
useful. An injected stronger claim must fail closed.

## 10. PromptFacingProjection

PromptFacingProjection is a dedicated typed output model constructed from an
explicit allowlist. It is the only projection shape eligible for a later
Prompt Engine handoff. It must not be produced by serializing the full source
object and deleting blocked fields.

The model contains only approved public fields, such as:

- a coarse canonical status;
- coarse public reason code(s) allowed by the policy;
- role-permitted approved claim records;
- role-permitted approved limitation records;
- minimal anonymous subject/request identity needed for rendering; and
- schema/version metadata needed to parse this projection.

It must not contain:

- policy ID, policy version, policy hash, effective version, review decision
  ID, evidence references, review status/detail, rights status, or internal
  trust metadata;
- trusted relation, disclosure decision, suppression reason, hidden claim
  name, hidden construct name, hidden field count, or suppressed count;
- internal Safety action or sensitive Safety reason;
- theta, SE, score, score aliases, intervals, bands, latent values, or
  precision-as-risk;
- diagnosis, disorder, severity, risk, suicide/self-harm, crisis,
  treatment, or Level 1–5 semantics; or
- natural-language prose generated by D3-3.

The public model must use coarse denial outputs so that equivalent sensitive
denials have the same public shape.

## 11. AuditProjection

AuditProjection is a distinct typed model, not the PromptFacingProjection
serialized with more fields. It may contain the internal information needed
for traceability and review:

- selected policy identity and verified hash;
- source status and source identity;
- trusted role, purpose, relation, and authorization state;
- selected allowed claim codes;
- suppressed claim codes;
- detailed suppression/denial reason;
- decision provenance, context version, request/trace identity; and
- whether the public projection was withheld or redacted.

AuditProjection is not accepted by the Prompt Engine public rendering API.
The API must reject an AuditProjection passed where a Prompt-facing
Projection is required. Audit data remains subject to the project's privacy
and logging boundaries and must not copy raw answers, identity fields, full
prompts, or sensitive model context.

## 12. Public statuses and reason codes

The D3-3 canonical statuses are:

- READY_FOR_PROMPT;
- NO_PERSONALIZED_DISCLOSURE;
- ABSTAIN_POLICY_MISSING;
- ABSTAIN_POLICY_MISMATCH;
- ABSTAIN_ROLE_NOT_ALLOWED;
- ABSTAIN_PURPOSE_NOT_ALLOWED;
- ABSTAIN_RELATIONSHIP_MISMATCH;
- ABSTAIN_DISCLOSURE_NOT_AUTHORIZED;
- ABSTAIN_MODE_NOT_ALLOWED;
- ABSTAIN_SOURCE_STATUS; and
- BYPASS_SAFETY.

An implementation extension requires written justification and cannot replace
these canonical values.

Prompt-facing reason codes are deliberately coarse. Detailed internal codes
such as CONSENT_MISSING, CLAIM_NOT_VISIBLE, RELATION_FAILED, and
SENSITIVE_SOURCE_PRESENT belong only in AuditProjection when their exposure
could leak sensitive state. A Teacher/Parent denial caused by no source claim
and one caused by a suppressed source claim must both return the same coarse
NO_PERSONALIZED_DISCLOSURE public shape.

## 13. Current role matrix

| Role | Valid purpose | Required relation | Valid current mode | Current public result |
|---|---|---|---|---|
| STUDENT_SELF | SELF_UNDERSTANDING | SELF | Explicitly allowed synthetic/demo scope | Own D3-2 approved claims and public limitations only |
| TEACHER_SUPPORT | EDUCATIONAL_SUPPORT | Trusted assigned support relation | Explicitly allowed scope; current individualized psychological disclosure denied | NO_PERSONALIZED_DISCLOSURE with zero personalized claims |
| PARENT_DEMO | SYNTHETIC_PARENT_DEMO | SYNTHETIC_DEMO | SYNTHETIC_DEMO only | Synthetic/demo path only |
| SYSTEM_ADMIN | None for psychology content | None | Any | Deny / NO_PERSONALIZED_DISCLOSURE |
| UNKNOWN | None | None | Any | Deny |

This matrix does not authorize real parent disclosure, real teacher
psychological disclosure, counselor/clinician roles, automatic notification,
or age-based access. Future expansion requires a new Controller decision and
new research, review, and validation.

## 14. Required deterministic tests

The implementation must cover:

1. raw caller cannot forge STUDENT_SELF;
2. raw caller cannot forge TEACHER_SUPPORT;
3. raw caller cannot forge SELF relation;
4. raw caller cannot forge purpose;
5. teacher requesting student claims yields NO_PERSONALIZED_DISCLOSURE;
6. hidden claim names are absent;
7. suppressed counts are absent;
8. parent REAL_USER fails closed;
9. parent synthetic demo passes only with trusted synthetic context;
10. age 17 does not grant parent access;
11. SYSTEM_ADMIN cannot access psychology content;
12. unknown roles deny;
13. output claim codes are a subset of input approved claim codes;
14. injected stronger/new claims are rejected;
15. audit fields are absent from PromptFacingProjection;
16. AuditProjection is rejected by the Prompt-facing API;
17. D3-2 BYPASS_SAFETY stops normal projection;
18. Safety action is absent from Teacher/Parent public payloads;
19. no wildcard/default/latest policy path exists;
20. policy hash tampering fails closed;
21. no raw theta/SE/score/band/interval/latent reconstruction occurs;
22. equivalent non-self denial cases have an equivalent coarse public shape;
23. current Teacher personalized claim output is zero; and
24. current Parent production and real data paths remain blocked.

Tests must be deterministic, use synthetic fixtures only, and include the
monotonicity property with synthetic/randomized claim sets where useful.

## 15. Verification and acceptance gates

The bounded implementation can be recommended for Controller review only after
fresh evidence covers:

- D3R total 48, materialization 48, semantic deviations 0, and no mission or
  scope deviation;
- deterministic execution, zero LLM calls, zero RAG calls, and no new claim
  generation;
- trusted audience context and fail-closed caller role/purpose/relation/
  authorization boundaries;
- exact policy match, verified policy hash, and no wildcard/default/latest
  fallback;
- monotonicity and output-claim subset;
- Student relation enforcement and allowlisted output;
- Teacher default deny, zero personalized claims, and no hidden-state leakage;
- Parent real-user blocking, synthetic-demo behavior, and no age-only access;
- Admin/unknown denial;
- Prompt/audit model separation;
- D3-2 Safety bypass behavior and no Safety-reason leakage;
- no theta/SE/raw-score/diagnosis/severity/risk/natural-language generation;
- D3-3 tests, Ruff, Pyright, compile/import;
- D3-2 regression (historically 41/41 or current equivalent);
- D3-1 regression (historically 48/48 or current equivalent);
- CAT regression where required by the existing project gate;
- Root Contract, OpenAPI, and Frozen Root checks;
- no forbidden-module changes;
- no real student data; and
- evidence and local-commit boundaries required by the mission.

These gates are evidence requirements, not claims that the pre-implementation
documents have passed them.

## 16. Stop conditions

Stop and return CONTROLLER_DECISION_REQUIRED if implementation would require:

- a D3-2 contract change;
- a D3-1 behavior change;
- Backend authentication changes;
- new real-consent semantics;
- a new parent legal decision;
- a new teacher disclosure decision;
- psychology claim approval;
- a new SUPPORT_TOPIC;
- a Safety architecture change;
- a Root Contract or OpenAPI change;
- real data; or
- a new runtime policy engine.

The implementation must not add OpenFGA, OPA, FHIR server, Keycloak,
LangChain, DSPy, or an external policy engine. Typed Python, versioned JSON,
JSON Schema, and deterministic tests are the bounded design.

## 17. Evidence and acceptance boundary

The pre-implementation fidelity report and closure evidence must distinguish:

- Controller mission decisions;
- historical D3-1/D3-2 evidence;
- fresh tests;
- Worker reports and routing metadata;
- Execution Lead review; and
- Controller acceptance.

Before implementation:

- fidelity state is pending/NOT_YET_VERIFIED;
- closure evidence state is PRE_IMPLEMENTATION/NOT_YET_VERIFIED;
- final test counts, fidelity, and acceptance fields are
  PENDING_LEAD_VERIFICATION; and
- no READY_FOR_CONTROLLER_REVIEW claim is made.

After implementation, only fresh Lead verification can populate final fields.
Only Project Controller may accept D3-3. D3-4 remains stopped pending that
review.
