# D3-3 Role Projection and Minimum Disclosure Technical Decision V1

Status: FROZEN FOR BOUNDED IMPLEMENTATION

Authority: Project Controller D3-3 mission package. This document materializes
the 48 numbered D3-3 requirements in that package. It does not grant
Controller acceptance, psychology approval, real-pilot authorization, rights
clearance, clinical validity, or production readiness.

Scope: D3-3 Role Projection and Minimum Disclosure in 07_prompt-engine.
D3-4 Backend Integration, Safety architecture changes, real consent workflows,
real student data, and production delivery remain out of scope.

Source of truth: repository and accepted evidence. D1 remains
RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK. D2's new intake remains
rights-unknown and review-pending, and is not original-candidate signoff.
Parent production delivery remains paused; synthetic/demo capability may be
retained. Real student data and a real pilot remain forbidden/blocked.

The current D3-2 output is the role-neutral source boundary. D3-3 may retain,
remove, redact, or suppress already approved claims for an authorized
audience. It must not create new psychology semantics. Current D3-2
MEASUREMENT_ONLY is a valid source result. No D3-4 behavior is authorized by
this decision.

## Frozen D3R-01 through D3R-48

The requirements below are frozen in the mission order. Their numbering and
semantics must not be changed during bounded implementation.

### D3R-01 — Read governance

Before implementation, read the project execution governance at
D:\Projects\StudentMentalHealthAI\AGENTS.md, then PROJECT.md, ARCHITECTURE.md,
CONTRACTS.md, MODULES.md, the current controller state files
PROJECT_STATE.md, CURRENT_STATE_INVENTORY.md, DECISION_REGISTER.md,
HUMAN_REVIEW_RECONCILIATION.md, and AGENT_HANDOFF_PROTOCOL.md. Read the
accepted D3-1 and D3-2 decisions and evidence. Repository and accepted
evidence are the source of truth.

### D3R-02 — Clean baseline

The bounded implementation starts from
d9e1cba8b02c26b5661bd139339daed8629f3d1e on branch
exp/d3-role-projection-v1 in worktree
D:\Projects\StudentMentalHealthAI-d3-role-projection. The worktree must be
checked clean before implementation. Unrelated integration overlays must not
be copied.

### D3R-03 — Materialize the frozen decision

Create this technical-decision document under
14_docs/project-controller/ with status FROZEN FOR BOUNDED IMPLEMENTATION.
Materialize all 48 frozen requirements in their original order. Do not
renumber or weaken them.

### D3R-04 — Implementation specification

Create D3_SLICE3_IMPLEMENTATION_SPEC.md under
14_docs/project-controller/ with status
APPROVED_FOR_BOUNDED_IMPLEMENTATION. It must define module ownership,
trusted audience context, role projection policy, policy hashing,
role/purpose/relation semantics, projection monotonicity, field allowlists,
the prompt-facing/audit split, statuses and reason codes, existence-side-
channel protection, the current role matrix, tests, and acceptance gates.
It must introduce no psychology semantics.

### D3R-05 — Module ownership

D3-3 belongs to 07_prompt-engine. Prefer a new standalone role-projection
submodule or subpackage. Do not alter accepted D3-1 behavior unless
unavoidable. D3-1 integration is deferred to D3-4. If a small import/export
change is necessary because of the existing package structure, keep it
minimal and prove that the D3-1 regression remains green.

### D3R-06 — Execution Lead must not write product code

The Execution Lead is limited to inspection, dispatch, review, verification,
and evidence collection. Workers own implementation. If a Worker fails or
times out, dispatch another Luna/Max Worker. Do not fall back to
Lead-authored product source.

### D3R-07 — Worker routing

Every Worker must use model gpt-5.6-luna, reasoning_effort max, and
fork_turns none. Routing metadata must be recorded. If routing cannot be
independently verified, that output must not be used as final acceptance
authority.

### D3R-08 — First parallel read-only batch

Before implementation, reconcile three read-only investigations:

1. Contract Mapper: read D3-1, D3-2, 07_prompt-engine, and
   03_assessment-adapter; determine the actual D3-2 result shape, D3-1
   trusted-context/input needs, safe integration boundary, package layout,
   and compatibility risks.
2. Privacy / Role Boundary Mapper: read the frozen D3R decisions,
   HUMAN_REVIEW_RECONCILIATION, current population/parent decisions, and the
   current D3-2 policy state; return current Student/Teacher/Parent
   permissible disclosure, fields that remain internal, future-only
   decisions, and no invented psychology/legal approval.
