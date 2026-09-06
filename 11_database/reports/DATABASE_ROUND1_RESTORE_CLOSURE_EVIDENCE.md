# Database Round 1 Restore Closure Evidence

Generated: `2026-09-05T15:10:40.108953+00:00`  
Conclusion: **PASS**

## Command/process summary

- Source database: `smhai_round1_test_c01`
- Fresh restored database: `smhai_round1_restore_c01`
- MySQL server: `8.4.8`
- Restore target marked fresh: `True`
- Restore command category: `mysqldump logical backup + mysql SOURCE into a new empty database`
- Restore start UTC: `2026-09-05T15:10:38.5664805Z`
- Restore completion UTC: `2026-09-05T15:10:39.3428427Z`
- Restore exit code: `0`

## Backup identity

- Path: `D:\Dev\backups\studentmentalhealthai\database-round1-c01.sql`
- Timestamp UTC: `2026-09-05T15:10:38.5467287Z`
- Size: `42636` bytes
- SHA-256: `028f857aac25818407516bb0f1c8978e661c33f5407495dee00b768901ab5a01`
- Artifact identity: `True`

## Migration and table identity

| Check | Source | Restored | Match |
|---|---:|---:|---:|
| Alembic revision | `20260905_0001` | `20260905_0001` | True |
| Physical table count | 20 | 20 | True |

Expected physical table count is `20`: 19 domain tables plus
`database_alembic_version`. Table names matched exactly: `True`.

## Deterministic row counts

| Table | Source | Restored | Match |
|---|---:|---:|---:|
| `account_roles` | 0 | 0 | True |
| `accounts` | 1 | 1 | True |
| `assessment_responses` | 1 | 1 | True |
| `assessment_results` | 1 | 1 | True |
| `assessment_sessions` | 1 | 1 | True |
| `audit_events` | 2 | 2 | True |
| `auth_sessions` | 0 | 0 | True |
| `consent_records` | 0 | 0 | True |
| `idempotency_records` | 0 | 0 | True |
| `review_cases` | 1 | 1 | True |
| `review_events` | 1 | 1 | True |
| `roles` | 5 | 5 | True |
| `safety_decisions` | 1 | 1 | True |
| `subject_access_grants` | 0 | 0 | True |
| `subjects` | 2 | 2 | True |
| `support_evidence` | 0 | 0 | True |
| `support_messages` | 2 | 2 | True |
| `support_runs` | 1 | 1 | True |
| `support_sessions` | 1 | 1 | True |

All checked domain-table row counts matched: **True**.

## Safe content hashes

The hashes cover deterministic, non-secret operational fields only. Encrypted plaintext,
password hashes, raw session tokens, CSRF hashes, and key material are excluded.

