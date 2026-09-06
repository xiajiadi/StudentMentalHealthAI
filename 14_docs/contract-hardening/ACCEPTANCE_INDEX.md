# Contract/API Hardening Acceptance Index

This index is the evidence map for the candidate-only round. A status is
authoritative only when a current machine-readable artifact or command output
is linked below.

| Area | Evidence | State |
|---|---|---|
| Stage 0 inventory | CURRENT_STATE_INVENTORY.md | complete |
| Reference research | research/OPEN_SOURCE_REFERENCE_AUDIT.md | complete |
| Git baseline | GIT_BASELINE_REPORT.md | complete; required commit/tag present |
| Technical decision | CONTRACT_API_HARDENING_TECHNICAL_DECISION_V1.md | complete |
| Operation inventory | API_OPERATION_INVENTORY.md and evidence/operation-id-map.json | complete |
| Error catalogue | ERROR_CATALOG.md | complete |
| Provenance trace | PROVENANCE_TRACE_REPORT.md and evidence/provenance-machine-evidence.json | complete for in-process round trip; MySQL pending |
| Candidate OpenAPI | evidence/openapi.hardened.candidate.json | complete; source-generated |
| Redocly lint | evidence/redocly-lint.json | complete; 0 errors / 0 warnings |
| oasdiff compatibility | OASDIFF_COMPATIBILITY_REPORT.md and evidence/oasdiff-*.txt | executed; breaking findings held for review |
| Schemathesis | evidence/schemathesis-coverage-fuzzing.* and evidence/schemathesis-stateful.* | complete; 0 generated-case failures |
| Arazzo/Respect | workflows and evidence/respect-*.json | partial; reviewer passed, normal/crisis cookie handoff blocked |
| SDK determinism | evidence/sdk-generation-manifest.json | complete; 0.99.0, byte-identical |
| Secret scans | evidence/gitleaks-*.json | complete; 0 post-hardening findings |
| Acceptance result | reports/CONTRACT_API_HARDENING_ROUND1_ACCEPTANCE.md | PARTIAL PASS |
| Machine evaluation | reports/contract_api_hardening_round1_evaluation.json | complete |
| Promotion decision | CONTRACT_PROMOTION_PROPOSAL_V0_2.md | proposal only; hold |

Root-contract checks remain the separate official gate:
00_architecture/tests/run_contract_checks.ps1.
