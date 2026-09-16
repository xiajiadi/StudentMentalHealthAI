# D3 Slice 3 · Canonical D3R Decision Fidelity Report

Status: READY_FOR_CONTROLLER_REVIEW

This is the Execution Lead's documentation-only correction package for the
Controller's canonical D3R-01 through D3R-48 mapping. The audit was performed
read-only before this correction. It does not grant Controller acceptance,
psychology approval, legal or consent approval, real-pilot readiness, rights
clearance, clinical validity, or production readiness.

## 1. Closure binding

| Field | Value |
|---|---|
| Original product commit | 403acbe37da81e8fb2d5ebb58d6866b4926340b8 |
| Worktree | D:\Projects\StudentMentalHealthAI-d3-role-projection |
| Branch | exp/d3-role-projection-v1 |
| Product baseline | 403acbe37da81e8fb2d5ebb58d6866b4926340b8 |
| Expected product tree after closure | identical to original product commit |
| Technical Decision previously mis-materialized | true |
| Fidelity Report previously mis-mapped | true |
| Product semantic gap found | false |
| Closure scope | documentation and machine-evidence correction only |
| Controller acceptance | NOT_GRANTED / PENDING_CONTROLLER_DECISION |

The earlier Technical Decision had 48 headings, but their contents followed
execution-mission sections and acceptance gates. The earlier Fidelity Report
copied that numbering. The correction below restores the exact Controller
meanings supplied in PROJECT_CONTROLLER_D3R_V1. The product implementation,
tests, schema, policy asset, and original product commit are unchanged.

## 2. Canonical D3R audit table