3. Abuse Matrix Designer: design adversarial tests for caller-forged role,
   purpose, relation, disclosure authorization, teacher requests for student
   claims, parent requests for real-user claims, admin full-access attempts,
   hidden-result existence leakage, suppressed-count leakage, audit metadata
   leakage, claim expansion, new-claim injection, source-status bypass,
   Safety bypass leakage, wildcard/default policy, and policy-hash tamper.

The Execution Lead reconciles these read-only findings before implementation.

### D3R-09 — Trusted audience context

Implement a typed internal TrustedAudienceContext containing authoritative
audience_role, purpose_of_use, subject_relation, execution_mode,
disclosure_authorization, context_version, and an opaque trust capability.
Plain dict or JSON caller input must not create a privileged context. Do not
claim hostile same-process cryptographic isolation.

### D3R-10 — Current audience roles

The canonical current roles are STUDENT_SELF, TEACHER_SUPPORT, and
PARENT_DEMO. SYSTEM_ADMIN and UNKNOWN must be explicitly rejected as
psychological-content audiences. Do not introduce a counselor or clinician
product role in this mission.

### D3R-11 — Purpose of use

The canonical purposes are SELF_UNDERSTANDING, EDUCATIONAL_SUPPORT, and
SYNTHETIC_PARENT_DEMO. Role and purpose must match:

- STUDENT_SELF with SELF_UNDERSTANDING is potentially valid.
- TEACHER_SUPPORT with SELF_UNDERSTANDING is invalid.
- PARENT_DEMO with SYNTHETIC_PARENT_DEMO is potentially valid only in
  synthetic mode.

### D3R-12 — Subject relation

Use typed relation values such as SELF, ASSIGNED_SUPPORT, and
SYNTHETIC_DEMO, or semantically equivalent values. STUDENT_SELF requires
SELF. A teacher requires a trusted support relation. Parent demo requires a
synthetic relation. A role must not self-assert its relation. Real
relationship lookup belongs to D3-4 Backend.

### D3R-13 — Disclosure authorization

D3-3 must not implement a real legal-consent workflow. It may model a typed
authorization state sufficient for projection. In V0.9, real parent
disclosure is BLOCKED. Real teacher psychological disclosure is BLOCKED
unless a future policy explicitly authorizes an approved support claim.
Synthetic authorization may be used in tests/demo. Do not encode age under
18 as an automatic parent-access rule.

### D3R-14 — Role projection policy pack

Implement a versioned JSON RoleProjectionPolicyPack containing:

- policy_id;
- policy_version;
- policy_hash;
- audience_role;
- purpose_of_use;
- allowed_modes[];
- allowed_source_statuses[];
- allowed_claim_codes[];
- allowed_limitation_codes[];
- public_field_allowlist[];
- required_relation;
- disclosure_requirement;
- synthetic_only;
- review metadata; and
- effective_version.

Use exact policy selection. No default, latest, or wildcard fallback is
allowed.

### D3R-15 — Policy hash

Use the project-consistent canonical JSON SHA-256 approach. A hash mismatch
must fail closed. Direct typed-policy tampering must also be rechecked
defensively before use.

### D3R-16 — Projection monotonicity

The hard invariant is:

output content claim codes MUST be a subset of input D3-2 approved claim
codes.

D3-3 may retain, remove, redact, or suppress. D3-3 must not invent, upgrade,
reinterpret, infer, or merge claims into a stronger psychological claim. Test
this generically.

### D3R-17 — STUDENT_SELF policy

Student output may contain only the student's own projected D3-2 approved
claims, approved public limitations, and the minimal public metadata required
for rendering. It must not contain policy hash, review decision ID,
psychology-review detail, internal evidence references, Safety action, audit
suppression reasons, or internal trust metadata. Current D3-2
MEASUREMENT_ONLY is valid; the implementation must not invent interpretation
to make Student output interesting.

### D3R-18 — TEACHER_SUPPORT policy

The default is deny for individualized psychological assessment claims.
Teacher output must not contain assessment score, theta, SE, construct
psychological meaning, clinical/severity/risk content, review status, policy
identity, Safety status, or hidden claim existence. Future teacher
personalization is allowed only for an explicitly approved
educational-support claim. Current D3-2 does not authorize SUPPORT_TOPIC;
therefore current Teacher projection must produce
NO_PERSONALIZED_DISCLOSURE with zero personalized psychological claims. This
is expected success.

