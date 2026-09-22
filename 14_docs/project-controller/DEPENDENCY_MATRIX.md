# Dependency Matrix

Updated: 2026-09-22. Current state is the Controller-accepted engineering
baseline for D3 plus the bounded D4-1 evaluation foundation under review.

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
| D4 Evaluation / Red Team | accepted D3 plus approved product scope | evaluation, red-team, budget and safety boundary evidence | D4-1 foundation READY_FOR_CONTROLLER_REVIEW; D4 overall NOT_ACCEPTED / NOT_RUN |
| D5 Windows-first Operations | verified product and D4 boundary | startup, recovery, configuration and cleanup evidence | Pending |
| D6 V0.9 RC / Demo | D4 and D5 closure | RC documentation and synthetic demo | Pending |
| Real pilot | psychology approval, rights/licensing, ethics/consent/privacy, calibration and validation | separate explicit authorization and evidence | **BLOCKED** |

## Preserved P1

- Baseline Backend Pyright SQLAlchemy import-resolution errors.
- Historical GPU snapshot / fixed-output-budget robustness follow-up.
- D5 cleanup PID follow-up.

D3 acceptance does not authorize production, clinical use, real-student
disclosure, real pilot, later D4 slices, merge, or push. D4-1 is synthetic and
evaluation-only. Future population or parent-facing expansion remains a
research/review/validation-dependent option.
