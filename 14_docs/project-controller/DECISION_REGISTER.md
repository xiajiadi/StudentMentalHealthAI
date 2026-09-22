# Decision Register

Updated: 2026-09-22. Decisions below are Controller decisions recorded for
fact-layer continuity. An engineering acceptance does not substitute for
psychology, ethics, legal, rights, or production authorization.

| ID | Decision | Status |
|---|---|---|
| CTRL-19 | D3-1 Prompt Engine Core is accepted as FULL PASS / CONTROLLER ACCEPTED. | CONFIRMED |
| CTRL-20 | D3-2 Assessment Interpretation Adapter is accepted as FULL PASS / CONTROLLER ACCEPTED. | CONFIRMED |
| CTRL-21 | D3-3 Role Projection & Minimum Disclosure is accepted as FULL PASS / CONTROLLER ACCEPTED. | CONFIRMED |
| CTRL-22 | D3-4 Trusted Backend Orchestration & Evidence Binding is accepted as FULL PASS / CONTROLLER ACCEPTED. | CONFIRMED |
| CTRL-23 | D3 overall engineering status is ENGINEERING_COMPLETE / SYNTHETIC_DEMO_SCOPE. | CONFIRMED |
| CTRL-24 | D3 acceptance grants no psychology approval, psychometric validity, legal/consent approval, real-student authorization, clinical approval, real-pilot readiness, or production enablement. | CONFIRMED |
| CTRL-25 | Real pilot remains BLOCKED pending psychology, rights/licensing, ethics/consent/privacy, calibration, and validation decisions. | CONFIRMED |
| CTRL-26 | Preserve the three D3 P1 items: baseline Backend Pyright errors, GPU snapshot/fixed-output-budget robustness, and D5 cleanup PID. | CONFIRMED |
| CTRL-27 | D4 implementation, D4 branch creation, product-source changes, merge, push, and Root/OpenAPI/Contract changes are not authorized by this publication. | CONFIRMED |
| CTRL-28 | Future population expansion or parent-facing delivery remains possible only after new research, review, and validation. | CONFIRMED |
| CTRL-29 | D4 Technical Decision is FROZEN / CONTROLLER ACCEPTED and the D4 SDD is FROZEN / APPROVED FOR BOUNDED IMPLEMENTATION. | CONFIRMED |
| CTRL-30 | At D4-1 implementation start, the Evaluation Foundation was authorized in the isolated `exp/d4-evaluation-foundation-v1` worktree only and was not yet accepted. | SUPERSEDED BY CTRL-33 |
| CTRL-31 | At the D4-1 implementation publication, D4 overall remained NOT_ACCEPTED / NOT_RUN and D4-2 through D4-7 were outside that slice. | SUPERSEDED BY CTRL-34/35 |
| CTRL-32 | The D4-1 foundation remains synthetic/evaluation-only. Real pilot remains BLOCKED and no psychology, clinical, legal, consent, rights, or production approval is implied. | CONFIRMED |
| CTRL-33 | D4-1 Evaluation Foundation is FULL PASS / CONTROLLER ACCEPTED. Local tag `d4-slice1-r1-accepted` targets `05ce1fe59796a4f079e74cc2f425943040dd706a`. | CONFIRMED |
| CTRL-34 | D4-2 Deterministic Trust & Safety Regression implementation is authorized in an isolated evaluation scope. Product repair, Promptfoo, model/network evaluation, and D4 overall acceptance are not authorized. | CONFIRMED |
| CTRL-35 | D4-2 is authorized but not started; real pilot remains BLOCKED and D4 overall remains NOT_ACCEPTED / NOT_RUN. | CONFIRMED |

## D3 publication bindings

- D3-4 tested Integration Commit: `b1a99326885be0fd93adbf8a46db8c14740bef63`.
- D3-4 evidence closure commit: `80140de6fbb63d3239ecc425f9c3daaaf34fb4d7`.
- Local accepted tag: `d3-slice4-r1-accepted` →
  `80140de6fbb63d3239ecc425f9c3daaaf34fb4d7`.
- D3-3 accepted tag target: `cb28fe38b2e1df1b06c96610419691dd2d7924db`.
- The D3-4 evidence is synthetic/demo-bounded and preserves the GPU and
  historical CPU attempt distinction.

These decisions update only the Controller fact layer. They do not alter
product behavior or any frozen contract.

## D4-1 implementation binding

- Baseline commit: `e052e18906dba0256814c1f26209d43f101e919e`.
- Branch/worktree: `exp/d4-evaluation-foundation-v1` /
  `D:\\Projects\\StudentMentalHealthAI-d4-evaluation`.
- Closure evidence: `14_docs/project-controller/D4_SLICE1_EVALUATION_FOUNDATION_EVIDENCE.md`.
- Accepted tag: `d4-slice1-r1-accepted` → `05ce1fe59796a4f079e74cc2f425943040dd706a`.
- Controller acceptance marker: `D4_SLICE1_READY_FOR_CONTROLLER_ACCEPTANCE`.

## D4-2 authorization binding

- Preferred branch: `exp/d4-deterministic-regression-v1`.
- Baseline: D4-1 acceptance-publication commit `05ce1fe59796a4f079e74cc2f425943040dd706a`.
- Scope: deterministic synthetic trust, safety, privacy, citation-integrity, and
  fail-closed regression only.
- Product source, Root/OpenAPI/Contract/DB, Promptfoo, model/network execution,
  merge, push, and D4-3 remain outside this authorization.
