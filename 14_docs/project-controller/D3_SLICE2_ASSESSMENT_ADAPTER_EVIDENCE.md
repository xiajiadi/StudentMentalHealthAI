# D3 Slice 2 · Assessment Interpretation Adapter · R1 Evidence

Status: `READY_FOR_CONTROLLER_REVIEW`

This is the Execution Lead's bounded implementation recommendation. It is not
Controller acceptance, psychology approval, psychometric validity, real-pilot
readiness, or production enablement.

## 1. Mission

Implement only D3-2 `03_assessment-adapter` from accepted D3-1, preserving the
frozen root contracts and D3I-01 through D3I-40. Do not start D3-3/D3-4/D4/D5/D6.

## 2. Baseline

Baseline is accepted D3-1 commit `c6727af1e722134617952383b34db596ed26ca15` in a
clean worktree. The original main worktree was not used for implementation.

## 3. Frozen Decision

`D3_ASSESSMENT_INTERPRETATION_TECHNICAL_DECISION_V1.md` contains exactly 40
unique D3I identifiers. The fidelity report records materialization and the
remaining governance/downstream boundaries.

## 4. Worktree/Branch

Worktree: `D:\Projects\StudentMentalHealthAI-d3-assessment-adapter`
Branch: `exp/d3-assessment-interpretation-adapter-v1`
Final local commit is created only after this evidence and the staged diff are
checked; no push, merge, or accepted tag is authorized.

## 5. Existing Module State

At the accepted baseline, `03_assessment-adapter` contained its task boundary
but no implementation source, schema, policy asset, fixture, or test suite. The
bounded slice adds those files without changing another product module.

## 6. Architecture

The adapter is typed Python with a versioned JSON policy registry, a module-owned
result schema, and deterministic tests. It makes no LLM, RAG, Safety service,
database, network, or Prompt Engine call.

## 7. CAT Boundary

CAT remains the sole authority for theta, SE, and stopping evidence. D3-2 reads
assessment identity, dimensions, instrument, version, and population for exact
binding; it never recalculates or reinterprets theta/SE.

## 8. Trusted Context

Interpretation requires the internal trusted-context capability. Ordinary
mappings and forged context construction fail closed. The context carries mode,
population, request/trace identity, and the already-decided Safety action.

## 9. Policy Pack

Every selected policy is typed and versioned, binds instrument/version/population,
records allowed modes, review metadata, evidence references, construct metadata,
claim codes, limitations, and a canonical hash.

## 10. Policy Hash

The registry recomputes canonical `sha256:` content and rejects a missing or
mismatched policy hash. Hash identity is part of exact policy selection.

## 11. Exact Policy Match

Selection is exact on policy id, policy version, policy hash, instrument,
instrument version, population, and execution mode. There is no default,
latest, first-entry, or generic psychological fallback.

## 12. Approval Dimensions

The shipped policy records `REVISIONS_REQUIRED` and
`RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK`, matching the reconciled D1
record. This is not psychology approval. Four old construct names are not
silently frozen as approved meanings.

## 13. Current Synthetic Policy

The committed policy is `CURRENT_SYNTHETIC_GRM` / `synthetic_item_bank.v1` for
`SYNTHETIC_STUDENT_DEMO`, `SYNTHETIC_DEMO`, and synthetic engineering use only.
It is conservative and returns `MEASUREMENT_ONLY` with no public interpretation
claims.

## 14. Construct Semantics

Construct direction and high/low meaning are policy metadata. The current
`demo_trait` has no direction or high/low psychological meaning and is not a
diagnostic or severity construct.

## 15. Claim Contract

The output is canonical, typed, and role-neutral. A shipped conservative pack
emits no claims. A neutral `SYNTHETIC_TEST_ONLY` policy is used only to exercise
the test status path and must carry the explicit synthetic-only marker.

## 16. Forbidden Claims

The registry and adapter enforce a global deny-list covering diagnosis,
disorder, clinical severity, risk, suicide, self-harm, crisis, treatment,
Level, cutoff, score/band, theta, SE, interval, and related aliases. Typed
registry objects receive a second defensive check.

## 17. Status Machine

The adapter returns explicit statuses for invalid input, missing/mismatched
policy, population/version/mode mismatch, unapproved construct, Safety bypass,
conservative measurement-only output, and the test-only ready path. It never
returns an empty silent interpretation.

## 18. Reason Codes

Every abstention/bypass path includes a typed reason code, including policy
invalid/hash mismatch, construct unapproved, trusted context required,
assessment schema invalid, and Safety bypass.

## 19. Safety

Trusted `CRISIS_ROUTE`, `REVIEW_REQUIRED`, and `BLOCK` actions bypass/abstain
before interpretation. The adapter preserves the action in audit metadata and
does not change or generate a Safety decision.

## 20. REAL_USER

`REAL_USER` is rejected by the context gate and cannot be admitted by a policy.
Real student data remains prohibited. Only explicitly allowed synthetic or
research modes can proceed, and the current shipped policy allows synthetic demo.

## 21. Raw theta/SE

Raw theta and SE are absent from the public result schema and output projection.
They are not used to produce severity, risk, confidence, crisis, or treatment
claims.

## 22. Precision

SE remains estimate precision only. D3-2 does not independently expose
confidence intervals or reinterpret precision as diagnostic confidence, crisis
probability, or clinical severity.

## 23. RAG

D3-2 does not depend on RAG to decide score meaning. Psychometric policy
provenance and RAG knowledge provenance remain separate domains.

## 24. D2

The unreviewed D2 intake of 14 sources/58 fragments is excluded. No new D2
source, chunk, rights decision, or corpus hash was introduced.

## 25. Tests

