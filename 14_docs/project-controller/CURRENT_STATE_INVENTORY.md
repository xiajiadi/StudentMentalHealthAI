# CURRENT STATE INVENTORY

Updated: 2026-09-24. This is the current Controller fact-layer inventory for
the accepted D4-2 publication baseline. It records accepted evidence without
rewriting historical machine results.

## Repository and publication truth

- Worktree: `D:\Projects\StudentMentalHealthAI-d4-deterministic-regression`.
- Branch: `exp/d4-deterministic-regression-v1`.
- D4-2 accepted commit: `2ead2fd6a131f34c2cc7cb71274aed04ce935053`.
- Local annotated tag: `d4-slice2-r1-accepted` targets that exact commit.
- Fact-layer publication is documentation-only and is distinct from the
  accepted deterministic implementation/evidence closure.
- Product source was changed only within the D4-2R authorization in
  `09_backend` to close the D4E-26 assessment-existence disclosure. This
  acceptance publication changes no product source, Root, OpenAPI, Contract,
  database schema, D3 behavior, or Runtime configuration.

## Controller acceptance state

| Slice | Status | Binding |
|---|---|---|
| D3-1 | FULL PASS / CONTROLLER ACCEPTED | `c6727af1e722134617952383b34db596ed26ca15` |
| D3-2 | FULL PASS / CONTROLLER ACCEPTED | `3539927939ff0340871bb01a329feddb830875e6` |
| D3-3 | FULL PASS / CONTROLLER ACCEPTED | `d3-slice3-r1-accepted` → `cb28fe38b2e1df1b06c96610419691dd2d7924db` |
| D3-4 | FULL PASS / CONTROLLER ACCEPTED | `d3-slice4-r1-accepted` → `80140de6fbb63d3239ecc425f9c3daaaf34fb4d7` |
| D3 overall | ENGINEERING_COMPLETE / SYNTHETIC_DEMO_SCOPE | D3-1 through D3-4 |
| D4-1 Evaluation Foundation | FULL PASS / CONTROLLER ACCEPTED | `d4-slice1-r1-accepted` → `05ce1fe59796a4f079e74cc2f425943040dd706a` |
| D4-2 Deterministic Trust & Safety Regression | FULL PASS / CONTROLLER ACCEPTED | `d4-slice2-r1-accepted` → `2ead2fd6a131f34c2cc7cb71274aed04ce935053` |
| D4 current slice | D4-3A Citation Support & Safe Utility Evaluation Foundation | Evaluation-only work; semantic gold awaits human review |
| D4 overall | IN_PROGRESS / NOT_ACCEPTED | D4-1 and D4-2 accepted; D4-3A not yet accepted |

D3-4 evidence records D3SEAM 20/20, D3INT 60/60, D3VAL 16/16, zero semantic
and mission deviations, GPU Normal PASS, trace/persistence evidence, and the
historical CPU resource-blocked attempt. The accepted GPU evidence remains
synthetic/demo-bounded.

## Human and safety boundary

The engineering status does not provide psychology approval, psychometric
validity, legal/consent approval, rights/licensing clearance, real-student
disclosure authorization, clinical approval, real-pilot readiness, or
production enablement. Real pilot remains **BLOCKED**. Future population
expansion or parent-facing delivery requires new research, review, and
validation.

## Preserved P1 and pending stages

1. Baseline Backend Pyright SQLAlchemy import-resolution errors.
2. Historical GPU snapshot and fixed-output-budget robustness follow-up.
3. D5 cleanup PID follow-up.
4. B frontend tournament, remaining D4 evaluation slices, D5 operations, and
   D6 RC work remain pending. D4-1 and D4-2 are accepted. D4-3A is the current
   authorized evaluation-only slice; D4 overall remains not accepted.

## D4-1 and D4-2 accepted / D4-3A current slice

- Technical Decision: **FROZEN / CONTROLLER ACCEPTED**.
- SDD: **FROZEN / APPROVED FOR BOUNDED IMPLEMENTATION**.
- Worktree: `D:\\Projects\\StudentMentalHealthAI-d4-evaluation`.
- Branch: `exp/d4-evaluation-foundation-v1`.
- Baseline: `e052e18906dba0256814c1f26209d43f101e919e`.
- Status: **FULL PASS / CONTROLLER ACCEPTED**; accepted tag
  `d4-slice1-r1-accepted` → `05ce1fe59796a4f079e74cc2f425943040dd706a`.
  D4 overall now remains **IN_PROGRESS / NOT_ACCEPTED** after D4-2 acceptance.
- Evidence: `D4_SLICE1_EVALUATION_FOUNDATION_EVIDENCE.md`.
- Scope was synthetic evaluation foundation only: schemas, authority registry,
  fixture/split governance, manifests, normalized evidence, and sealed-set
  protection. Promptfoo, model, network, behavioral, and product execution did
  not start.
- D4-2 is **FULL PASS / CONTROLLER ACCEPTED**. Its local accepted tag
  `d4-slice2-r1-accepted` resolves to
  `2ead2fd6a131f34c2cc7cb71274aed04ce935053`.
- D4-2R preserved the initial D4E-26 P0 finding, repaired the public
  assessment-existence disclosure, corrected the evaluation transaction-ID
  schema, resolved exact D3 fixture provenance, and closed the bounded route
  inventory. The original evidence remains historical and retains its
  candidate status.
- Current slice: **D4-3A Citation Support & Safe Utility Evaluation
  Foundation**. Draft semantic labels and MUST_ANSWER cases require Controller
  or designated human review before they can be counted as human gold.

## Verification boundary

This publication did not rerun the product suite. It verified the D4-2 local
accepted tag target, governance-only diff scope, product-source immutability,
and fact-layer consistency. No merge or push was performed.
