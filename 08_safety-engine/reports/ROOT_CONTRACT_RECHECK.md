# Repository-wide Root Contract Recheck

## Result

- Status: `PASS`
- Scope: repository-wide official A-phase contract, schema, and OpenAPI gate
- Official entry point: `00_architecture/tests/run_contract_checks.ps1`
- Working directory: `D:\Projects\StudentMentalHealthAI`
- Exact command: `powershell -NoProfile -ExecutionPolicy Bypass -File .\00_architecture\tests\run_contract_checks.ps1`
- Started: `2026-09-05T13:07:15.9724018+08:00`
- Finished: `2026-09-05T13:07:17.8490741+08:00`
- Python test count: `13 passed, 0 failed`
- OpenAPI validation: `PASS` (`openapi-spec-validator`, target `00_architecture/openapi.v1.json`)
- Process exit code: `0`

The official PowerShell entry point first runs `00_architecture/tests/test_contracts.py`
and then invokes `openapi-spec-validator` for the root OpenAPI document. The 13-test
composition below is the output of the current source, not a hard-coded expected count.

## Current suite composition

The current source contains 9 `ContractSchemaTests` cases and 4 `OpenApiContractTests`
cases:

1. `test_all_positive_fixtures_validate`
2. `test_assessment_required_fields_and_high_risk_invariant`
3. `test_config_does_not_accept_secret_values_or_unknown_keys`
4. `test_contract_document_examples_are_parseable_and_schema_valid`
5. `test_generation_blocking_and_review_invariants`
6. `test_governance_skeleton_is_complete`
7. `test_id_and_version_policy_is_explicit_and_machine_checked`
8. `test_knowledge_status_and_unknown_field_are_rejected`
9. `test_logging_requires_traceability_and_rejects_sensitive_fields`
10. `test_contract_schema_links_exist`
11. `test_openapi_document_has_valid_top_level_shape`
12. `test_operations_have_unique_ids_responses_and_resolvable_refs`
13. `test_public_paths_and_methods_are_complete`

This is separate from Safety's 7-fixture local compatibility check. That local check
is reported as `Safety Local Contract Compatibility` and is not the repository-wide
Root Gate.

## Exact captured stdout

```text
START_TIMESTAMP=2026-09-05T13:07:15.9724018+08:00
WORKING_DIRECTORY=D:\Projects\StudentMentalHealthAI
EXACT_COMMAND=powershell -NoProfile -ExecutionPolicy Bypass -File .\00_architecture\tests\run_contract_checks.ps1
test_all_positive_fixtures_validate (__main__.ContractSchemaTests.test_all_positive_fixtures_validate) ... ok
test_assessment_required_fields_and_high_risk_invariant (__main__.ContractSchemaTests.test_assessment_required_fields_and_high_risk_invariant) ... ok
test_config_does_not_accept_secret_values_or_unknown_keys (__main__.ContractSchemaTests.test_config_does_not_accept_secret_values_or_unknown_keys) ... ok
test_contract_document_examples_are_parseable_and_schema_valid (__main__.ContractSchemaTests.test_contract_document_examples_are_parseable_and_schema_valid) ... ok
test_generation_blocking_and_review_invariants (__main__.ContractSchemaTests.test_generation_blocking_and_review_invariants) ... ok
test_governance_skeleton_is_complete (__main__.ContractSchemaTests.test_governance_skeleton_is_complete) ... ok
test_id_and_version_policy_is_explicit_and_machine_checked (__main__.ContractSchemaTests.test_id_and_version_policy_is_explicit_and_machine_checked) ... ok
test_knowledge_status_and_unknown_field_are_rejected (__main__.ContractSchemaTests.test_knowledge_status_and_unknown_field_are_rejected) ... ok
test_logging_requires_traceability_and_rejects_sensitive_fields (__main__.ContractSchemaTests.test_logging_requires_traceability_and_rejects_sensitive_fields) ... ok
test_contract_schema_links_exist (__main__.OpenApiContractTests.test_contract_schema_links_exist) ... ok
test_openapi_document_has_valid_top_level_shape (__main__.OpenApiContractTests.test_openapi_document_has_valid_top_level_shape) ... ok
test_operations_have_unique_ids_responses_and_resolvable_refs (__main__.OpenApiContractTests.test_operations_have_unique_ids_responses_and_resolvable_refs) ... ok
test_public_paths_and_methods_are_complete (__main__.OpenApiContractTests.test_public_paths_and_methods_are_complete) ... ok

----------------------------------------------------------------------
Ran 13 tests in 0.081s

OK
D:\Projects\StudentMentalHealthAI\00_architecture\tests\..\openapi.v1.json: OK
A-phase contract, Schema, and OpenAPI checks passed.
PROCESS_EXIT_CODE=0
END_TIMESTAMP=2026-09-05T13:07:17.8490741+08:00
```