### D3R-19 — PARENT_DEMO policy

Parent production remains PAUSED. Only SYNTHETIC_DEMO may use Parent Demo
projection. Any REAL_USER parent path must fail closed. Age alone must not be
used as authorization. The committed current policy must not present real
psychological interpretation. Test-only neutral claims may be used for
synthetic demonstration.

### D3R-20 — SYSTEM_ADMIN policy

SYSTEM_ADMIN is a technical role, not an audience role for psychological
content. A projection request for SYSTEM_ADMIN must deny or return
NO_PERSONALIZED_DISCLOSURE. There is no implicit superuser content path.

### D3R-21 — Source-status handling

Consume D3-2 canonical status. Only explicitly allowed normal source statuses
may project content. BYPASS_SAFETY and relevant ABSTAIN statuses must not
perform normal role projection. Return BYPASS_SAFETY or ABSTAIN_SOURCE_STATUS
according to the specification. Do not reveal the underlying sensitive
Safety reason in Prompt-facing output.

### D3R-22 — Safety boundary

D3-3 does not calculate Safety, modify Safety, notify a parent, notify a
teacher, route a crisis, or infer a crisis. If the source indicates a Safety
bypass, normal content projection stops. Audit may preserve the source
status. Prompt payloads must not disclose internal Safety action to
Teacher/Parent.

### D3R-23 — Prompt-facing versus audit

Implement two typed output surfaces: PromptFacingProjection and
AuditProjection. They must not be the same model serialized differently.
Prompt-facing output contains only explicitly permitted renderable fields.
Audit output may contain policy identity, suppressed claim codes, suppression
reason, trusted relation, and decision provenance. AuditProjection must not be
accepted by the Prompt Engine public rendering API.

### D3R-24 — Existence side-channel

For non-self audiences, do not reveal hidden claim names, hidden construct
names, hidden field count, suppressed claim count, or whether sensitive
assessment content exists. Public results must be coarse. Prefer
NO_PERSONALIZED_DISCLOSURE for externally indistinguishable denial cases.
Specific denial reasons remain audit-only.

### D3R-25 — Explicit field allowlist

Build PromptFacingProjection from an explicit allowlist. Do not serialize a
full source object and then delete blocked keys. Construct permitted output
from approved fields only.

### D3R-26 — Raw-score boundary

Prompt-facing projection must not contain theta, SE, score aliases, intervals,
bands, or latent values. D3-3 should not need these fields. If D3-2 does not
expose them, prove that D3-3 does not reconstruct them.

### D3R-27 — Role-specific language boundary

D3-3 does not generate natural language. It prepares role-scoped structured
input. D3-1 Prompt Engine remains the language-generation boundary. D3-4
later connects them.

### D3R-28 — Current canonical statuses

Implement these canonical statuses:

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

Any extension requires justification and must not replace the Controller
canonical vocabulary.

### D3R-29 — Public versus audit reason

Prompt-facing results may contain only coarse public reason codes. Detailed
reasons such as CONSENT_MISSING, CLAIM_NOT_VISIBLE, RELATION_FAILED, and
SENSITIVE_SOURCE_PRESENT must remain audit-only when they would leak sensitive
state. Test this boundary.

### D3R-30 — Current policy assets

Create conservative shipped policies for:

- STUDENT_SELF / SELF_UNDERSTANDING;
- TEACHER_SUPPORT / EDUCATIONAL_SUPPORT; and
- PARENT_DEMO / SYNTHETIC_PARENT_DEMO.

Expected current behavior is: Student may receive safe D3-2 public
limitations and approved claims; Teacher returns
NO_PERSONALIZED_DISCLOSURE until explicit approved support claims exist; and
Parent is synthetic/demo only. Admin is denied. Do not fabricate SUPPORT_TOPIC.

### D3R-31 — No new runtime framework

Do not add OpenFGA, OPA, an FHIR server, Keycloak, LangChain, DSPy, or an
external policy engine for D3-3. NIST, FHIR, OpenFGA, and PolicyEngine are
design references only. Use typed Python, versioned JSON, JSON Schema, and
deterministic tests.

### D3R-32 — Contract boundary

D3-3 remains a module-owned internal contract. Do not modify the Frozen Root
or OpenAPI. Root promotion is deferred to D3-4.

### D3R-33 — Implementation worker ownership

