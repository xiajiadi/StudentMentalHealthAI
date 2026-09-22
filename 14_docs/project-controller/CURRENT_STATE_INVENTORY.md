# CURRENT STATE INVENTORY

Updated: 2026-09-22. This is the current Controller fact-layer inventory for
the D3 integration worktree. It records accepted evidence without rewriting
historical machine results.

## Repository and publication truth

- Worktree: `D:\Projects\StudentMentalHealthAI-d3-backend-integration`.
- Branch: `exp/d3-backend-integration-v1`.
- Tested Integration Commit: `b1a99326885be0fd93adbf8a46db8c14740bef63`.
- D3-4 Evidence Closure Commit: `80140de6fbb63d3239ecc425f9c3daaaf34fb4d7`.
- Local annotated tag: `d3-slice4-r1-accepted` targeting the Evidence Closure Commit.
- Fact-layer publication is documentation-only and must not be confused with
  the tested product commit.
- Product source is unchanged by the D3-4 evidence closure and this
  publication. Root, OpenAPI, Contract, database schema, and Runtime source
  are unchanged by this publication.

## Controller acceptance state

| Slice | Status | Binding |
|---|---|---|
| D3-1 | FULL PASS / CONTROLLER ACCEPTED | `c6727af1e722134617952383b34db596ed26ca15` |
| D3-2 | FULL PASS / CONTROLLER ACCEPTED | `3539927939ff0340871bb01a329feddb830875e6` |
| D3-3 | FULL PASS / CONTROLLER ACCEPTED | `d3-slice3-r1-accepted` → `cb28fe38b2e1df1b06c96610419691dd2d7924db` |
| D3-4 | FULL PASS / CONTROLLER ACCEPTED | `d3-slice4-r1-accepted` → `80140de6fbb63d3239ecc425f9c3daaaf34fb4d7` |
| D3 overall | ENGINEERING_COMPLETE / SYNTHETIC_DEMO_SCOPE | D3-1 through D3-4 |

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
4. B frontend tournament, later D4 evaluation/red-team slices, D5 operations,
   and D6 RC work remain pending. D4-1 is isolated and ready for Controller
   review; D4-2 through D4-7 are not started.

## D4-1 current slice

- Technical Decision: **FROZEN / CONTROLLER ACCEPTED**.
- SDD: **FROZEN / APPROVED FOR BOUNDED IMPLEMENTATION**.
- Worktree: `D:\\Projects\\StudentMentalHealthAI-d4-evaluation`.
- Branch: `exp/d4-evaluation-foundation-v1`.
- Baseline: `e052e18906dba0256814c1f26209d43f101e919e`.
- Status: **READY_FOR_CONTROLLER_REVIEW**; D4 overall remains
  **NOT_ACCEPTED / NOT_RUN**.
- Evidence: `D4_SLICE1_EVALUATION_FOUNDATION_EVIDENCE.md`.
- Scope is synthetic evaluation foundation only: schemas, authority registry,
  fixture/split governance, manifests, normalized evidence, and sealed-set
  protection. Promptfoo, model, network, behavioral, and product execution did
  not start.

## Verification boundary

This publication did not rerun the full product suite. It verified the local
accepted tag target, clean publication scope, product-source immutability, and
fact-layer consistency. No merge or push was performed.
