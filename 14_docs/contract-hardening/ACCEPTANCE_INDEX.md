# Contract/API Hardening Acceptance Index

This index is the evidence map for the candidate-only round. A status is
authoritative only when a current machine-readable artifact or command output
is linked below.

| Area | Evidence | State |
|---|---|---|
| Stage 0 inventory | CURRENT_STATE_INVENTORY.md | complete |
| Reference research | research/OPEN_SOURCE_REFERENCE_AUDIT.md | complete |
| Git baseline | GIT_BASELINE_REPORT.md | pending baseline commit |
| Technical decision | CONTRACT_API_HARDENING_TECHNICAL_DECISION_V1.md | pending |
| Operation inventory | API_OPERATION_INVENTORY.md | pending |
| Error catalogue | ERROR_CATALOG.md | pending |
| Provenance trace | PROVENANCE_TRACE_REPORT.md | pending |
| Candidate OpenAPI | evidence/openapi.hardened.candidate.json | pending |
| Redocly lint | evidence/redocly-lint.json | pending |
| oasdiff compatibility | evidence/oasdiff-compatibility.txt | pending |
| Schemathesis | evidence/schemathesis.ndjson | pending |
| Arazzo/Respect | workflows and evidence/respect.json | pending |
| SDK determinism | evidence/sdk-generation-manifest.json | pending |
| Secret scans | evidence/gitleaks-*.json | pending |
| Acceptance result | reports/CONTRACT_API_HARDENING_ROUND1_ACCEPTANCE.md | pending |
| Machine evaluation | reports/contract_api_hardening_round1_evaluation.json | pending |
| Promotion decision | CONTRACT_PROMOTION_PROPOSAL_V0_2.md | pending |

Root-contract checks remain the separate official gate:
00_architecture/tests/run_contract_checks.ps1.
