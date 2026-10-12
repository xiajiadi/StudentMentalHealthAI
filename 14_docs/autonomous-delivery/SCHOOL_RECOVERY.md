# Synthetic school recovery boundary

Decision: Controller, 2026-10-12. Scope: local synthetic engineering; existing school workspace and databases must remain intact.

## Backup

The original v1 snapshot contains database rows but omits the application encryption-key container. It is a verified sealed snapshot, not a self-contained recoverable installation. Preserve all original files.

The v2 package shall include the original CurrentUser DPAPI application-key container as sealed bytes inside the sealed backup envelope. Do not decrypt application payloads or serialize plaintext application keys, runtime/root passwords, CSRF secrets or session cookies into the package. Restore is limited to the Windows user able to unseal these containers; cross-user or portable restore is unsupported.

Validate version, project, synthetic scope, supported schema revision, source identity, table/column identifiers, row widths and typed values before target creation. Reject unknown tags, malformed Base64 and nonfinite numeric values. Snapshot DDL is evidence only and must never be executed by the importer.

## Restore target and ordering

Only a previously nonexistent external workspace/datadir and a free loopback port may become a restore target. Reject source/target overlap, existing content, reparse points and foreign process ownership. Never DROP, reset, truncate or overwrite an existing schema. Failure preserves the new target and a non-sensitive phase marker for inspection.

Use trusted repository migrations to build precisely supported revision 20261011_0005. MySQL DDL is not transactional; failed migration cannot be described as rolled back. Match the complete snapshot table/column manifest to the trusted revision before importing. Keep foreign-key checks enabled and use a reviewed parent-first dependency order, including composite constraints. Import data transactionally where supported and verify counts and references before publishing readiness.

Restore the original sealed application-key container exclusively to the new private target. Generate new target database/runtime identities and CSRF configuration; never reuse source administrative credentials. Revoke all imported authentication sessions in the target and require fresh login. This is a deliberate recovery transformation; record it in the recovery summary without changing the source snapshot.

## Evidence and current limits

The guarded resume helper passed 24 focused tests and a native ALREADY_RUNNING check against the existing owned workspace. That check did not restart the database. Native missing-service start through the helper, complete restore import, encrypted-payload readability after restore and installation portability remain unverified.

The v2 backup and restore planner are implemented. The planner checks all 27 local model tables plus the Alembic revision table, exact column membership, non-null values, primary keys and ordinary/composite foreign-key references. It maps source column order by name and produces a parent-first plan without changing the snapshot. It does not prevalidate every SQL type, unique constraint or CHECK condition; the trusted migrated target must enforce those during import.

The importer library requires a distinct SCHEMA_READY restore target and exclusive caller ownership. It verifies live database/port/datadir, enabled foreign keys, InnoDB table/column inventory, exact revision and empty business tables before inserts. Parameterized inserts use one transaction, followed by row-count and stored-value readback checks and confirmation that no active imported session remains. Errors are redacted; rollback is attempted and the target is retained. Successful import explicitly returns ready=false pending key/payload/runtime/browser validation. This library neither provisions a target nor executes archived DDL.

Root's actual v2 backup preflight succeeded for 27 business tables and668 rows, with2 sessions requiring revocation in the plan. No target was created or imported by that preflight. Focused planner/importer tests:26 passed in the database virtual environment; static checks passed. An earlier run in the backend virtual environment failed because SQLAlchemy was absent; the database environment is required, with no global installation or hidden substitute.

No restore may be reported as passing until a new isolated target has been restored and checked through real database access and representative browser workflows, with original data preserved. The next action is new-target provisioning and migration, native import, sealed-key installation, ciphertext readability checks and session-denial/relogin verification.
