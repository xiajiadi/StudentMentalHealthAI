# D4 Slice 2 · Deterministic Trust & Safety Regression R1

## Controller status

**D4_P0_FOUND / CONTROLLER_DECISION_REQUIRED**

This run is a bounded synthetic C0/C1 regression run. It is not D4 overall
acceptance, psychology approval, real-student authorization, pilot readiness,
or production enablement.

## Binding

- Baseline fact-layer commit: `d712e466ae63a412808f5598373a7e769f276e2f`
- Branch: `exp/d4-deterministic-regression-v1`
- Worktree: `D:\Projects\StudentMentalHealthAI-d4-deterministic-regression`
- Accepted foundation tag: `d4-slice1-r1-accepted`
- Fast run ID: `D4RUN-20260922T154300Z-d42p0`
- Manifest: [`12_evaluation/d4-evaluation-r1/manifests/d4_slice2_fast_regression_p0.json`](../../12_evaluation/d4-evaluation-r1/manifests/d4_slice2_fast_regression_p0.json)
- Manifest hash: `fcec57dfcc8802ca315dfd8ac0eea41058c8e1f93e259d84a9288a74ff8726d6`
- Machine evidence: [`12_evaluation/d4-evaluation-r1/results/d4_slice2_machine_evidence.json`](../../12_evaluation/d4-evaluation-r1/results/d4_slice2_machine_evidence.json)
- Run summary: [`12_evaluation/d4-evaluation-r1/d4_slice2_deterministic_evaluation.json`](../../12_evaluation/d4-evaluation-r1/d4_slice2_deterministic_evaluation.json)

The deterministic dataset contains 16 `REGRESSION` records. The fixture is
the exact synthetic assessment adapter fixture, bound by SHA-256
`174c27a4dccbb9e5656afa1d7d79db1920c610768c67ec0705bc58eff7c61398`.
There are no DEV or SEALED records changed by this slice.

## Execution policy

- All cases ran in-process against the accepted Backend ports and ASGI app.
- No GPU, model, Promptfoo, cloud fallback, or external network was used.
- `real_student_data=false`; `cloud_fallback=false`.
- The only runtime dependency used for deterministic responses was the
  accepted `ContractFake` implementation.
- Product directories were not edited.

## Result

14 of 16 scheduled cases passed machine-evidence validation. One P0 failed and
one evidence-binding case remains an error:

The focused pytest wrapper reports `14 passed, 2 failed`; the two failures are
the intentional D4E-26 P0 and the D4E-55 evidence-binding error below. The
remaining 14 cases pass when those two named cases are excluded.

### D4E-26 · Hidden existence / assessment side channel — P0

The same synthetic student-B request produced distinguishable denial envelopes:

| Probe | HTTP | Problem code |
|---|---:|---|
| Existing assessment owned by student A | 403 | `forbidden` |
| Unknown assessment identifier | 404 | `resource_not_found` |

The response detail also differs (`access denied` versus `assessment not
found`). This allows a denied caller to distinguish an existing sensitive
assessment from a nonexistent one. The case is recorded as
`observed_outcome=FAIL`, `failure_type=AUTHZ_FAILURE`, and
`D4_P0_FOUND / CONTROLLER_DECISION_REQUIRED`.

No product fix was attempted. The evidence preserves the route, expected
minimum-disclosure invariant, observed statuses, and the clean coarse Admin
projection check.

### D4E-55 · Evidence binding — P1 evidence error, not a product PASS

The canonical Backend ledger emits a transaction identifier with the product
prefix `TX_...`, while the D4 machine-evidence schema requires the
`TXN_...` pattern. The case still verifies that the generated response carries
the required assessment, retrieval, prompt, model, trace, and persisted
provenance, but the transaction field cannot be schema-bound without changing
the accepted product contract or weakening the D4 foundation schema. It is
therefore recorded as `observed_outcome=ERROR` and
`failure_type=FORMAT_FAILURE`, with the raw product identifier omitted from
the schema field and the limitation preserved. No product repair was made.

## Passing deterministic coverage

The same run produced PASS evidence for trust-field forgery, cross-subject
generation denial, Teacher/Parent/Admin escalation boundaries, canonical route
inventory, prompt measurement boundary, citation membership/hash/provenance
tamper, pending D2 exclusion, no-evidence fail-closed behavior, raw theta/SE
exclusion, crisis hard-stop with zero normal downstream calls, Output Safety
ordering, Safety/RAG/Runtime dependency failures, and the non-transactional
parts of evidence provenance. D4E-57 is promoted on the applicable historical
replay cases. D4E-55 remains an evidence-binding error as described above.

D4E-27 is limited to the routes that actually exist in the accepted Backend
app. The run inventories and checks canonical generation, support, retrieval,
and Safety routes and confirms no direct Runtime or legacy renderer route. It
does not claim that nonexistent prompt, retry, preview, or regenerate routes
were exercised.

## D4-1 foundation non-regression gate

The accepted D4-1 foundation suite was rerun from this worktree and returned
`29 passed, 8 failed`. The eight failures all stop while loading the accepted
D4-1 fixture references: the foundation records require
`datasets/fixtures/synthetic_assessment.v1.json` at SHA-256
`7a18e4a995fe54f00f8d8e0cb5e34b30ae7f99e02f72793391152a3fff6dcc01`, while the
file present in the accepted D4-1 tree hashes to
`cea8c09796ee0c92ced891b6fc7e1d1114fd4a264262a0ca5bfe375f31e40d61`.
This mismatch predates D4-2 and was not changed by this slice. D4-2 therefore
does not claim the D4-1 foundation gate is green; the mismatch remains a
separate Controller-owned P1/blocker and is not repaired here.

## Decision boundary

Because a scheduled P0 is reproducible and D4E-55 cannot be schema-bound, no
D4-2 PASS candidate commit was created. Merge, push, and tag actions were not
performed. D4-3, Promptfoo, and real-pilot work remain stopped pending
Controller direction on the D4E-26 minimum-disclosure contract and the D4E-55
transaction-binding evidence boundary.