| D3R | Controller frozen meaning | Implementation evidence | Test evidence | Status |
|---|---|---|---|---|
| D3R-01 | D3-3 belongs to 07_prompt-engine as an independent Role Projection submodule; accepted D3-1 core behavior is not redefined. | role_projection.py and role_projection_models.py are standalone; test_prompt_engine.py remains unchanged. | Full Prompt Engine regression: 147 passed, including D3-1 48 passed. | PASS |
| D3R-02 | D3-3 is deterministic and MUST NOT call an LLM. | role_projection.py has no LLM client or network path. | D3-3 focused tests 99 passed; zero-call design and machine evidence. | PASS |
| D3R-03 | Sole content authority is D3-2 AssessmentInterpretationResult; D3-3 must not reread CAT theta/SE. | project validates the D3-2 source shape and contains no CAT import or theta/SE read path. | Public-field and raw-score negative tests pass. | PASS |
| D3R-04 | D3-3 must not interpret, enrich, or infer new psychological meaning. | Empty shipped claim allowlists and explicit source-claim filtering. | Injection and forbidden-vocabulary tests pass. | PASS |
| D3R-05 | Projected content claims are a subset of approved canonical source claims. | validate_claim_monotonicity checks source and policy subsets. | Source claim injection and monotonicity tests pass. | PASS |
| D3R-06 | D3-3 must not create a new psychological claim code. | No claim generation path; allowed claim codes are policy-controlled. | New/injected claim tests pass. | PASS |
| D3R-07 | Role Projection is not an authentication or authorization replacement; D3-4 Backend owns real identity and relationship verification. | Spec and README explicitly defer authentication/relationship lookup to D3-4. | Trusted-context boundary tests reject raw caller mappings. | PASS |
| D3R-08 | D3-3 requires TrustedAudienceContext or an equivalent trusted context. | project requires TrustedAudienceContext with private capability. | test_raw_mapping_cannot_replace_trusted_context passes. | PASS |
| D3R-09 | Role, purpose, relation, mode, and disclosure authorization are not authoritative merely because a raw caller supplied them. | Controlled builder validates all fields and capability. | Forged context and mismatch tests pass. | PASS |
| D3R-10 | Authorization uses role plus subject/object/context attributes and purpose, not role-only RBAC. | Role matrix checks role, purpose, relation, mode, authorization, and source status. | Role/purpose/relation/authorization matrix tests pass. | PASS |
| D3R-11 | Role Projection Policy is fail-closed. | Missing, mismatch, tamper, and disallowed paths return typed abstentions. | Policy failure tests pass. | PASS |
| D3R-12 | No exact policy means no default, nearest, latest, or wildcard projection. | Registry resolve requires exact id/version/hash. | latest/default/wildcard and missing-policy tests pass. | PASS |
| D3R-13 | Projection Policy uses versioned JSON plus canonical SHA-256. | role_projection_policy_registry.v1.json and canonical_policy_hash. | Registry hash tests pass for all three policies. | PASS |
| D3R-14 | Exact policy identity includes role, purpose, mode, and policy id/version/hash. | resolve_exact binds every supplied selector and source status. | Exact selector and mismatch tests pass. | PASS |
| D3R-15 | Projection is deny-by-default. | Unknown/admin and non-authorized paths construct empty public envelopes. | Admin/unknown and denial tests pass. | PASS |
| D3R-16 | STUDENT_SELF requires trusted subject relation SELF. | Role matrix requires TrustedRelation.SELF. | Forged relation test passes. | PASS |
| D3R-17 | Student sees only D3-2 approved claims/limitations permitted by Student policy. | Student projection uses source subset and policy limitation allowlist. | Student safe limitation and empty-claim test passes. | PASS |
| D3R-18 | Student Prompt-facing payload excludes policy hash, review identity, evidence refs, Safety action, and governance metadata. | Explicit PromptFacingProjection fields contain none of those values. | Public-field and metadata-leak tests pass. | PASS |
| D3R-19 | Student may receive explicitly public-safe typed limitations. | Safe limitation allowlist is explicit and validated. | Student READY_FOR_PROMPT limitation test passes. | PASS |
| D3R-20 | TEACHER_SUPPORT defaults to no individualized psychological claims. | Teacher policy has empty allowed_claim_codes and coarse denial. | Teacher default-deny test passes. | PASS |
| D3R-21 | Future Teacher personalized disclosure may only originate from an explicitly approved EDUCATIONAL_SUPPORT claim. | Teacher policy is bound to EDUCATIONAL_SUPPORT and empty until a reviewed claim is added. | Policy purpose and empty-allowlist tests pass. | PASS |
| D3R-22 | Teacher requires trusted relation, purpose, and disclosure policy; role alone is insufficient. | Teacher matrix validates ASSIGNED_SUPPORT, purpose, mode, and authorization. | Teacher forgery/mismatch tests pass. | PASS |
| D3R-23 | Current V0.9 has no approved SUPPORT_TOPIC; Teacher produces zero personalized claims. | No SUPPORT_TOPIC in policy or source allowlists. | Teacher output claim count is zero. | PASS |
| D3R-24 | PARENT_DEMO is allowed only for SYNTHETIC_DEMO. | Parent policy permits only SYNTHETIC_DEMO mode/relation. | Parent synthetic mode tests pass. | PASS |
| D3R-25 | Parent REAL_USER disclosure remains blocked. | REAL_USER is excluded from parent policy and mode checks fail closed. | Parent REAL_USER test passes with ABSTAIN_MODE_NOT_ALLOWED. | PASS |
| D3R-26 | Age alone must not automatically authorize parent disclosure. | No age field or age authorization branch exists; parent authorization is typed synthetic-only. | Parent authorization/mode tests pass; no age-derived access path exists. | PASS |
| D3R-27 | Future real parent disclosure requires separate legal, ethical, and consent policy. | Spec defers real consent/legal workflow to future policy and D3-4. | No real-user or consent implementation is present. | PASS |
| D3R-28 | SYSTEM_ADMIN is not a psychology audience and has no implicit full-content access. | SYSTEM_ADMIN is outside ALLOWED_AUDIENCE_ROLES and maps to coarse denial. | Admin denial test passes. | PASS |
| D3R-29 | Unknown role, relation, or purpose fails closed. | Closed enums and role matrix return typed abstention/denial. | Unknown and forged-value tests pass. | PASS |
| D3R-30 | Current purposes include SELF_UNDERSTANDING, EDUCATIONAL_SUPPORT, and SYNTHETIC_PARENT_DEMO. | PurposeOfUse enum and three policy records contain exactly these values. | Enum and registry tests pass. | PASS |
| D3R-31 | Purpose comes from trusted context, not caller self-assertion. | Context builder capability and purpose validation are required. | Forged-purpose test passes. | PASS |
| D3R-32 | D3-2 BYPASS_SAFETY does not enter normal projection; D3-3 returns coarse BYPASS_SAFETY. | project handles BYPASS_SAFETY before normal policy projection. | Safety bypass tests pass for CRISIS_ROUTE, REVIEW_REQUIRED, and BLOCK. | PASS |
| D3R-33 | CRISIS_ROUTE, REVIEW_REQUIRED, and BLOCK details must not leak to Teacher/Parent Prompt-facing payloads. | Safety action is retained only on AuditProjection. | Safety action non-leak tests pass. | PASS |
| D3R-34 | D3-3 does not notify parent/teacher or perform crisis notification. | No notification or routing dependency exists in the module. | Deterministic local tests and source inspection show no notification path. | PASS |
| D3R-35 | Prompt-facing projection uses explicit field allowlists. | _build_prompt_facing_projection constructs only status, claims, limitations, citations. | Public envelope/schema tests pass. | PASS |
| D3R-36 | PromptFacingProjection and AuditProjection are separate typed surfaces. | Distinct dataclasses and RoleProjectionResult fields. | Audit-to-prompt rejection and surface tests pass. | PASS |
| D3R-37 | Prompt-facing payload excludes suppressed count, hidden claim names, and detailed sensitive denial reason. | Denial envelope is coarse and empty. | Hidden-claim and suppressed-count side-channel tests pass. | PASS |
| D3R-38 | Non-self projection protects against sensitive-result-existence side channels. | Teacher/Parent no-claim and hidden-claim outputs use the same public shape. | Side-channel equivalence tests pass. | PASS |
| D3R-39 | Audit may retain provenance, but audit data must never automatically enter Prompt input. | prompt_input accepts only PromptFacingProjection and rejects AuditProjection/combined results. | Prompt/audit rejection tests pass. | PASS |
| D3R-40 | Public projection contains no raw theta/SE, diagnosis, severity, clinical risk, or crisis inference. | Forbidden source/prompt vocabulary and explicit public fields. | Raw-score/clinical-code schema and runtime tests pass. | PASS |
| D3R-41 | D3-3 produces structured projection only; natural-language generation remains D3-1 responsibility. | role_projection.py produces typed dictionaries only and has no generator. | Full Prompt Engine regression remains green. | PASS |
| D3R-42 | D3-3 does not call RAG or query the D2 corpus. | No RAG/D2 imports or lookup path; citations remain opaque. | Machine evidence records rag_calls=0; deterministic tests pass. | PASS |
| D3R-43 | No new OpenFGA, OPA, FHIR server, LangChain, or similar runtime dependency. | No dependency or runtime framework was added. | Static/package diff review passes. | PASS |
| D3R-44 | Implementation uses transparent typed Python, versioned JSON policy, schema, and deterministic tests. | Models, engine, registry asset, JSON Schema, and tests are explicit. | Focused/full test and static gates pass. | PASS |
| D3R-45 | D3-3 contract is module-owned internal contract; Frozen Root is unchanged. | Changes are confined to D3-3 assets/docs; Root diff is zero. | Frozen Root comparison exit 0, recorded 8/8. | PASS |
| D3R-46 | Root contract promotion remains deferred to D3-4. | README/spec/evidence explicitly defer promotion. | No Root/OpenAPI product changes. | PASS |
| D3R-47 | Only synthetic/research engineering data is allowed; real student data remains forbidden. | Fixtures and policies are synthetic-only; no real identity/relationship/consent data. | Repository/data inspection and machine evidence pass. | PASS |
| D3R-48 | Engineering PASS does not imply legal compliance, psychology approval, real disclosure authorization, pilot readiness, or production readiness. | Decision/spec/evidence repeat the boundary and keep Controller acceptance pending. | Review package status is READY_FOR_CONTROLLER_REVIEW, not ACCEPTED. | PASS |