After reconnaissance, the bounded worker split is:

- Worker D owns trusted audience models, role/purpose/relation enums,
  projection policy, hash, registry, schemas, policy assets, and policy
  tests.
- Worker E owns projection engine, monotonic filtering, field allowlist,
  prompt/audit split, existence-side-channel protections,
  Student/Teacher/Parent/Admin behavior, and negative tests. Worker E starts
  after Worker D contracts stabilize.
- Worker F owns README, documentation, and read-only D3R fidelity
  preparation, with no overlapping product source.

### D3R-34 — Required security tests

At minimum, test:

1. caller forges STUDENT_SELF -> fail;
2. caller forges TEACHER_SUPPORT -> fail;
3. caller forges relation SELF -> fail;
4. caller forges purpose -> fail;
5. teacher requests student claims -> NO_PERSONALIZED_DISCLOSURE;
6. teacher cannot see hidden claim name;
7. teacher cannot see suppressed count;
8. parent REAL_USER -> fail;
9. parent synthetic demo valid path -> pass;
10. age 17 does not auto-grant parent access;
11. SYSTEM_ADMIN cannot see psychological content;
12. unknown role denies;
13. projection output claims are a subset of input claims;
14. injected stronger claim is rejected;
15. audit fields are absent from prompt payload;
16. audit model is rejected as Prompt-facing input;
17. D3-2 BYPASS_SAFETY stops projection;
18. Safety action is not leaked to Teacher/Parent payload;
19. wildcard/default policy is absent; and
20. policy-hash tamper fails.

### D3R-35 — Side-channel equivalence test

For at least two non-self denial scenarios, such as no claim exists and a
claim exists but is suppressed, the Prompt-facing Teacher result must be
indistinguishable in sensitive details. Both must expose only the same coarse
NO_PERSONALIZED_DISCLOSURE shape or equivalent allowed public shape. Audit
records may differ.

### D3R-36 — Monotonicity property test

For every output claim, claim.code must exist in source.claims, except
projection metadata that is not a psychological/content claim. Test with
randomized or synthetic claim sets where useful. There must be no output claim
semantic expansion.

### D3R-37 — D3-2 regression

Run the accepted D3-2 regression, historically 41/41, or the current
equivalent. Do not modify D3-2 source.

### D3R-38 — D3-1 regression

Run the accepted D3-1 regression, historically 48/48, or the current
equivalent. Do not regress accepted D3-1 behavior.

### D3R-39 — Static and Root gates

Run D3-3 tests, Ruff, Pyright, compile/import, D3-2 regression, D3-1
regression, CAT regression where required by the existing project gate, Root
Contract, OpenAPI, and Frozen Root checks. All required checks must be green
before the bounded implementation can be recommended for Controller review.

### D3R-40 — Real data boundary

Real student data is FORBIDDEN. Use synthetic fixtures only. Do not use real
identity, relationship, or consent data.

### D3R-41 — Decision fidelity report

Create D3_SLICE3_DECISION_FIDELITY_REPORT.md. After implementation, it must
record D3R total = 48, materialized = 48, and semantic deviations = 0. Before
implementation, all such results remain pending and must not be fabricated.

### D3R-42 — Machine evidence

After implementation, create
12_evaluation/d3-slice3-role-projection-r1/d3_slice3_role_projection_evaluation.json.
At minimum it must record the following fields and results: deterministic,
llm_calls=0, rag_calls=0, new_claim_generation=false,
monotonicity=PASS, teacher_default_deny=PASS,
parent_real_user=false, parent_synthetic_demo=PASS,
admin_content_access=false, prompt_audit_separation=PASS,
existence_side_channel=PASS, raw_theta_se=false, safety_leak=false,
policy_hash=PASS, real_student_data=false,
tests/static/regressions/root/frozen results, and remaining P0/P1 items.

### D3R-43 — Closure evidence

Create D3_SLICE3_ROLE_PROJECTION_EVIDENCE.md under
14_docs/project-controller/. Mark it READY_FOR_CONTROLLER_REVIEW only if all
gates pass. Before implementation it must remain a bounded
PRE_IMPLEMENTATION / NOT_YET_VERIFIED skeleton and must not claim acceptance.

### D3R-44 — Commit policy

If all hard gates pass, create one local commit containing only D3-3
implementation/tests/policies/docs, the D3R decision/spec, D3-3 evidence, and
the D3-3 evaluation. The suggested message is
feat(prompt-engine): add minimum-disclosure role projection. Do not merge,
push, or create an accepted tag.

