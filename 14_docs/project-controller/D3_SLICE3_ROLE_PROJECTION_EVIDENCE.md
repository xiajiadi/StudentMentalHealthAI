# D3 Slice 3 · Role Projection and Minimum Disclosure Evidence

Status: READY_FOR_CONTROLLER_REVIEW

This is the Execution Lead's bounded D3-3 evidence package. It is not
Controller acceptance, psychology approval, legal or consent approval,
real-pilot readiness, clinical validity, rights clearance, or production
enablement.

## 1. Baseline binding

| Field | Value |
|---|---|
| Mission | D3-3 Role Projection and Minimum Disclosure R1 |
| Worktree | D:\Projects\StudentMentalHealthAI-d3-role-projection |
| Branch | exp/d3-role-projection-v1 |
| Baseline HEAD | d9e1cba8b02c26b5661bd139339daed8629f3d1e |
| Accepted D3-2 tested product closure | 3539927939ff0340871bb01a329feddb830875e6 |
| Current product state | D3-3 implemented and freshly verified |
| Evidence state | READY_FOR_CONTROLLER_REVIEW |
| Final commit | One local D3-3 closure commit; SHA is supplied in the Lead handoff after commit |
| Controller acceptance | PENDING_CONTROLLER_DECISION |

The tested D3-2 commit and D3-1 evidence are historical inputs. They do not
replace the fresh checks recorded here.

## 2. Authorized scope

The change is contained in 07_prompt-engine and its D3-3 tests, versioned
policy asset, JSON Schema, README, project-controller evidence documents, and
the machine evaluation under 12_evaluation. No other product module was
changed. D3-4 Backend Integration was not started.

The public API is the typed role projection entry point:

    project(source_result, policy_reference, trusted_audience_context, citations)
    prompt_input(result.prompt)

The first call consumes a role-neutral D3-2 interpretation result. The second
call accepts only the internal PromptFacingProjection surface.

## 3. Implementation summary

The implementation provides:

- typed TrustedAudienceContext with role, purpose, relation, mode,
  disclosure authorization, context version, and an opaque process-local
  capability;
- closed enums for STUDENT_SELF, TEACHER_SUPPORT, PARENT_DEMO,
  SYSTEM_ADMIN, UNKNOWN; SELF_UNDERSTANDING, EDUCATIONAL_SUPPORT,
  SYNTHETIC_PARENT_DEMO; SELF, ASSIGNED_SUPPORT, SYNTHETIC_DEMO; and
  SYNTHETIC_DEMO/REAL_USER modes;
- exact, versioned JSON policy registry and canonical SHA-256 verification;
- fail-closed policy missing, mismatch, tamper, role, purpose, relation,
  authorization, mode, and source-status paths;
- monotonic claim subset enforcement and explicit public-field allowlists;
- separate PromptFacingProjection, AuditProjection, and combined internal
  RoleProjectionResult types;
- coarse non-self denial envelopes that do not reveal hidden claims,
  suppressed counts, result existence, policy identity, or audit details;
- Safety bypass stop behavior with action retained only in audit; and
- rejection/absence of theta, SE, score, band, interval, latent, diagnostic,
  risk, severity, treatment, crisis, and natural-language content.

The shipped policy hashes are:

- Student self: sha256:7396fa34f2e08d24cf415bd526d3647b254492f8ec715150e76e7c22515e40d4
- Teacher support: sha256:378adb0b7a701e1c27bd65c89939d081d9abcf325db622595591f33c81817d7b
- Parent demo: sha256:d562fd172a496674b77d5943502f9413345166c8c3e582a771735e7a5c9be912

All three policies accept only the synthetic MEASUREMENT_ONLY source and
have an empty claim allowlist. Student returns READY_FOR_PROMPT with safe
D3-2 limitations and opaque citations. Teacher and Parent return an empty
NO_PERSONALIZED_DISCLOSURE envelope. Parent REAL_USER returns
ABSTAIN_MODE_NOT_ALLOWED. SYSTEM_ADMIN and UNKNOWN have the same coarse
public denial shape. Age 17 is not authorization.

## 4. Trust and disclosure boundary

Plain caller mappings and direct public model construction cannot create a
privileged context or prompt projection. The internal construction seam is
process-local and intentionally does not claim cryptographic isolation from
hostile same-process code.

D3-3 does not perform authentication, real relationship lookup, legal or
guardian consent, age-based authorization, or psychology approval. Real
parent and teacher psychological disclosure remain blocked. Parent support is
synthetic/demo only. D1 remains RECEIVED / REVISIONS_REQUIRED /
SIGNATURE_BLANK; D2's new 14-source/58-fragment intake remains
rights-unknown/review-pending and is not a source.

