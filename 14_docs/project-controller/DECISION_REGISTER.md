# Decision Register

Updated: 2026-09-24. Decisions below are Controller decisions recorded for
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
| CTRL-31 | At the D4-1 implementation publication, D4 overall remained NOT_ACCEPTED / NOT_RUN and D4-2 through D4-7 were outside that slice. | SUPERSEDED BY CTRL-36 |
| CTRL-32 | The D4-1 foundation remains synthetic/evaluation-only. Real pilot remains BLOCKED and no psychology, clinical, legal, consent, rights, or production approval is implied. | CONFIRMED |
| CTRL-33 | D4-1 Evaluation Foundation is FULL PASS / CONTROLLER ACCEPTED. Local tag `d4-slice1-r1-accepted` targets `05ce1fe59796a4f079e74cc2f425943040dd706a`. | CONFIRMED |
| CTRL-34 | D4-2 Deterministic Trust & Safety Regression implementation was authorized in an isolated evaluation scope. | SUPERSEDED BY CTRL-36 |
| CTRL-35 | At the prior D4-2 authorization publication, D4-2 had not started; real pilot was BLOCKED and D4 overall was NOT_ACCEPTED / NOT_RUN. | SUPERSEDED BY CTRL-36 |
| CTRL-36 | D4-2 Deterministic Trust & Safety Regression is FULL PASS / CONTROLLER ACCEPTED. Local tag `d4-slice2-r1-accepted` targets `2ead2fd6a131f34c2cc7cb71274aed04ce935053`. Its initial D4E-26 sensitive assessment-existence disclosure P0 remains preserved as discovered and repaired evidence. | CONFIRMED |
| CTRL-37 | D4-3A Citation Support & Safe Utility Evaluation Foundation is the current bounded evaluation-only slice. Draft semantic labels are not human gold until Controller/designated reviewer approval; D4 overall remains IN_PROGRESS / NOT_ACCEPTED and real pilot remains BLOCKED. | SUPERSEDED BY CTRL-38 |
| CTRL-38 | D4-3A Citation Support & Safe Utility Evaluation Foundation R1 is FULL PASS / CONTROLLER ACCEPTED. The project owner approved all 7 citation-support and 12 answerability units as drafted; `d4-slice3a-r1-accepted` targets `dd083d7a9d50e554408571e8b6d8040700d7a88b`. The documented Ruff download deviation is accepted as a documented process deviation and remains recorded. | CONFIRMED |
| CTRL-39 | D4-3B Controlled Product Citation Support & Safe Utility Evaluation R1 is authorized from the D4-3A fact-layer publication baseline for the approved synthetic cases on the canonical local product path. No product changes, Promptfoo, D4-4, or real-student data are authorized; D4 overall remains IN_PROGRESS / NOT_ACCEPTED and real pilot remains BLOCKED. | CONFIRMED |

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

## D4-2 acceptance binding

- Preferred branch: `exp/d4-deterministic-regression-v1`.
- Accepted tag: `d4-slice2-r1-accepted` →
  `2ead2fd6a131f34c2cc7cb71274aed04ce935053`.
- Initial P0 evidence: `42c2fc8e39dc3f2c571c7760a91b6c16d0110ed2`.
- Tested repair implementation: `5400831a6df8ee46d1df421ddc596bbfe37366c0`.
- Machine evidence closure: `a63d636482e5a787f5ab5c4bf8598356f79bc1d9`.
- Final documentation closure: accepted commit above.
- D4E-26 sensitive assessment-existence disclosure was preserved and repaired
  with minimum-disclosure behavior. See `D4_SLICE2_ACCEPTANCE_PUBLICATION.md`.
- D4-2 is bounded synthetic engineering. It does not imply psychology,
  clinical, legal/consent, real-student, pilot, or production approval.

## D4-3A acceptance binding

- Human Gold closure commit: `dd083d7a9d50e554408571e8b6d8040700d7a88b`.
- Accepted tag: `d4-slice3a-r1-accepted` →
  `dd083d7a9d50e554408571e8b6d8040700d7a88b`.
- Approved packet: `D4-PACKET-SLICE3A-CITATION-UTILITY-R1`.
- Pre-publication hash: `sha256:8b2e83469888fc195dbf9baea1389f97ab5dcaa0c48e83c9c5ae1efcf25cbe67`.
- Approved Human Gold hash: `sha256:cfbe640300c2cbfbfe9616bb20b10b6ed80e7ee1e15169aadf2052ac8de107c6`.
- Approval record: `D4_SLICE3A_HUMAN_GOLD_APPROVAL.md`; 7 citation-support
  and 12 answerability decisions approved as drafted.
- No case/claim/evidence text, support labels, response classes, applicability
  decisions, pairings, or rubric meanings changed during closure.
- The D4-3A network deviation remains disclosed and is accepted as a documented
  process deviation. It is not described as network-free evidence.
- Acceptance is synthetic engineering/evaluation Human Gold only; it implies
  no psychology, clinical, D2 publication, production, real-student, or pilot
  approval.

## D4-3B current slice binding

- Baseline: this fact-layer publication commit; D4-3B must start at its exact
  Git commit in a new isolated worktree.
- Branch/worktree: `exp/d4-controlled-product-evaluation-v1` /
  `D:\Projects\StudentMentalHealthAI-d4-controlled-product-eval`.
- Scope: one controlled run of the 12 approved synthetic answerability cases,
  using the canonical Backend and accepted local Runtime, loopback-only.
- No product source changes, Promptfoo, real-student data, D4-4, merge, or push.
- Real pilot remains BLOCKED; D4 overall remains IN_PROGRESS / NOT_ACCEPTED.