Fresh module verification: `35 passed`, with no failures. This includes policy,
hash, exact matching, Safety, modes, output schema, import-scope, deny-list,
identity sanitization, and synthetic-only tests.

## 26. Security negative tests

Twelve forbidden aliases, a direct typed-registry bypass, human-looking invalid
identity values, plain context, REAL_USER, three Safety actions, and
`synthetic_only=false` were exercised. Each failed closed or preserved the
trusted action as required.

## 27. Static

Ruff: `All checks passed!`
Pyright: `0 errors, 0 warnings, 0 informations`
Compile/import smoke: passed.

## 28. CAT Regression

CAT regression in the accepted CAT environment: `24 passed`.

## 29. D3-1 Regression

D3-1 Prompt Engine regression: `48 passed`.

## 30. Root

Root contract gate: `13` tests passed. The first fresh attempt exposed only a
new-environment dependency issue; the rerun used the accepted external backend
environment and passed. No root source was changed.

## 31. OpenAPI

OpenAPI validation completed with `OK` as part of the Root Gate.

## 32. Frozen Root

Eight frozen root blobs match the D3-1 baseline: `FROZEN_MATCH=8/8`. The root
contract, generation.v1, RAG identity, and candidate OpenAPI files are unchanged.

## 33. Real Data

No real student data, production credentials, or personal data was used. The
fixture is explicitly synthetic and the public identity projection retains only
frozen anonymous ID forms.

## 34. Changed Files

Product implementation and tests are confined to `03_assessment-adapter`.
Lead-owned evidence/specification files are under `14_docs/project-controller`
and the machine-readable evaluation is under `12_evaluation`.

## 35. Scope Integrity

No changes were made to CAT, Prompt Engine, RAG, Safety, Backend, Database,
RuntimeService, root contracts, D2 intake, or any forbidden module. No D3-3,
D3-4, D4, D5, or D6 work was started.

## 36. Decision Fidelity

Decision fidelity report: 40/40 D3I identifiers materialized, zero semantic
deviations after the repaired synthetic-only gate, and governance declarations
remain explicitly labelled as governance rather than runtime evidence.

## 37. Worker Dispatch Ledger

All implementation/review dispatches requested `model=gpt-5.6-luna`,
`reasoning_effort=max`, `fork_turns=none`, and worker depth 0. Two read-only
reports used a previously allocated slot; their task messages requested the
same model/settings, but the reused slot's routing metadata was not independently
visible to the Lead and is recorded as such.

| Worker ID / task ID | Model / reasoning / fork | Read scope | Write scope | Files changed | Result | Lead review |
|---|---|---|---|---|---|---|
| `/root/d3_slice2_contract_mapper` | gpt-5.6-luna / max / none | CAT, assessment contract, module | none | none | `NOT_RETURNED / TIMEOUT` | Lead recorded timeout; no evidence used. |
| `/root/d3_slice2_policy_boundary` | gpt-5.6-luna / max / none | D1 reconciliation, D3I | none | none | Returned D1/D2 boundary report | Reconciled and used to keep current policy synthetic-only. |
| `/root/d3_review_scope` | requested gpt-5.6-luna / max / none; reused-slot routing not independently visible | D3I and module abuse surface | none | none | Returned abuse matrix | Used as read-only design input; no files changed. |
| `/root/d3_slice2_implementation` | gpt-5.6-luna / max / none | module implementation | `03_assessment-adapter` only | initial module, policy, schema, fixture, tests, README | Implemented bounded slice and first repairs; no commit | Lead inspected scope and reran checks. |
| `/root/d3_slice2_security_review` | gpt-5.6-luna / max / none | module trust, claims, identity, Safety | none | none | `PARTIAL_PASS`; found claim-injection and identity-echo issues | Repairs were required and independently re-probed. |
| `/root/d3_slice2_static_review` | gpt-5.6-luna / max / none | module, CAT, D3-1, Root, OpenAPI | none | none | Initial static/test review returned pass | Lead reran every affected gate after final repairs. |
| `/root/d3_review_static` | requested gpt-5.6-luna / max / none; reused-slot routing not independently visible | D3I-01..40 and implementation | none | none | Returned fidelity `PARTIAL` because D3I-39 gate was missing | Lead repaired D3I-39 and reconciled the report. |
| `/root/d3_slice2_gate_repair2` | gpt-5.6-luna / max / none | module repair target | `03_assessment-adapter` only | `adapter.py`, `test_assessment_adapter.py` | Added all-mode synthetic-only gate and tests; final module run `35 passed` | Lead reran module, static, security, CAT, D3-1, Root, OpenAPI, and frozen checks. |

No Worker committed, merged, pushed, tagged, changed root contracts, or
delegated recursively.

## 38. Remaining P0

None identified in the bounded D3-2 slice after the final repair. This does not
remove the separate human approval, ethics, privacy, validity, and production
gates.

## 39. Remaining P1

Project-level P1s remain: fixed output budget 768 robustness is deferred to D4;
the historical GPU_PARTIAL resource snapshot must remain distinct from
standalone GPU_FULL evidence; exited-PID cleanup behavior is deferred to D5.

## 40. Recommendation

`READY_FOR_CONTROLLER_REVIEW` for this bounded D3-2 implementation. The
Execution Lead does not self-assign `ACCEPTED` and does not authorize D3-3 until
the Controller reviews this evidence and D1/D2 boundaries.

## 41. Controller Review Focus

Please review: (1) the exact D3I-01..40 fidelity report, (2) the reconciled
`REVISIONS_REQUIRED / SIGNATURE_BLANK` D1 state, (3) the synthetic-only and
forbidden-claim gates, (4) the absence of root-contract changes, and (5) the
separation between this engineering recommendation and psychology approval,
real-pilot readiness, and future population/parent-product expansion.
