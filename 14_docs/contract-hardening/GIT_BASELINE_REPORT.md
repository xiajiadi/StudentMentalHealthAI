# Git Baseline Report

Baseline date: 2026-09-06 (Asia/Shanghai)  
Repository: D:\Projects\StudentMentalHealthAI  
Remote: none

## Baseline identity

The repository did not contain a Git worktree before this round. After
reconstructing the accepted Software Integration Round 1 evidence and running
the module-local verification commands, the repository was initialized on
main and committed with the required message:

- commit: 65c3df2c28f955a3cbadfc3e01c466d6d89f81a6
- message: chore: establish Software Integration R1 accepted baseline
- tag: integration-r1-accepted

The baseline tag remains on the required baseline commit. A follow-up local
cleanup commit `dfbf1bd` removed two local Qdrant runtime files that were
accidentally staged during initial repository setup; no accepted source or
contract file was changed by that cleanup.

No remote, push, release, or promotion action was performed.

## Evidence used for acceptance

The baseline is based on the current source and these accepted artifacts:

- 15_demo/integration/reports/SOFTWARE_INTEGRATION_ROUND1_ACCEPTANCE.md
- 15_demo/integration/reports/SOFTWARE_INTEGRATION_ROUND1_EVIDENCE.md
- 15_demo/integration/reports/integration_round1_evaluation.json
- 00_architecture/tests/run_contract_checks.ps1

Fresh checks before the baseline commit:

| Check | Result |
|---|---|
| Root contract gate | PASS, 13 tests |
| Backend tests from 09_backend | PASS, 12 tests |
| Database module tests from 11_database | PASS, 10 passed, 6 skipped because MySQL was not active |
| Frontend typecheck | PASS |
| Frontend lint | PASS |
| Frontend unit tests | PASS, 3 files / 9 tests |
| Frontend build | PASS |
| Repository-root aggregate pytest | collection failure caused by module-local import paths; not used as the authoritative baseline command |
| Pre-Git Gitleaks 8.30.1 | 316 redacted generic-api-key findings in dependencies/generated hash-like fixtures; no confirmed credential |
| Post-ignore Gitleaks 8.30.1 | PASS, 0 findings |
| Post-baseline history Gitleaks 8.30.1 | PASS, 0 findings |

The pre-Git and post-ignore scans were required because the project initially
had no root Git metadata or ignore policy. The known synthetic/hash false
positives are scoped in .gitleaks.toml; no secret value is stored in this
report.

## Scope and limitations

This is an accepted local baseline, not a release baseline. MySQL-backed
integration tests were not active in the fresh module-local run; accepted
Software Integration Round 1 evidence supplies the previously recorded real
composition evidence. The root v0.1.0 contract and its SHA-256 manifest are
unchanged. Contract/API hardening starts after this commit/tag and must remain
candidate-only.
