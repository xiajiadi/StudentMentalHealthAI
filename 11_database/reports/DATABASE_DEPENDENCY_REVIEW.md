# Database Dependency Review — Round 1 Closure

Date: 2026-09-05  
Scope: `11_database` only  
Decision: review and recommendation only; the accepted environment was not
automatically upgraded.

## MySQL 8.4 LTS patch review

- Installed and tested: **MySQL 8.4.8 Community Server**.
- Current official downloadable 8.4.x LTS patch checked on 2026-09-05:
  **8.4.11** for Windows, as shown by the [official MySQL 8.4 download
  page](https://dev.mysql.com/downloads/mysql/8.4.html).
- The [official MySQL 8.4 release notes](https://dev.mysql.com/doc/relnotes/mysql/8.4/en/)
  list later maintenance entries, but a version not present on the download
  page is not treated as released for this review.
- Upgrade recommended: **YES, as a separate maintenance-window upgrade to
  8.4.11; do not modify the existing `MySQL84` Windows service as part of
  Round 1 closure**.
- Round 1 closure status: **not blocked**. 8.4.8 remains a valid LTS baseline
  and all current acceptance evidence was executed against it.

The schema uses ordinary InnoDB tables, `utf8mb4`, foreign keys, checked
`VARCHAR` state fields, JSON metadata, `MEDIUMBLOB` encrypted payloads, and
`DATETIME(6)`. No deprecated or removed behavior was identified in the
Round 1 migration. The 8.4.11 release notes still warrant regression because
maintenance releases include optimizer, JSON, and DDL-validation fixes.

After a future patch upgrade, the following must be run in a fresh isolated
database before accepting the new baseline:

1. `alembic upgrade head` and `alembic check`.
2. `alembic downgrade base`, re-upgrade, and a second `alembic check`.
3. `uv run pytest -q` and the real-MySQL group `uv run pytest -q -m mysql`.
4. A new logical backup plus the complete fresh-restore closure verifier.
5. The official repository Root Contract suite and frozen-contract hash check.

## pyca/cryptography review

- Installed and locked: **cryptography 46.0.7**.
- Current official stable release checked on 2026-09-05: **50.0.1**, shown on
  the [official PyPI project page](https://pypi.org/project/cryptography/).
- Current project constraint: `cryptography>=45,<47`; changing to 50.x would
  require an intentional `pyproject.toml` constraint decision and lockfile
  regeneration. Neither was changed for closure.
- Upgrade recommended: **YES, as a separately reviewed security-maintenance
  change; do not blindly upgrade the accepted Round 1 environment**.

Compatibility assessment:

- The module uses the stable `Fernet` API and a versioned key-provider wrapper;
  it does not depend on X.509, certificate parsing, backend internals, or
  deprecated low-level primitives.
- `MultiFernet` is not the runtime abstraction in this module. The existing
  rotation path decrypts with the recorded key version and re-encrypts with
  the active version. A future 50.x upgrade should probe both Fernet and
  MultiFernet encrypt/decrypt/rotation semantics before changing the provider.
- Python 3.12 is supported by the current project and is listed by the
  current stable package metadata. The accepted environment’s current
  Fernet round-trip, wrong-key, and rotation tests passed on Python 3.12.
- Security/advisory relevance: cryptography is security-sensitive and the
  current 46.0.7 line is not the newest maintained release. Review the
  [pyca changelog](https://github.com/pyca/cryptography/blob/main/CHANGELOG.rst)
  and release advisories during the upgrade; this is a recommendation, not a
  claim that the accepted closure environment is already upgraded.

Required isolated upgrade probe: install the candidate version outside the
accepted `.venv`, run Fernet/MultiFernet compatibility checks, the complete
database test suite, the real-MySQL group, backup/restore closure, Ruff,
Pyright, dependency checks, and the Root Contract suite. Keep the current
lock unchanged until that evidence is reviewed.

## Session timezone review

The low-risk Database-only change was implemented in
`database_layer/config.py`: the current `mysql+aiomysql` engine passes
`init_command = SET time_zone = '+00:00'` at connection creation. The
real-MySQL integration test now asserts `SELECT @@time_zone = '+00:00'`.

This is a non-breaking clarification of the existing UTC `DATETIME(6)`
decision. It does not modify `09_backend`; Backend persistence wiring remains
deferred until stable persistence ports exist.

## Boundaries

This review does not upgrade or restart the existing MySQL service, change
the frozen root contract, add production infrastructure, or admit real
student data.
