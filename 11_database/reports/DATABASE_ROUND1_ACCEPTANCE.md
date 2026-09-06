# Database Round 1 Acceptance

## 1 Conclusion

**PASS**, scoped to the `11_database` Round 1 module boundary and synthetic
data only. This is an engineering acceptance result, not a legal, clinical,
privacy-certification, or production-readiness claim.

## 2 Scope

The module owns MySQL persistence, SQLAlchemy models, Alembic migrations,
repositories, transaction boundaries, field encryption persistence,
least-privilege baseline, backup/restore rehearsal, lifecycle controls, and
database documentation. It does not own HTTP routes, frontend behavior,
Backend authorization policy, Safety interpretation, CAT, RAG, or LLM behavior.

The current Backend module has no stable persistence ports to wire. The
compatibility mapping is therefore recorded without changing `09_backend`.

## 3 Runtime

- Python: 3.12.13, project-local environment under `11_database/.venv`.
- MySQL command-line tools: local MySQL Server 8.4.8 installation on D:.
- The final rehearsal used a fresh isolated MySQL data directory, loopback
  port 3307, temporary users, and a temporary database name. The existing
  `MySQL84` service was not modified.

## 4 MySQL

- Version: 8.4.8 Community Server - GPL.
- Release line: MySQL 8.4 LTS.
- Storage engine: InnoDB.
- Server/database charset: `utf8mb4`.
- Server/database collation: `utf8mb4_0900_ai_ci`.
- Runtime timezone report: `SYSTEM`; application timestamp semantics are UTC
  through `DATETIME(6)` and the `utc_now()` helper.
- Strict mode evidence: `STRICT_TRANS_TABLES` was present in `sql_mode`.