Citation records are opaque source_chunk_id plus optional locator. Binding
those IDs to trusted RAG/document snapshots, content hashes, rights,
population, role, and risk scope is explicitly deferred to D3-4.

## 5. Hard-gate results

- [x] D3R 48/48; semantic deviations 0; mission deviations 0
- [x] Deterministic execution; LLM calls 0; RAG calls 0
- [x] Trusted audience context and fail-closed raw caller boundary
- [x] Deny by default; exact policy and canonical hash; no fallback
- [x] Monotonicity and no new claim generation
- [x] STUDENT_SELF relation enforcement
- [x] Teacher default deny and zero personalized claims
- [x] Parent REAL_USER blocked; synthetic/demo path retained
- [x] SYSTEM_ADMIN and UNKNOWN denied
- [x] Prompt-facing/audit type separation
- [x] No audit metadata, hidden claim name, suppressed count, or existence leak
- [x] Safety bypass stops projection and Safety action is not public
- [x] No theta/SE/raw-score/diagnosis/severity/risk/natural language
- [x] Synthetic fixtures only; real student data none
- [x] D3-3 focused tests: 99 passed
- [x] Full 07_prompt-engine tests: 147 passed
- [x] D3-2 regression: 41 passed
- [x] D3-1 regression: 48 passed
- [x] CAT regression: 24 passed
- [x] Ruff: all checks passed
- [x] Pyright: 0 errors, 0 warnings, 0 informations
- [x] Compileall: pass
- [x] Root Contract/OpenAPI wrapper: 13 tests passed, OpenAPI OK, exit 0
- [x] Frozen Root unchanged: diff exit 0, recorded 8/8
- [x] Forbidden modules unchanged
- [x] One local commit only; no merge, push, or accepted tag
- [x] Remaining P0: none

## 6. Worker and review ledger

Every dispatch below explicitly requested gpt-5.6-luna, reasoning effort max,
fork_turns none, and depth 0. The platform does not expose an independent
routing attestation; therefore worker reports are advisory and the Lead
independently reran the executable gates.

| Worker | Scope | Reconciled result |
|---|---|---|
| A | D3 contract mapper, read-only | D3-2 shape, D3-1 context, package boundary, and compatibility risks confirmed |
| B | Privacy/role boundary mapper, read-only | Student self-only, Teacher deny, synthetic Parent-only, Admin/Unknown deny confirmed |
| C | Abuse matrix designer, read-only | Forgery, leakage, side-channel, injection, Safety bypass, fallback, and hash-tamper cases supplied |
| D | Models, registry, schema, contract tests | Implemented and verified; direct prompt forgery and forbidden vocabulary closed |
| E | Projection engine and negative tests | Implemented and verified; Parent coarse shape and source deny-list P2 fixed |
| F | README and project-controller docs | Implemented; README explicitly defers trusted citation binding to D3-4 |
| G | Privacy/security review | PARTIAL with bounded D3-4 P1: current source deny-list fix confirmed; citation snapshot binding remains deferred |
| H | Tests/static review | Executable gates green; Lead reran final commands after the last source fix |
| I | D3R fidelity review | No semantic deviation found; evidence and review boundary reconciled |

## 7. Machine evidence and fresh commands

Machine evidence is stored at:

    12_evaluation/d3-slice3-role-projection-r1/d3_slice3_role_projection_evaluation.json

The JSON records deterministic=true, llm_calls=0, rag_calls=0,
new_claim_generation=false, monotonicity=PASS, Teacher default deny,
Parent real-user=false, synthetic Parent path, Admin content=false,
Prompt/Audit separation=PASS, existence-side-channel=PASS, raw theta/SE=false,
Safety leak=false, policy hash=PASS, real student data=false, test counts,
static checks, Root/Frozen Root results, and remaining P0/P1 items.

Fresh command results:

| Command family | Result |
|---|---|
| 07_prompt-engine focused D3-3 | 99 passed |
| 07_prompt-engine full | 147 passed |
| 03_assessment-adapter | 41 passed |
| 01_cat-engine | 24 passed |
| Root wrapper | 13 passed, OpenAPI OK, WRAPPER_EXIT=0 |
| Frozen Root comparison | exit 0, 8/8 unchanged |

## 8. Remaining P1 and review focus

P0: NONE.

P1:

1. D3-3 citation records are intentionally opaque. Trusted RAG/document
   snapshot binding is a D3-4 responsibility.
2. The capability boundary is process-local; hostile same-process private
   imports, memory mutation, or subclass bypass are outside this mission's
   threat model.

Controller review should confirm that Parent remains a coarse synthetic/demo
path, Teacher has no individualized claim policy, no new psychology claims
were generated, Safety remains authoritative, and the P1 items are deferred.
The recommendation is READY_FOR_CONTROLLER_REVIEW. Controller acceptance is
still pending, and D3-4 remains stopped.
