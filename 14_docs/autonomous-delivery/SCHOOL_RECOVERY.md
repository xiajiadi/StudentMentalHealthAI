# Synthetic school recovery boundary

Decision: Controller, 2026-10-12. Scope: local synthetic engineering; existing school workspace and databases must remain intact.

## Backup

The original v1 snapshot contains database rows but omits the application encryption-key container. It is a verified sealed snapshot, not a self-contained recoverable installation. Preserve all original files.

The v2 package shall include the original CurrentUser DPAPI application-key container as sealed bytes inside the sealed backup envelope. Do not decrypt application payloads or serialize plaintext application keys, runtime/root passwords, CSRF secrets or session cookies into the package. Restore is limited to the Windows user able to unseal these containers; cross-user or portable restore is unsupported.

Validate version, project, synthetic scope, supported schema revision, source identity, table/column identifiers, row widths and typed values before target creation. Reject unknown tags, malformed Base64 and nonfinite numeric values. Snapshot DDL is evidence only and must never be executed by the importer.

## Restore target and ordering

Only a previously nonexistent external workspace/datadir and a free loopback port may become a restore target. Reject source/target overlap, existing content, reparse points and foreign process ownership. Never DROP, reset, truncate or overwrite an existing schema. Failure preserves the new target and a non-sensitive phase marker for inspection.

Use trusted repository migrations to build the snapshot's explicitly supported revision (0005 through0024; see `13_deployment/school_schema.py`). Match its exact table/column manifest before importing; upgrade to the current runtime revision only after old-layout import succeeds. MySQL DDL is not transactional, so a failed migration cannot be described as rolled back. Keep foreign-key checks enabled and use the reviewed parent-first dependency order, including composite constraints. Import data transactionally and verify stored values and references before publishing readiness.

Restore the original sealed application-key container exclusively to the new private target. Generate new target database/runtime identities and CSRF configuration; never reuse source administrative credentials. Revoke all imported authentication sessions in the target and require fresh login. This is a deliberate recovery transformation; record it in the recovery summary without changing the source snapshot.

## Evidence and current limits

### Current0024 recovery

The independent AI target restored the final Z0023 snapshot and upgraded to0024.
Fresh verification decrypted1558 stored encrypted cells with zero claimable jobs;
four-role browser checks and later native role workflows ran on this target.
Separately, the AH0024 backup restored into AK0024 and retained the independent
education candidate/review ciphertexts, publication receipt and withdrawn event
history. The reviewed payloads matched after RAM-only decryption. AK was not
started for a browser check; its restore status remains
`DATA_KEYS_RUNTIME_VERIFIED_REQUIRES_BROWSER`.

Evidence: external `psynova-independent-restore-ai-20261016-r1/`
`fresh-ciphertext-verification.json` and
`psynova-ah-release-review-metadata-20261016-r1/`
`ah-ak-restore-review-crossproof.json`. These verify same-Windows-user recovery;
they do not establish cross-user key portability or automatic OS-reboot recovery.

### Current0023 recovery and review-only startup

CurrentUser recovery now preserves the800-case research cohort,6400 answers,
input/output review receipts and encrypted candidate/feedback state. The fresh
AC restore verified63 tables/43482 rows/1126 encrypted fields,then ran the
candidate-review and rewritten-feedback publish/SELF-read/deny/revoke workflow.
Exact source pins,API/database/browser artifacts and limits are indexed in
`CURRENT_STATE.md`;this is bounded engineering evidence,not global readiness.

For a review-only restored application,keep the draft configuration enabled and
pass `--disable-research-general-education-draft-worker` to the official lifecycle
`start` command. This keeps candidate/output-review APIs available without
claiming queued jobs. Confirm the actual Backend dependency reports `DISABLED`;
input-review continuation is a separate flag. Old manifests retain normal worker
enablement. The switch does not change draft-file hashes or grant publication
permission. Stopping the application preserves MySQL and pending queue rows.

### Current0010 feedback recovery evidence

After explicit CPU-only resume, Root restored original0010 sealed backup into new
F3314:41 business tables/3851 exact stored-value rows,8 revoked imported sessions,
230 readable encrypted fields. Actual published feedback read matches ciphertext;
revoked feedback remains hidden and role denials hold. Fresh assignment/SELF
revocation checks and12-stage publish/read/revoke browser evidence pass. F was
then gracefully stopped and resumed, preserving41 tables/3940 current rows exactly;
post-restart feedback read/denial checks pass. CURRENT_STATE.md indexes artifacts.
This proves bounded CurrentUser0010 feedback recovery and authorization. It does
not establish portable install, OS reboot, complete role matrix or grounded AI.
One initial external browser selection failure is retained with unresolved exact
cause; subsequent metadata-instrumented run passes without a product change.

### Current0009 recovery evidence

New isolated targetE (`.StudentMentalHealthAI-school-restore-20261013-e`,3313)
imports39 business tables/2905 rows, revokes8 imported sessions and verifies190
encrypted fields. After browser activity, its guarded SQL shutdown and actual
resume preserve all39 tables/2937 current rows; new guardian identity and unchanged
original guardian are verified. No old restore target was reset.

Current Backend8089/Frontend4179 use a dedicated CPU CAT8181 selected by the
validated `--cat-port`; the original8180 registry is separate. A restored saved
session resumes its one persisted response, keeps the exact immutable bank/config
and binding, saves the two remaining responses and completes with teacher
aggregate-only proof. The original8180 session count is unchanged; this is not
an exhaustive comparison of original in-memory state.

Fresh restored four-role browser checks pass at targetE
`browser-qa/20261012T211504Z-3f5227cd583d4e87baef54e881066f1f` with actual
`school-restore-browser-qa.json` and masked screenshots. History rows are checked
against the returned metadata in order, including status, count and date/null
labels. Duplicate account slots and malformed diagnostic fields fail closed.
Root source checks98 Python/3 Node pass. Earlier failed checks remain historical
evidence; they are not relabeled as successful runs.

Target evidence: `restart-checkpoint.json` and
`restored-saved-cat-qa-b438cb5aad4d4ab7ba6bb86b21a5ad9b.json`. A new target-local
backup is sealed/readback verified at
`backups/20261012-211143-d83ea271c4294531b1356f76758bba17.private.dpapi`.
This establishes local current-user restore/restart and bounded business proof.
Cross-user DPAPI portability, OS reboot, the final installer, full university AI
grounding and controlled L2/L3 publication remain unverified.

The following earlier milestone records retain their original evidence scope.

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