Canonical audit totals: expected 48; materialized 48; PASS 48; PARTIAL 0;
MISSING 0; CONFLICT 0; semantic deviations 0; mission deviations 0.

## 3. EXECUTION_MISSION_COMPLIANCE

These are execution steps and evidence gates, not D3R meanings.

| Execution item | Result |
|---|---|
| Initial baseline | HEAD 403acbe37da81e8fb2d5ebb58d6866b4926340b8; working tree clean |
| Read-only audit before edits | Completed against Technical Decision, Spec, old Fidelity Report, source, tests, and machine JSON |
| Product tree integrity | git diff --quiet 403acbe... -- 07_prompt-engine exit 0 after closure |
| Forbidden modules | No changes after original product commit |
| Product semantic modification | None authorized or performed |
| Documentation correction | Technical Decision, Implementation Spec reference, Fidelity Report, Closure Evidence, Machine JSON only |
| Machine evidence parse | JSON parse and decision_fidelity consistency PASS |
| Fresh fidelity worker | /root/d3_canonical_fidelity; model gpt-5.6-luna; reasoning max; fork_turns none; depth 0; advisory result independently reconciled by Lead; expected=48, passed=48, partial=0, missing=0, conflict=0 |
| Commit policy | One local evidence/governance closure commit; no amend of 403acbe |
| Merge/push/tag | None |
| D3-4 | Not authorized and not started |

The product implementation and tests were not rerun for this
documentation-only closure. Their previous fresh results remain bound to
403acbe: D3-3 focused 99 passed, full Prompt Engine 147 passed, D3-2 41
passed, D3-1 48 passed, CAT 24 passed, Ruff pass, Pyright 0 errors, compile
pass, Root Contract 13 passed, OpenAPI pass, and Frozen Root 8/8 unchanged.

## 4. Controller review boundary

Product P0: none. Evidence/governance P0: none after this correction.

Remaining P1:

1. Citation records are intentionally opaque in D3-3; binding them to the
   trusted RAG/document snapshot, content hash, rights state, population
   scope, and role/risk scope remains a D3-4 responsibility.
2. The typed capability seam is process-local. Hostile same-process private
   imports, memory mutation, or subclass bypass are outside this mission's
   threat model.

Recommendation: READY_FOR_CONTROLLER_REVIEW. Controller acceptance remains
pending. Do not start D3-4 from this report.