| Table | Source SHA-256 | Restored SHA-256 | Match |
|---|---|---|---|
| `subjects` | `a614ee8d1ad112e8176598874fc7d3ad3d988153cd11456e9cf2a0569dcbc796` | `a614ee8d1ad112e8176598874fc7d3ad3d988153cd11456e9cf2a0569dcbc796` | True |
| `assessment_sessions` | `835c0880f1157e9b9f06d851e8c794fe27e521fdb7c1a014efaac808d1c44bc0` | `835c0880f1157e9b9f06d851e8c794fe27e521fdb7c1a014efaac808d1c44bc0` | True |
| `support_runs` | `87c9f8c50c2dfaa1f0881cbb3ce58e388bab9b70684d63e51924a56b774c014d` | `87c9f8c50c2dfaa1f0881cbb3ce58e388bab9b70684d63e51924a56b774c014d` | True |
| `support_evidence` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | True |
| `review_cases` | `6c368a74cebd7f7c57dd678afef6e083934a2cf45c0ace533de6db37b96023fe` | `6c368a74cebd7f7c57dd678afef6e083934a2cf45c0ace533de6db37b96023fe` | True |
| `audit_events` | `c8ad5a303686872f0228a993be201206fe1bf00cb2aadb88d1bc8ebcfb883d29` | `c8ad5a303686872f0228a993be201206fe1bf00cb2aadb88d1bc8ebcfb883d29` | True |
| `idempotency_records` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945` | True |

All selected safe content hashes matched: **True**.

## Ciphertext identity

| Payload class | Populated | Source ciphertext SHA-256 | Restored ciphertext SHA-256 | Match |
|---|---:|---|---|---:|
| `assessment_response` | True | `f2f350d4aa85245239aa7a1f318513d3b13dffc1bb7dd66548fb98d6332405be` | `f2f350d4aa85245239aa7a1f318513d3b13dffc1bb7dd66548fb98d6332405be` | True |
| `assessment_result` | True | `59ceca4ff4e764199b57e57668a697530bc9d898ce50e3bc17796b15eaf14985` | `59ceca4ff4e764199b57e57668a697530bc9d898ce50e3bc17796b15eaf14985` | True |
| `support_message` | True | `ebc96ece3bbd9e6ec4260a521cfcd641a05e46e3d356f5417431719d6febaa53` | `ebc96ece3bbd9e6ec4260a521cfcd641a05e46e3d356f5417431719d6febaa53` | True |
| `safety_decision` | True | `3aa7a27f273f3725b480bf59453efa13f53d4ac93451945cb0489bf9a2e7e900` | `3aa7a27f273f3725b480bf59453efa13f53d4ac93451945cb0489bf9a2e7e900` | True |
| `review_case` | True | `23d29236f14e65ff8a7f664ebd48a94aba931185b993f8430add7aaa79fbae92` | `23d29236f14e65ff8a7f664ebd48a94aba931185b993f8430add7aaa79fbae92` | True |
| `review_event` | False | `None` | `None` | True |

Ciphertext hashes matched for all required populated payload classes:
**True**. No ciphertext bytes are printed.

## Encrypted payload decryptability

| Payload class | Status | Schema version | Safe payload keys |
|---|---|---|---|
| `assessment_response` | PASS | assessment-response.v1 | answer, source |
| `assessment_result` | PASS | assessment-result.v1 | schema_version, source |
| `support_message` | PASS | support-message.v1 | text |
| `safety_decision` | PASS | safety-detail.v1 | reason_code |
| `review_case` | PASS | review-note.v1 | note |
| `review_event` | NOT_POPULATED | None | - |

Values were not written to this report. Required populated payloads were decryptable with
the configured development key provider and had the expected schema/key shape:
**True**.

Wrong-key regression: tested `assessment_response`, observed
explicit `EncryptionFailure` failure, result
**True**.

## Foreign-key integrity

| Constraint | Child | Parent | Orphan rows |
|---|---|---|---:|
| `fk_account_roles_account` | `account_roles.account_id` | `accounts.id` | 0 |
| `fk_account_roles_role` | `account_roles.role_id` | `roles.id` | 0 |
| `fk_assessment_responses_session` | `assessment_responses.assessment_session_id` | `assessment_sessions.id` | 0 |
| `fk_assessment_results_session` | `assessment_results.assessment_session_id` | `assessment_sessions.id` | 0 |
| `fk_assessment_sessions_subject` | `assessment_sessions.subject_id` | `subjects.id` | 0 |
| `fk_audit_events_actor` | `audit_events.actor_account_id` | `accounts.id` | 0 |
| `fk_auth_sessions_account` | `auth_sessions.account_id` | `accounts.id` | 0 |
| `fk_consent_records_granted_by` | `consent_records.granted_by_account_id` | `accounts.id` | 0 |
| `fk_consent_records_subject` | `consent_records.subject_id` | `subjects.id` | 0 |
| `fk_review_cases_assignee` | `review_cases.assigned_account_id` | `accounts.id` | 0 |
| `fk_review_cases_safety` | `review_cases.safety_decision_id` | `safety_decisions.id` | 0 |
| `fk_review_cases_subject` | `review_cases.subject_id` | `subjects.id` | 0 |
| `fk_review_events_actor` | `review_events.actor_account_id` | `accounts.id` | 0 |
| `fk_review_events_case` | `review_events.review_case_id` | `review_cases.id` | 0 |
| `fk_safety_decisions_run` | `safety_decisions.support_run_id` | `support_runs.id` | 0 |
| `fk_subject_access_grants_account` | `subject_access_grants.principal_account_id` | `accounts.id` | 0 |
| `fk_subject_access_grants_subject` | `subject_access_grants.subject_id` | `subjects.id` | 0 |
| `fk_support_evidence_run` | `support_evidence.support_run_id` | `support_runs.id` | 0 |
| `fk_support_messages_safety` | `support_messages.safety_decision_id` | `safety_decisions.id` | 0 |
| `fk_support_messages_session` | `support_messages.support_session_id` | `support_sessions.id` | 0 |
| `fk_support_runs_assessment` | `support_runs.assessment_session_id` | `assessment_sessions.id` | 0 |
| `fk_support_runs_session` | `support_runs.support_session_id` | `support_sessions.id` | 0 |
| `fk_support_sessions_assessment` | `support_sessions.assessment_session_id` | `assessment_sessions.id` | 0 |
| `fk_support_sessions_subject` | `support_sessions.subject_id` | `subjects.id` | 0 |

Relationships checked: `24`; total orphan rows:
`0`; result: **True**.

`@@SESSION.FOREIGN_KEY_CHECKS = 1` and
`@@GLOBAL.FOREIGN_KEY_CHECKS = 1`; checks were
re-enabled and the state check passed: **True**.

## Schema sanity

| Check | Result |
|---|---:|
| `all_tables_innodb` | True |
| `all_tables_utf8mb4` | True |
| `all_tables_expected_collation` | True |
| `public_id_unique_for_all_domain_tables` | True |
| `idempotency_scope_key_hash_unique` | True |
| `review_case_version_field` | True |
| `session_hashes_binary_32` | True |
| `encrypted_payloads_binary_or_blob` | True |

Schema sanity result: **True**.

## Source vs restored summary

| Comparison | Result |
|---|---:|
| Migration revision | True |
| Table count | True |
| Table names | True |
| Row counts | True |
| Safe content hashes | True |
| Ciphertext hashes | True |
| Encrypted payload decryptability | True |
| Foreign-key integrity | True |
| Schema sanity | True |
| Overall restore verification | **PASS** |

## Limitations

- This is a local engineering rehearsal against isolated synthetic MySQL data; it is not
  production backup, TLS, KMS/Vault/HSM, PITR, replication, or HA acceptance.
- The comparison proves the selected structural, relational, safe-field, and ciphertext
  properties. It does not assert legal retention periods, clinical validity, or real-data
  readiness.
- The fixture contains synthetic identifiers and payloads only; no real student data was
  used.

## Final restore conclusion

**PASS** — the fresh logical restore is structurally, relationally, and
cryptographically consistent with its synthetic source for the checks above.
