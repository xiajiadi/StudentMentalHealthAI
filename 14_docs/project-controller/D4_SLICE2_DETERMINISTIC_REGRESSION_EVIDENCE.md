# D4 Slice 2 · Deterministic Trust & Safety Regression R1

## Controller status

**READY_FOR_CONTROLLER_REVIEW / D4-2R REPAIR CLOSURE CANDIDATE**

This run is a bounded synthetic C0/C1 regression run. It is not D4 overall
acceptance, psychology approval, real-student authorization, pilot readiness,
or production enablement.

## Binding

- Baseline fact-layer commit: `d712e466ae63a412808f5598373a7e769f276e2f`
- Branch: `exp/d4-deterministic-regression-v1`
- Worktree: `D:\Projects\StudentMentalHealthAI-d4-deterministic-regression`
- Accepted foundation tag: `d4-slice1-r1-accepted`
- Failure-preservation commit: `42c2fc8e39dc3f2c571c7760a91b6c16d0110ed2`
- Repair implementation commit: `5400831a6df8ee46d1df421ddc596bbfe37366c0`
- Fast run ID: `D4RUN-20260923T000500Z-d42r-final`
- Manifest: [`12_evaluation/d4-evaluation-r1/manifests/d4_slice2_fast_regression_d4_2r_final.json`](../../12_evaluation/d4-evaluation-r1/manifests/d4_slice2_fast_regression_d4_2r_final.json)
- Manifest hash: `6f669d6ac6f11de573b9ba9fd9b9836a0262a50786e5d3cb5c5b85396b50e79e`
- Machine evidence: [`12_evaluation/d4-evaluation-r1/results/d4_slice2_machine_evidence.json`](../../12_evaluation/d4-evaluation-r1/results/d4_slice2_machine_evidence.json)
- Run summary: [`12_evaluation/d4-evaluation-r1/d4_slice2_deterministic_evaluation.json`](../../12_evaluation/d4-evaluation-r1/d4_slice2_deterministic_evaluation.json)

The deterministic dataset contains 16 `REGRESSION` records. The exact D3
synthetic assessment adapter fixture is bound by canonical-content SHA-256
`cb647c639188e0d1e752c8c842a649a0245a57849458f4cb26d9fc8b7a413abd`.
The historical D4-1 snapshot and its line-ending variants are recorded in
[`D4_FOUNDATION_POST_ACCEPTANCE_ERRATA_V1.md`](D4_FOUNDATION_POST_ACCEPTANCE_ERRATA_V1.md).

## Execution policy

- All cases ran in-process against the accepted Backend ports and ASGI app.
- No GPU, model, Promptfoo, cloud fallback, or external network was used.
- `real_student_data=false`; `cloud_fallback=false`.
- The only runtime dependency used for deterministic responses was the
  accepted `ContractFake` implementation.
- The only product change is the authorized `09_backend` assessment lookup
  minimum-disclosure seam; D3, Root, OpenAPI, RAG, Runtime, Safety policy, and
  Database semantics remain unchanged.

## Result

All 16 scheduled cases passed machine-evidence validation. The focused pytest
wrapper reports `16 passed, 0 failed`; the wrapper summary is
`pass_count=16`, `fail_count=0`, `error_count=0`, `new_p0_count=0`, and
`status=READY_FOR_CONTROLLER_REVIEW`.

### D4E-26 · Hidden existence / assessment side channel — repaired P0 finding

The pre-repair run produced distinguishable denial envelopes:

| Probe | HTTP | Problem code |
|---|---:|---|
| Existing assessment owned by student A | 403 | `forbidden` |
| Unknown assessment identifier | 404 | `resource_not_found` |

The response detail also differs (`access denied` versus `assessment not
found`). This allows a denied caller to distinguish an existing sensitive
assessment from a nonexistent one. The case is recorded as
`observed_outcome=FAIL`, `failure_type=AUTHZ_FAILURE`, and
`D4_P0_FOUND / CONTROLLER_DECISION_REQUIRED`.

The repair now returns the same normalized public envelope for both probes:

| Probe | HTTP | Problem code | Detail |
|---|---:|---|---|
| Existing assessment owned by student A | 404 | `resource_not_found` | `assessment not found` |
| Unknown assessment identifier | 404 | `resource_not_found` | `assessment not found` |

The internal audit stream still records `ASSESSMENT_ACCESS_DENIED` for the
foreign identifier and `ASSESSMENT_NOT_FOUND` for the unknown identifier. No
normal RAG, D3, or Runtime calls occur on either denial.

### D4E-55 · Evidence binding — schema erratum closed

The accepted Backend ledger emits `TX_` plus 32 lowercase hexadecimal
characters. The D4 schema and evidence validator now bind that exact format
(`^TX_[0-9a-f]{32}$`) without changing product identity. D4E-55 is PASS with
the real observed value retained in machine evidence.

## Passing deterministic coverage

The same run produced PASS evidence for trust-field forgery, cross-subject
generation denial, Teacher/Parent/Admin escalation boundaries, canonical route
inventory, prompt measurement boundary, citation membership/hash/provenance
tamper, pending D2 exclusion, no-evidence fail-closed behavior, raw theta/SE
exclusion, crisis hard-stop with zero normal downstream calls, Output Safety
ordering, Safety/RAG/Runtime dependency failures, and the non-transactional
parts of evidence provenance. D4E-57 is promoted on the applicable historical
replay cases. D4E-55 is PASS after the evidence-schema erratum and is bound to
the accepted product's exact transaction identity.

D4E-27 is bounded by an authoritative inventory. Runtime and OpenAPI agree
after excluding FastAPI's generated documentation routes. Canonical support,
generation, and retrieval are `PRESENT_AND_TESTED`; raw Runtime, legacy
renderer, prompt, preview, retry, and regenerate families are
`ABSENT_CONFIRMED` by runtime enumeration, OpenAPI, and static router search.
No nonexistent endpoint was called.

## D4-1 foundation non-regression gate

The complete D4-1 foundation harness now returns `37 passed, 0 failed`.
The 13 core foundation checks and schema/fixture checks use canonical JSON
content identity. The accepted D4-1 tag and its historical snapshot remain
immutable; the three competing hashes and their provenance are recorded in the
post-acceptance errata.

## Decision boundary

The initial failed run remains preserved in
`D4_2R_INITIAL_FAILURE_PRESERVATION.md` and commit `42c2fc8...`. The repair
commit is `5400831...`; regenerated machine evidence is bound to that commit.
No merge, push, or tag action was performed. Promptfoo, external network,
real-student data, and D4-3 remain stopped. This document is a
Controller-review handoff, not a self-acceptance declaration.