The LTS, charset, foreign-key, JSON, encryption, and backup decisions are
grounded in the official [MySQL release documentation](https://docs.oracle.com/cd/E17952_01/mysql-8.4-en/mysql-releases.html)
and [MySQL 8.4 reference manual](https://dev.mysql.com/doc/refman/8.4/en/).

## 5 Open-source Research

The required current-source audit is in
[`research/OPEN_SOURCE_REFERENCE_AUDIT.md`](../research/OPEN_SOURCE_REFERENCE_AUDIT.md).
It records source URLs, versions/revisions, licenses, inspected files or
documentation, adopted patterns, rejected patterns, and whether code was
copied. The implementation uses the libraries as dependencies; no reference
project source was copied.

## 6 Standards / Privacy Research

The design maps PIPL Articles 6, 19, 28, 29, 31, 47, 51, 55, and 56 to
engineering controls in [`PIPL_DATABASE_MAPPING.md`](PIPL_DATABASE_MAPPING.md)
and [`DATA_PRIVACY_MODEL_V1.md`](../DATA_PRIVACY_MODEL_V1.md). The security
mapping is in [`OWASP_DATABASE_SECURITY_MAPPING.md`](OWASP_DATABASE_SECURITY_MAPPING.md).
These documents explicitly avoid legal-compliance claims and leave legal,
ethics, guardian-consent, and retention approval to later gates.

## 7 Technical Decision

[`DATABASE_TECHNICAL_DECISION_V1.md`](../DATABASE_TECHNICAL_DECISION_V1.md)
records D-01 through D-80 with status `PROVISIONALLY_FROZEN`, including MySQL
8.4 LTS, InnoDB, `utf8mb4`, async SQLAlchemy, aiomysql, Alembic, explicit
foreign keys, application field encryption, separate database roles, synthetic
fixtures, and deferred production controls.

## 8 Schema Architecture

The initial migration creates 19 domain tables across identity,
authentication, assessment, support, safety/review, reliability, and audit.
The final physical database contained 20 tables because it also contains the
Alembic version table. Evidence recorded 99 information-schema constraints and
114 indexes. The generated [schema document](../SCHEMA.md),
[data dictionary](../DATA_DICTIONARY.md), and
[Mermaid ERD](database_round1_erd.mmd) are derived from the same metadata.

## 9 Identity / Subject Separation

`accounts` stores authentication identity and a password hash only.
`subjects` stores a pseudonymous subject reference and lifecycle state.
Assessment, support, safety, and review content is not placed in account rows.
Internal IDs are `BIGINT UNSIGNED AUTO_INCREMENT`; external resource IDs are
UUID4 public IDs and are not treated as authorization by themselves.

## 10 Consent

`consent_records` is append-oriented and versioned by consent type, policy
version, scope, relationship, grant/withdrawal timestamps, and status. It does
not store invented legal wording and does not claim that a database row alone
establishes legal sufficiency.

## 11 Auth Sessions

`auth_sessions` stores a cryptographic hash of the opaque session token, plus
optional CSRF and user-agent hashes. The final schema uses `BINARY(32)` for
fixed-length digests. Raw session tokens and raw CSRF tokens are not persisted.

## 12 Assessment Persistence

`assessment_sessions` keeps queryable instrument/version/status/trace metadata.
`assessment_responses.response_ciphertext` and
`assessment_results.result_ciphertext` hold encrypted JSON bytes with explicit
cipher, key, and payload-schema version metadata. No psychometric computation
or clinical cutoff columns were added.

## 13 Support Persistence

`support_sessions`, `support_runs`, and `support_evidence` keep workflow,
trace, provenance, and citation metadata. `support_messages.payload_ciphertext`
stores sensitive message payloads as encrypted binary data. Raw RAG chunks,
internal prompts, and rejected unsafe candidates are not persisted.

## 14 Safety / Review Persistence

Safety action and review queue fields remain queryable as operational state;
detailed safety and review notes are encrypted. `review_cases` uses an explicit
version for lost-update protection. No clinical diagnosis, risk-level, or
psychological-label schema was invented.

## 15 Idempotency

`idempotency_records` uses a unique `(scope, key_hash)` constraint and fixed
length digest columns. `IdempotencyStore` claims the record inside a nested
transaction/savepoint and returns the existing authoritative record on a
duplicate race.

## 16 Audit

`audit_events` records actor/action/resource/result/trace metadata and safe
allowlisted JSON metadata. It has no raw answer, message, safety detail,
review note, prompt, or decrypted psychological payload column.

## 17 Field Encryption

The Round 1 provider serializes bounded JSON and encrypts it with a versioned
Fernet format using pyca/cryptography. Unit and real-MySQL runs verified
round-trip decryption and that stored ciphertext does not contain the test
plaintext.

## 18 Key Management

The development key file is outside both the repository and MySQL, by default
at `D:\Dev\secrets\studentmentalhealthai\database-keys.json`. The provider
fails closed when the key file or requested key version is missing. Production
KMS/Vault/HSM integration is explicitly deferred.

## 19 Key Rotation

`FernetDataProtectionProvider.rotate()` decrypts using the recorded old key and
re-encrypts with the active version. The evidence report records
`key_rotation: true`; a wrong-key decrypt records `wrong_key_failure: true`.

## 20 Retention / Purge

The synthetic lifecycle service deletes encrypted child records in explicit
dependency order, replaces the subject reference with an opaque erased value,
marks the subject `ERASED`, and writes only safe audit metadata. A separate
synthetic retention purge clears due encrypted payloads and key metadata. The
implementation does not hardcode a fake legal retention period.

## 21 SQLAlchemy

SQLAlchemy 2.0.52 is locked and used through declarative mappings,
`AsyncEngine`, `AsyncSession`, and `async_sessionmaker(expire_on_commit=False)`.
Models and API DTOs remain separate concepts. Production schema creation is
migration-controlled; `Base.metadata.create_all()` is not used as the
production path.

## 22 aiomysql

aiomysql 0.3.2 was used for the real async MySQL connection and the six real
integration tests. The URL driver is `mysql+aiomysql`; `asyncmy` remains a
future performance candidate, not a Round 1 dependency.

## 23 Transactions / UnitOfWork

Repositories do not commit independently. `SqlAlchemyUnitOfWork` creates a
per-use-case `AsyncSession`, exposes domain-specific repositories, and owns
commit, rollback, and close. No `AsyncSession` is shared across concurrent
asyncio tasks.

## 24 Constraints

Core relationships use real MySQL foreign keys with explicit `RESTRICT`
behavior by default. Unique public IDs, domain references, scoped idempotency,
state checks, version checks, and bounded relationship values are represented
as database or repository constraints. MySQL native `ENUM` is not used as the
application state baseline.

## 25 Concurrency

Real MySQL integration verified one authoritative idempotency claim under a
concurrent race. Review updates use an expected version and raise an
optimistic-concurrency error on a stale writer. The final real integration
result was 6 passed, 0 failed, 10 deselected.

## 26 Indexes / EXPLAIN

The final real run executed EXPLAIN as the least-privileged app user against a
seeded subject public ID. The plan used `uq_subjects_public_id`, `type=const`,
`rows=1`, and `Using index`. The run also recorded 114 physical indexes in
information schema.

## 27 Alembic

Alembic 1.19.2 is locked. The async environment requires an async MySQL URL,
uses the metadata only for drift comparison, and the reviewed initial
migration does not import current ORM models.

## 28 Migration Stairway

Against a fresh isolated MySQL 8.4.8 database, the final run passed:

1. `upgrade head`
2. `alembic check`
3. `downgrade base`
4. `upgrade head` again
5. `alembic check` again

## 29 Schema Drift

`alembic check` passed both before and after the downgrade/re-upgrade cycle.
The final evidence migration head is `20260905_0001`.

## 30 DB User Least Privilege

The runtime app account was separate from the migrator account. Redacted
`SHOW GRANTS` evidence was:

```text
GRANT USAGE ON *.* TO `smhai_app_20260905_n`@`127.0.0.1`
GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_round1_test_20260905_n`.* TO `smhai_app_20260905_n`@`127.0.0.1`
```

The app user had no `CREATE`, `DROP`, `GRANT OPTION`, or `FILE` privilege.
CREATE TABLE, DROP TABLE, GRANT, and SELECT INTO OUTFILE denial probes all
returned exit code 1.

## 31 Backup

A real synthetic logical backup completed with `mysqldump` using
`--single-transaction`, `--skip-lock-tables`, `--no-tablespaces`, and
`--set-gtid-purged=OFF`. Final artifact:

`D:\Dev\backups\studentmentalhealthai\database-round1-20260905_n.sql`

The dump was 42,657 bytes. It is outside the repository and contains synthetic
data only.

## 32 Restore Drill

The dump was imported into a fresh database named
`smhai_round1_restore_20260905_m`. `scripts/verify_restore.py` successfully
decrypted one restored encrypted assessment response and reported
`decryptable: true` with payload keys `answer` and `source` without printing
the plaintext value.

## 33 Backend Port Mapping

[`BACKEND_PERSISTENCE_MAPPING.md`](BACKEND_PERSISTENCE_MAPPING.md) maps the
expected Backend repository responsibilities to this module's repositories,
transaction behavior, and current status. It is `BLOCKED FOR CROSS-MODULE
WIRING` because `09_backend` currently has no stable persistence ports. No
Backend files were changed.

## 34 Privacy Matrix

[`DATA_PRIVACY_MATRIX.md`](DATA_PRIVACY_MATRIX.md) classifies fields rather
than whole tables: PUBLIC/INTERNAL operational metadata, PERSONAL subject
references, SENSITIVE_PERSONAL consent/access/session metadata,
PSYCHOLOGICAL_SENSITIVE encrypted payloads, and SECURITY_SECRET values that do
not belong in MySQL or source.

## 35 Tests

- Repository/unit run under the final real-MySQL evidence environment: **16
  passed, 0 failed, 0 skipped**.
- Real MySQL integration: **6 passed, 0 failed, 10 deselected**.
- Crypto: round-trip, wrong-key failure, and key rotation passed.
- Lifecycle: synthetic erasure and retention policy tests passed.
- Schema: forbidden raw-secret/plaintext fields and migration metadata tests
  passed.

## 36 Ruff / Pyright

- `uv run ruff format --check database_layer migrations scripts tests`: PASS.
- `uv run ruff check database_layer migrations scripts tests`: PASS.
- `uv run pyright database_layer migrations scripts tests`: PASS, 0 errors.

## 37 Dependency / Compile

- `uv lock --check`: PASS.
- `uv pip check`: PASS.
- `uv run python -m compileall -q database_layer migrations scripts tests`:
  PASS.
- Locked versions: SQLAlchemy 2.0.52, Alembic 1.19.2, aiomysql 0.3.2,
  cryptography 46.0.7.

## 38 Root Contract

The official root suite passed **13 tests, 0 failed**. The machine evidence
also records the root suite exit code as 0.

## 39 Frozen Contract

**NOT MODIFIED.** SHA-256 checks for `CONTRACTS.md` and
`00_architecture/openapi.v1.json` matched the pre-run frozen values. No file in
the root governance or architecture contract surface was changed.

## 40 Real Student Data

**NONE.** All fixtures, database names, backup content, and restore content
were synthetic. No student, teacher, parent, assessment, or consultation case
from real life was used.

## 41 Known Limitations

- The isolated evidence server is a local engineering rehearsal, not a
  production deployment.
- Production TLS certificate configuration, KMS/Vault/HSM, secret-manager
  rotation, network policy, monitoring, and backup encryption are not enabled
  by this module.
- Legal retention periods, guardian-consent semantics, clinical validation,
  and ethics approval are not inferred from the schema.
- Backend composition-root wiring awaits stabilized Backend ports.

## 42 Deferred Items

PITR, replication, HA/read replicas, production TLS rollout, MySQL Enterprise
TDE, production key management, real-data onboarding, formal PIPIA/legal and
ethics approval, Redis/Elasticsearch/ClickHouse, analytics warehouse,
partitioning/sharding, and broader parent/school domains remain deferred. They
are acceptable Round 1 deferrals and are not silently represented as complete.

## 43 Recommendation

Accept the `11_database` Round 1 engineering baseline at the module boundary.
Use [`DATABASE_BACKEND_INTEGRATION_REQUEST.md`](../DATABASE_BACKEND_INTEGRATION_REQUEST.md)
to coordinate later Backend composition wiring, and require a separate
production-data/privacy/security gate before any real student data is admitted.

## Machine Evidence

The authoritative machine-readable snapshot is
[`database_round1_evaluation.json`](database_round1_evaluation.json). It
records MySQL 8.4.8, 20 physical tables including the Alembic version table,
99 constraints, 114 indexes, encryption checks, migration checks, least
privilege, backup, restore, test, root-contract, and frozen-contract status.

# Acceptance Closure

Closure date: **2026-09-05**

Previous Owner Review: **PARTIAL PASS**  
Closure reason: **Restore verification evidence incomplete**  
Closure result: **PASS**

The gap was closed by generating a new logical backup and restoring it into
the fresh synthetic database `smhai_round1_restore_c01`. The generated
closure evidence verifies Alembic revision `20260905_0001`, all 20 physical
tables and names, all 19 domain-table row counts, seven deterministic safe
content-hash sets, required ciphertext hashes, representative payload
decryptability, wrong-key failure, 24 foreign-key relationships with zero
orphans, re-enabled foreign-key checks, and the required schema properties.

- [`DATABASE_ROUND1_RESTORE_CLOSURE_EVIDENCE.md`](DATABASE_ROUND1_RESTORE_CLOSURE_EVIDENCE.md)
- [`database_round1_restore_verification.json`](database_round1_restore_verification.json)
- [`database_round1_evaluation.json`](database_round1_evaluation.json)
- [`DATABASE_DEPENDENCY_REVIEW.md`](DATABASE_DEPENDENCY_REVIEW.md)

The closure rerun also confirmed the application MySQL session timezone is
`+00:00`. This is a non-breaking clarification of the existing UTC
`DATETIME(6)` decision; the frozen root contract and `09_backend` were not
modified.
