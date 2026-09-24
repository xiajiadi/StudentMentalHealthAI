# Dependency Matrix

Updated: 2026-09-24. Current state records accepted D4-1 and D4-2 engineering
baselines and the authorized D4-3A evaluation foundation slice.

| Stage | Depends on | Observable completion | Current state |
|---|---|---|---|
| Frozen Root / API / Contracts | v0.1.0 frozen artifacts | Root and contract evidence unchanged | Accepted baseline; unchanged by D3 publication |
| D1 Psychometrics Engineering | instrument and CAT evidence plus human review boundary | Engineering closure and human psychology review package | Engineering accepted; psychology approval remains separate |
| D2 Knowledge Corpus Engineering | corpus provenance, rights, specialist review | Engineering closure and human review package | Engineering accepted; rights/publication boundary remains separate |
| D3-1 Prompt Engine Core | D1/D2 bounded decisions and frozen prompt contracts | Prompt trust, typing, refusal, and synthetic tests | FULL PASS / CONTROLLER ACCEPTED |
| D3-2 Assessment Interpretation Adapter | accepted D3-1 seam and synthetic measurement policy | deterministic interpretation, abstention, no recalculation | FULL PASS / CONTROLLER ACCEPTED |
| D3-3 Role Projection & Minimum Disclosure | accepted D3-2 output and role policy | typed role projection, monotonicity, minimum disclosure | FULL PASS / CONTROLLER ACCEPTED |
| D3-4 Trusted Backend Orchestration & Evidence Binding | D3-1/D3-2/D3-3, accepted RAG/Safety/Runtime/Database ports | trusted orchestration, evidence binding, GPU Normal, safety and persistence evidence | FULL PASS / CONTROLLER ACCEPTED |
| D3 overall | D3-1 through D3-4 | accepted engineering chain in synthetic/demo scope | ENGINEERING_COMPLETE / SYNTHETIC_DEMO_SCOPE |
| B Frontend Tournament | approved UI candidates and role scope | selected candidate, rendered-flow evidence, relevant verification | Pending |
| D4-1 Evaluation Foundation | accepted D3 and frozen D4 SDD | evaluation schemas, fixture/run governance, normalized evidence | FULL PASS / CONTROLLER ACCEPTED; `d4-slice1-r1-accepted` |
| D4-2 Deterministic Trust & Safety Regression | accepted D4-1 and bounded D4-2 authorization | deterministic synthetic trust/safety regression, including D4E-26 repair evidence | FULL PASS / CONTROLLER ACCEPTED; `d4-slice2-r1-accepted` → `2ead2fd6a131f34c2cc7cb71274aed04ce935053` |
| D4-3A Citation Support & Safe Utility Evaluation Foundation | accepted D4-1/D4-2; synthetic-only and evaluation-only boundaries | claim-support and applicability records, answerability fixtures, reviewer packet and denominator-explicit metrics | Current authorized slice; not yet accepted; human gold review pending |
| D4 overall | all D4 slices and applicable human review | complete D4 evidence with each slice independently accepted | **IN_PROGRESS / NOT_ACCEPTED** |
| D4-3B Controlled Product Generation | D4-3A human-review packet decision and separate authorization | controlled product generation against frozen reviewed gold | Not started; not authorized by the D4-3A foundation scope |
| D5 Windows-first Operations | verified product and D4 boundary | startup, recovery, configuration and cleanup evidence | Pending |
| D6 V0.9 RC / Demo | D4 and D5 closure | RC documentation and synthetic demo | Pending |
| Real pilot | psychology approval, rights/licensing, ethics/consent/privacy, calibration and validation | separate explicit authorization and evidence | **BLOCKED** |

## Preserved P1

- Baseline Backend Pyright SQLAlchemy import-resolution errors.
- Historical GPU snapshot / fixed-output-budget robustness follow-up.
- D5 cleanup PID follow-up.

D3/D4-1 engineering acceptance does not authorize production, clinical use,
real-student disclosure, real pilot, or D4 overall acceptance. D4-2 is
synthetic, deterministic, and evaluation-only; product repair, Promptfoo,
model/network execution, merge, and push remain outside the authorization.
Future population or parent-facing expansion remains a research/review/
validation-dependent option.