### D3R-45 — Review workers

After implementation, dispatch fresh explicit Workers, all
gpt-5.6-luna / max / none:

- Worker G: Privacy/Security Review of role, relationship, purpose and
  policy-tamper forging, Teacher/Parent leakage, existence side channel, audit
  leakage, monotonicity, and admin escalation.
- Worker H: Tests/Static Review running all required fresh gates.
- Worker I: read-only D3R Fidelity Review returning 48/48, semantic
  deviations, mission deviations, and scope violations.

No reused unverified routing slot may act as final acceptance authority.

### D3R-46 — Hard acceptance gate

READY_FOR_CONTROLLER_REVIEW is permitted only when all applicable boxes below
are satisfied and evidenced:

- D3R 48/48 and semantic deviations 0;
- deterministic execution, zero LLM calls, zero RAG calls;
- trusted audience context and fail-closed raw caller role, purpose, and
  relationship boundaries;
- deny-by-default, exact policy matching, verified policy hash, and no
  wildcard/default/latest fallback;
- monotonicity pass, output claims subset of input claims, and no new
  psychological claim generation;
- STUDENT_SELF relation enforcement;
- Teacher default deny pass and current Teacher personalized claims = 0;
- Parent REAL_USER blocked, Parent synthetic demo pass, and age does not
  authorize parent access;
- SYSTEM_ADMIN content access denied;
- separate Prompt-facing and audit models with audit metadata absent from
  Prompt-facing output;
- hidden claim names and suppressed counts not leaked and side-channel
  equivalence pass;
- D3-2 Safety bypass stops normal projection and Safety reasons are not
  exposed to Teacher/Parent;
- theta/SE absent, with no diagnosis/severity/risk and no natural-language
  generation;
- real student data NONE;
- D3-3 tests, Ruff, Pyright, compile/import, D3-2 regression, D3-1
  regression, Root, OpenAPI, and Frozen Root all pass;
- forbidden modules unchanged;
- one local commit exists, with no merge, push, or accepted tag; and
- remaining P0 is NONE.

### D3R-47 — Stop conditions

Return CONTROLLER_DECISION_REQUIRED if implementation requires any of:

- a D3-2 contract change;
- a D3-1 behavior change;
- a Backend authentication change;
- new real-consent semantics;
- a new parent legal decision;
- a new teacher disclosure decision;
- psychology claim approval;
- a new SUPPORT_TOPIC;
- a Safety architecture change;
- a Root Contract change;
- real data; or
- a new runtime policy engine.

### D3R-48 — Final response boundary

The final D3 Slice 3 response must return one of
READY_FOR_CONTROLLER_REVIEW, PARTIAL_PASS, FAIL, or
CONTROLLER_DECISION_REQUIRED. It must include baseline, worktree, branch,
final commit, D3R fidelity, changed files, trusted-audience boundary, roles,
purposes, relations, policies, monotonicity, Student result, Teacher result,
Parent result, Admin result, existence-side-channel result, Prompt/audit
separation, Safety behavior, raw theta/SE handling, new-claim generation,
tests, Ruff, Pyright, D3-2 regression, D3-1 regression, Root/OpenAPI/Frozen
Root results, real-data status, Worker dispatch ledger, remaining P0/P1,
recommendation, and Controller review focus. D3-4 must not start. The result
waits for Project Controller final review.

## Non-negotiable interpretation boundaries

- D3-3 is a disclosure projection boundary, not a psychometric interpreter.
- D3-3 cannot convert theta, SE, score, band, precision, review metadata, or
  source status into a new psychological meaning.
- The current D1 state remains RECEIVED / REVISIONS_REQUIRED /
  SIGNATURE_BLANK; a submitted review is not unqualified approval.
- D2's 14-source/58-fragment intake remains a separate unpublished,
  rights-unknown, review-pending submission and is not a projection source.
- University freshmen, suggested 17–19, remains the current direction. The
  possible minor status of 17-year-olds does not remove ethics, consent,
  privacy, or validation gates.
- Parent production remains paused. Synthetic/demo behavior does not restore
  parent production or authorize real disclosure.
- Safety remains authoritative and separate. D3-3 can stop projection on a
  trusted Safety bypass but cannot calculate, change, or disclose the Safety
  action.
- Root Contract and OpenAPI promotion is deferred to D3-4.
