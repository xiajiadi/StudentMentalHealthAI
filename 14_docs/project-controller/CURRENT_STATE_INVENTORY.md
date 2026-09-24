# CURRENT STATE INVENTORY

Updated: 2026-09-24. This is the current Controller fact-layer inventory for
the D4-3A Human Gold publication baseline and authorized D4-3B next slice. It
records accepted evidence without rewriting historical machine results.

## Repository and publication truth

- D4-3A implementation worktree/branch: `D:\Projects\StudentMentalHealthAI-d4-citation-utility` /
  `exp/d4-citation-utility-foundation-v1`.
- D4-3A Human Gold closure commit: `dd083d7a9d50e554408571e8b6d8040700d7a88b`.
- Local annotated tag: `d4-slice3a-r1-accepted` targets that exact commit.
- This documentation-only fact-layer publication commit is the D4-3B baseline;
  resolve its exact commit from Git HEAD.
- Authorized D4-3B branch/worktree: `exp/d4-controlled-product-evaluation-v1` /
  `D:\Projects\StudentMentalHealthAI-d4-controlled-product-eval`, to be
  created from this fact-layer publication commit.
- Product source, Root/OpenAPI/Contract, database schema, D3 behavior, and
  Runtime configuration are unchanged by the D4-3A publication.

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
| D4-3A Citation Support & Safe Utility Evaluation Foundation | FULL PASS / CONTROLLER ACCEPTED | `d4-slice3a-r1-accepted` → `dd083d7a9d50e554408571e8b6d8040700d7a88b`; Human Gold packet hash `sha256:cfbe640300c2cbfbfe9616bb20b10b6ed80e7ee1e15169aadf2052ac8de107c6` |
| D4 current slice | D4-3B Controlled Product Citation Support & Safe Utility Evaluation R1 | Authorized; not started; isolated worktree will use this fact-layer commit |
| D4 overall | IN_PROGRESS / NOT_ACCEPTED | D4-1, D4-2, and D4-3A accepted; D4-3B remains in progress/not accepted |

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
   D6 RC work remain pending. D4-1, D4-2, and D4-3A are accepted. D4-3B is the
   current authorized controlled product-evaluation slice; D4 overall remains
   not accepted.

## D4-1 through D4-3A accepted / D4-3B current slice

- Technical Decision: **FROZEN / CONTROLLER ACCEPTED**.
- SDD: **FROZEN / APPROVED FOR BOUNDED IMPLEMENTATION**.
- Worktree: `D:\\Projects\\StudentMentalHealthAI-d4-evaluation`.
- Branch: `exp/d4-evaluation-foundation-v1`.
- Baseline: `e052e18906dba0256814c1f26209d43f101e919e`.
- Status: **FULL PASS / CONTROLLER ACCEPTED**; accepted tag
  `d4-slice1-r1-accepted` → `05ce1fe59796a4f079e74cc2f425943040dd706a`.
  D4-2 was accepted within its bounded deterministic scope; the current D4
  progression through D4-3A and D4-3B is recorded below.
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
- D4-3A is **FULL PASS / CONTROLLER ACCEPTED**. The owner-approved packet
  contains 7 citation-support and 12 answerability Human Gold decisions; its
  accepted hash is `sha256:cfbe640300c2cbfbfe9616bb20b10b6ed80e7ee1e15169aadf2052ac8de107c6`.
- Current slice: **D4-3B Controlled Product Citation Support & Safe Utility
  Evaluation R1**. Its only approved inputs are synthetic evaluation fixtures;
  formal data-plane endpoints must be verified as loopback-only before calls.
  The documented D4-3A Ruff download is retained and accepted as a documented
  process deviation; it is not rewritten as network-free evidence.

## Verification boundary

D4-3A closure reran the citation/utility suite (56), D4-1 foundation (37),
D4-2 deterministic regression (16), Ruff/format, compile, Root (13/13), and
both OpenAPI validators. No product/model calls occurred. The D4-3A accepted
tag target, governance-only publication diff, product-source immutability, and
fact-layer consistency were verified. D4-3B product execution had not started
at this publication. No merge or push was performed.
