# Data Dictionary

Generated from the SQLAlchemy metadata by `scripts/generate_data_dictionary.py`.
Round 1 contains synthetic fixtures only; sensitivity labels are engineering classifications.

| Table | Column | Type | Nullable | Sensitivity | Encrypted/hashed? | Queryable? | Retention notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `schools` | `school_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Synthetic workspace reference; do not store a real school name |
| `schools` | `status` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `schools` | `data_origin` | `VARCHAR(24)` | no | INTERNAL | No | Yes | Shared origin vocabulary; repository accepts SYNTHETIC only |
| `schools` | `provenance_ref` | `VARCHAR(48) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Registered token `SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1` points to the non-sensitive synthetic school fixture recipe in `test_mysql_integration.py`; no names, member data, PII, credentials, free text, or source content |
| `schools` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `schools` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `schools` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `schools` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `accounts` | `login_name` | `VARCHAR(255)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `accounts` | `password_hash` | `VARCHAR(255)` | no | SECURITY_SECRET | Yes | No | Hash lookup or authentication control |
| `accounts` | `status` | `VARCHAR(16)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `accounts` | `id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `accounts` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `accounts` | `created_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `accounts` | `updated_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `idempotency_records` | `scope` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `key_hash` | `BINARY(32)` | no | SECURITY_SECRET | Yes | No | Hash lookup or authentication control |
| `idempotency_records` | `request_hash` | `BINARY(32)` | no | SECURITY_SECRET | Yes | No | Hash lookup or authentication control |
| `idempotency_records` | `state` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `result_resource_type` | `VARCHAR(64) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `result_public_id` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `expires_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `idempotency_records` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `roles` | `role_code` | `VARCHAR(64) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `roles` | `status` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `roles` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `roles` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `roles` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `roles` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `subjects` | `subject_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `status` | `VARCHAR(16)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `data_origin` | `VARCHAR(24)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `retention_due_at` | `DATETIME(6)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `erased_at` | `DATETIME(6)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `created_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subjects` | `updated_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `account_roles` | `account_id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `role_id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `status` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `granted_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `revoked_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `account_roles` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `assessment_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `subject_id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `instrument_id` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `instrument_version` | `VARCHAR(64) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `item_bank_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `config_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `schema_version` | `VARCHAR(64) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `status` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `started_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `completed_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_sessions` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `actor_account_id` | `BIGINT UNSIGNED` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `action` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `resource_type` | `VARCHAR(64) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `resource_public_id` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `result` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `safe_metadata` | `JSON` | yes | INTERNAL | No | No | Bounded JSON; purge with parent workflow |
| `audit_events` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `audit_events` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `auth_sessions` | `account_id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `session_token_hash` | `BINARY(32)` | no | SECURITY_SECRET | Yes | No | Hash lookup or authentication control |
| `auth_sessions` | `csrf_token_hash` | `BINARY(32)` | yes | SECURITY_SECRET | Yes | No | Hash lookup or authentication control |
| `auth_sessions` | `user_agent_hash` | `BINARY(32)` | yes | SECURITY_SECRET | Yes | No | Hash lookup or authentication control |
| `auth_sessions` | `last_seen_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `idle_expires_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `absolute_expires_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `revoked_at` | `DATETIME(6)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `revocation_reason` | `VARCHAR(128)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `created_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `auth_sessions` | `updated_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `subject_id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `consent_type` | `VARCHAR(128) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `policy_version` | `VARCHAR(64) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `scope_identifier` | `VARCHAR(128) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `granted_by_account_id` | `BIGINT UNSIGNED` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `granted_by_relationship` | `VARCHAR(32)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `granted_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `withdrawn_at` | `DATETIME(6)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `status` | `VARCHAR(16)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `retention_due_at` | `DATETIME(6)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `created_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `consent_records` | `updated_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `principal_account_id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `subject_id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `relationship_type` | `VARCHAR(32)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `status` | `VARCHAR(16)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `valid_from` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `valid_until` | `DATETIME(6)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `revoked_at` | `DATETIME(6)` | yes | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `id` | `BIGINT UNSIGNED` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `created_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `subject_access_grants` | `updated_at` | `DATETIME(6)` | no | PERSONAL | No | Yes | Policy-driven; explicit lifecycle |
| `assessment_responses` | `assessment_session_id` | `BIGINT UNSIGNED` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_responses` | `sequence_no` | `INTEGER` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_responses` | `item_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_responses` | `response_ciphertext` | `MEDIUMBLOB` | yes | PSYCHOLOGICAL_SENSITIVE | Yes | No | Clear ciphertext by retention or synthetic erasure |
| `assessment_responses` | `cipher_format_version` | `VARCHAR(32) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_responses` | `key_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_responses` | `payload_schema_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_responses` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_responses` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_responses` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_responses` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_responses` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_responses` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_results` | `assessment_session_id` | `BIGINT UNSIGNED` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_results` | `schema_version` | `VARCHAR(64) COLLATE ascii_bin` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_results` | `payload_ciphertext` | `MEDIUMBLOB` | yes | PSYCHOLOGICAL_SENSITIVE | Yes | No | Clear ciphertext by retention or synthetic erasure |
| `assessment_results` | `cipher_format_version` | `VARCHAR(32) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_results` | `key_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_results` | `payload_schema_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `assessment_results` | `completed_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_results` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_results` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_results` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_results` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `assessment_results` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `support_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `subject_id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `assessment_session_id` | `BIGINT UNSIGNED` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `target_role` | `VARCHAR(32) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `status` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `started_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `closed_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_sessions` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `run_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `support_session_id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `assessment_session_id` | `BIGINT UNSIGNED` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `generation_ref` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `retrieval_ref` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `status` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `workflow_action` | `VARCHAR(32)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `component_versions` | `JSON` | yes | INTERNAL | No | No | Bounded JSON; purge with parent workflow |
| `support_runs` | `started_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `completed_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `duration_ms` | `INTEGER` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_runs` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `safety_decisions` | `decision_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `safety_decisions` | `support_run_id` | `BIGINT UNSIGNED` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `safety_decisions` | `action` | `VARCHAR(32)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `safety_decisions` | `policy_version` | `VARCHAR(64) COLLATE ascii_bin` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `safety_decisions` | `guard_model_revision` | `VARCHAR(128) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `safety_decisions` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `safety_decisions` | `detail_ciphertext` | `MEDIUMBLOB` | yes | PSYCHOLOGICAL_SENSITIVE | Yes | No | Clear ciphertext by retention or synthetic erasure |
| `safety_decisions` | `cipher_format_version` | `VARCHAR(32) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `safety_decisions` | `key_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `safety_decisions` | `payload_schema_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `safety_decisions` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `safety_decisions` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `safety_decisions` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `safety_decisions` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `safety_decisions` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `support_run_id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `citation_id` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `source_id` | `VARCHAR(128) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `source_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `source_hash` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `locator` | `VARCHAR(512)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `rank_order` | `INTEGER` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_evidence` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `review_ref` | `VARCHAR(128) COLLATE ascii_bin` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_cases` | `subject_id` | `BIGINT UNSIGNED` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_cases` | `safety_decision_id` | `BIGINT UNSIGNED` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_cases` | `priority` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `status` | `VARCHAR(16)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `assigned_account_id` | `BIGINT UNSIGNED` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_cases` | `version` | `INTEGER` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `case_note_ciphertext` | `MEDIUMBLOB` | yes | PSYCHOLOGICAL_SENSITIVE | Yes | No | Clear ciphertext by retention or synthetic erasure |
| `review_cases` | `cipher_format_version` | `VARCHAR(32) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_cases` | `key_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_cases` | `payload_schema_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_cases` | `closed_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_cases` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_messages` | `support_session_id` | `BIGINT UNSIGNED` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `support_messages` | `sequence_no` | `INTEGER` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_messages` | `message_kind` | `VARCHAR(24)` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `support_messages` | `payload_ciphertext` | `MEDIUMBLOB` | yes | PSYCHOLOGICAL_SENSITIVE | Yes | No | Clear ciphertext by retention or synthetic erasure |
| `support_messages` | `cipher_format_version` | `VARCHAR(32) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `support_messages` | `key_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `support_messages` | `payload_schema_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `support_messages` | `safety_decision_id` | `BIGINT UNSIGNED` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `support_messages` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_messages` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_messages` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_messages` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `support_messages` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_events` | `review_case_id` | `BIGINT UNSIGNED` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `event_type` | `VARCHAR(32)` | no | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `actor_account_id` | `BIGINT UNSIGNED` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `from_status` | `VARCHAR(16)` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `to_status` | `VARCHAR(16)` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `note_ciphertext` | `MEDIUMBLOB` | yes | PSYCHOLOGICAL_SENSITIVE | Yes | No | Clear ciphertext by retention or synthetic erasure |
| `review_events` | `cipher_format_version` | `VARCHAR(32) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `key_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `payload_schema_version` | `VARCHAR(64) COLLATE ascii_bin` | yes | PSYCHOLOGICAL_SENSITIVE | No | No | Review policy before retention/erasure |
| `review_events` | `trace_id` | `VARCHAR(128) COLLATE ascii_bin` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_events` | `retention_due_at` | `DATETIME(6)` | yes | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_events` | `id` | `BIGINT UNSIGNED` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_events` | `public_id` | `VARCHAR(36) COLLATE ascii_bin` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_events` | `created_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
| `review_events` | `updated_at` | `DATETIME(6)` | no | INTERNAL | No | Yes | Policy-driven technical/audit retention |
