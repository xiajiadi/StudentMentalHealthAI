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

## Native recovery evidence

Root restored the v2 artifact into the previously nonexistent external target D:\Projects\.StudentMentalHealthAI-school-restore-20261012-a on loopback3309. Source3308 was retained. Trusted migrations reached0005;27 business tables and668 rows were imported in a transaction and compared by stored-value readback. The2 previously unrevoked sessions were revoked in the target. All55 non-null encrypted fields were decoded successfully in memory using the restored sealed key container; no plaintext field or key was logged or exported. The initializer's unused generated key container is preserved separately in the new target.

Runtime provisioning validated a new schema-scoped identity. Restored backend8089 and frontend4179 then passed the four-role browser authentication/route/authorization/logout checks, including student metadata history and feedback navigation. Evidence folder: browser-qa/20261012T025829Z-7cd8f5744c724a66b81280e2c3a7c23c in the restored target. Root inspected student/admin screenshots. Original-source preflight still passed. An earlier browser run failed before Chromium launch because its cache path was unset; that run remains preserved. Existing D:\Dev\caches\ms-playwright was supplied explicitly without download or global changes.

Focused restore/initializer/backend-port/browser-wrapper tests:76 passed; selected Ruff and diff checks passed. The initializer now checks raw target/vendor reparse paths, overlap, exclusive loopback port availability, guardian creation/exact argv/listener ownership and connected datadir before schema creation. MySQL's expired temporary password requires a first ALTER USER after process-ownership verification; datadir SQL verification immediately follows that rotation. Failed targets retain metadata and any live guardian; no numeric-PID taskkill cleanup remains.

This establishes one local CurrentUser synthetic restoration and representative restored-user access. It does not establish portable/cross-user installation, reboot recovery, every restored school-task interaction, presentation of an old pre-backup cookie to prove its revocation, professional approval, AI readiness or full project acceptance. Database evidence proves old session rows are revoked; fresh login/logout checks prove the restored account credentials work. Keep those claims distinct.

## Repeatable entrypoints

Use11_database/.venv/Scripts/python.exe with13_deployment/restore_school_workspace.py and explicit --backup, --source, --target, --mysql-bin and --port arguments. Target must be a new sibling workspace and port must differ from the source. A previously created target is refused; failure is an inspection checkpoint, never permission to reset it. Credentials are read through DPAPI in the dedicated Python process and never passed in argv.

school_backend.py accepts validated --port and --frontend-port arguments, with unchanged8088/4178 defaults and fixed loopback/module endpoints. The reviewed restoration browser profile uses8089/4179 only; run school_restore_browser_qa.py --browser-cache D:\Dev\caches\ms-playwright after launching the real frontend with VITE_API_MODE=real and VITE_API_BASE_URL=http://127.0.0.1:8089. Browser credentials remain in stdin/in-memory payloads, output is sanitized, and traces/storage-state files are not created.

## Revision0007 and repeated native recovery

A new targetB at D:\Projects\.StudentMentalHealthAI-school-restore-20261012-b /3310 restored the0007 backup20261012-132402-345df3c11d1f4e53b17c943d337f9a74.private.dpapi. Importer verified32 business tables/1371 rows by stored values, revoked2 archived sessions and validated107 non-null ciphertexts with the restored sealed keys. Current schema/runtime gate is0007. Original3308, old3306/3307 and preserved targetA were not reset.

The professional note API readback passed on restored8089 before and after target-only restart, including version/status, role/tenant denials and assignment revocation. Evidence in original external logs: professional-review-restored-api-7e5886e5b1964c66bacefe65e8113aea.json. TargetB restart-checkpoint.json records normal SHUTDOWN, actual resume STARTED, new exact guardian identity and equality of all32 business-table projections/1444 then-current rows. Root used the target initializer's sealed root credential only for shutdown; the limited application identity still has no global lifecycle privilege. The initial restricted-identity shutdown error did not change the database.

The restore resume entrypoint requires explicit --restore-mode --workspace <target> --port <port>. It binds the restored target to the registered original source and verified restore-state, checks ACL/reparse/datadir/argv/creation/listener identity, starts existing data without initialize/migration/reseed and validates runtime grants/revision. Repeated native invocation then returned ALREADY_RUNNING.

Fresh targetB Backend exec66648 and Frontend exec72482 use8089/4179. The browser wrapper accepts explicit --target and --database-port while restricting applications to8089/4179; it validates target restore-processes.json against live CIM identities and listeners before opening source credentials. Use the Database venv for restore/resume/browser wrappers and the Backend venv for school_backend.py; dependency scopes differ. Current post-restart browser artifact: targetB browser-qa/20261012T135933Z-dfc0b1b2a87b4397936292d274b407a6, four roles4/4, no fake responses. Student technical-ID overflow was fixed using a neutral missing-name label without changing carousel assets/layout. The runner asserts that greeting before masked capture.

Historical snapshot compatibility was independently exercised: targetC D:\Projects\.StudentMentalHealthAI-school-restore-20261012-c /3311 restored0005 (27 business tables/668 rows/55 readable encrypted fields) and then upgraded additively to0007; current runtime preflight passed. Ciphertext verification now selects only the trusted imported revision's table/column manifest before upgrade, rather than querying new ORM tables absent from old snapshots. Fake tests cover0005/0006/0007 and unknown-version refusal; current007 and old005 native paths both passed. TargetC data is preserved, with no browser/application proof claimed for it.

Scope remains local Windows CurrentUser synthetic recovery. This does not prove an OS reboot, cross-user/machine portability, a packaged installer, all restored business/AI paths or imported-cookie HTTP replay. No professional or production approval is implied. Focused deployment checks162 passed; subsequent CAT management source is a separate unfinished increment.
