# Current autonomous delivery state

Updated: 2026-10-11. Phase I continues; final delivery is not accepted.

## Objective and authority

Continue the synthetic four-role PsyNova engineering mission to evidenced ENGINEERING_DEMO_READY. The original application is historical product background; current mandate, frozen contracts and Controller decisions govern implementation. Do not use real students, assert professional approval, reset old data, bypass Safety/Claim Boundary, contact people automatically or introduce cloud model fallback.

## Git and ownership

- Worktree: `D:\Projects\StudentMentalHealthAI-m0-integration`.
- Baseline M0: `74372fef547ea6d0eba0e88fd5dd44750d7f1f8e`.
- Dedicated integration/remote branch: `xiajiadi/autonomous-delivery-20261011`; reviewed seed/runtime/teacher increment `1252425`, frontend context increment `a761641`, operator-supplied AGENTS and 0005 DB source increment `4085df5`. Push only to this dedicated branch.
- Earlier reviewed commits: runner/audit `2f29f5e`, student completion/original covers `2d69368`, isolated-workspace guard `2ba26b6`, school auth `4c730a2`, runtime/DPAPI `9390442`, school entrypoint `b6e6bea`.
- Preserve untracked `10_frontend/output/` and `10_frontend/public/assets/heartbridge/login-mark-v2.png`; never stage/reset/delete them.
- Governance V4 follows the user's explicit two-level decision: UI-selected Root owns direction, design, architecture, decomposition, integration and final review; Root directly dispatches Luna/high Workers. Former Lead has ended dispatch and handed off the isolated 0005 checkpoint. Direct `school_task_db_review` Worker now reviews that checkpoint read-only. Confirm live inventory before reassigning files.

## Runtime and data boundaries

- System MySQL 3306 is untouched. Preserved M0 MySQL 3307 and historical M0 services were recovered without reset/migration; never restart new-schema source against that database. Existing legacy launcher now blocks before bootstrap when 0003 exists.
- New owned external workspace: `D:\Projects\.StudentMentalHealthAI-school-workspace-20261011`; loopback MySQL 3308, `smhai_school_demo`. Current-user-only directory DACL; randomly generated database/auth/encryption settings sealed with Windows current-user DPAPI. No plaintext secret configuration or password argv.
- New demo and separate owned test schemas are at additive revision 0004; Alembic consistency checks pass. Native MySQL integration passes 7/7. Test-schema downgrade/re-upgrade passes; demo downgrade with registered seed rows is rejected before DDL. Old schemas were not migrated.
- Runtime identity has exactly demo-schema SELECT/INSERT/UPDATE/DELETE, no active roles or grant option. Actual login/grant/revision checks pass. Initialization/runtime settings required explicit recovery; clean repeated install is unproven. Failed new-account verification now locks that account and withholds runtime readiness.
- Registered seed provisions two synthetic schools, two subjects and eight random-password role accounts. Exact repeat preserves sealed credentials and verifies existing rows. Specialist/admin have zero subject grants. Generated credentials stay in current-user DPAPI storage.
- School backend serves 8088; HTTP health passes with four REAL_HTTP module clients. Frontend serves 4178. Native login/context/CSRF/logout checks pass for all eight accounts, with distinct `psynova_school_session` cookie and seven private-record masked denials. Real Chromium login/context/role route/forbidden route/teacher API/logout/blank restore checks pass for all four alpha roles. This proves authentication, not all remaining business operations.
- External `school-processes.json` records native creation times and process tree: backend interpreter 34364 (exec session 89598), frontend 47260 (exec session 25584). Reverify identities before process actions; numeric PIDs alone are insufficient. Shared M0 module processes are not owned by that manifest.
- Backend was explicitly restarted after exact owned-process verification to load 0004, CSRF and cookie separation. Further source changes require another verified reload.

## Reviewed implementation and fresh evidence

- School memberships/roles, CSRF-protected active context, tenant-scoped grants, revocation/invalid-context denial, concurrent context re-projection and revision gate are integrated. School profile has no legacy seed and no implicit admin psychological access.
- DPAPI key provider consumes sealed format without plaintext fallback; actual workspace Fernet roundtrip passes. School CSRF uses a sealed random 32-byte key, SecretStr config and in-memory adapter injection; invalid values redact secrets and unrelated errors remain specific.
- Integration focused backend 37/37 passes after CSRF integration. Lead's broader isolated backend checks and quality review are separate evidence. DPAPI integration crypto 9/9 and adapter 12/12 pass.
- Deployment tests 54/54 pass; fresh combined deployment/teacher/seed suite passes 72/72 after explicitly adding the existing database environment to PYTHONPATH. An initial run without SQLAlchemy failed at import and is not pass evidence. Runtime/entrypoint check actual ownership, DACL, grants, revision, readiness and sealed target. Configuration preflight is not HTTP workflow proof.
- Frontend 14 files/55 unit tests, Lint and typechecked build pass. Single authorized school context is explicitly activated; multiple contexts require authenticated server-provided selection. Independent Lead review and focused tests pass 12/12. Student completion persists pending answer and honors the updated server gate. Assessment art is 28 unique reproducible original SVGs; card brand marks are removed. Static inspection does not prove authenticated workflows.
- Native school student completed eight synthetic CAT responses through the server-authorized completion gate. Results/answers were not printed. Fresh support request returned 502; stored allowlisted diagnostics confirm CONTENT_VALIDATION succeeded and CLAIM_BOUNDARY rejected the candidate. Runtime used one CONSUMER_GPU attempt with qwen2.5-0.5b-engineering, no retry/fallback. Do not weaken the boundary or reopen the accepted GPU line. Exact rejected claim remains uninspected.
- Baseline CAT 28, Runtime 33, Safety 15, selected pipeline 12 and focused backend 7 are historical/fake-suite evidence; no psychometric/model-runtime acceptance. RAG baseline export fixture is still missing. One actual legacy synthetic support request returned 502/dependency_invalid_response; exact fresh failure stage remains unproven.

## Active next increment

Seed/provenance/0004 and frontend context changes are committed as the increments above. Seed username/password bounds now match HTTP login. 0003 stays immutable. Specialist case/publication assignment requires its own subsequent workflow; never misuse internal NULL-scoped REVIEW_ASSIGNMENT.

Teacher school/unknown overview now skips both assessment and report repositories, returns empty compatibility fields and task_progress_available=false; per-subject history is denied before repository access. Independent source/sentinel review passes; Root focused teacher/tenant tests pass 11/11 and native checks pass for both school teachers after reload. Real task progress remains unavailable. School/class/task design will use publication-time enrollment snapshots; revoked students lose access immediately, historical enrollment totals remain with active/revoked counts separated. Preserve separate self-initiated assessments outside task counts. No privacy threshold or psychological rule is invented. Lead/Worker now own only the next additive 0005 DB models/repository transaction increment in their isolated worktree.

DB checkpoint `8acea881` and direct Worker repair `453e2c0a` are integrated as source in `4085df5`: classes, typed student/teacher links, publication snapshots and enrollment/session persistence with additive 0005. Direct review found missing task windows and standalone-session rebinding; both were repaired. Root fresh non-MySQL DB suite passes 61/61 (7 native tests deselected). Owned schemas and running backend remain at 0004; 0005 native migration, actual transaction/race tests and task API integration are still pending. Do not restart new source against 0004 before synchronizing gates/schema.

Browser harness uses in-memory stdin credentials, isolated Chromium contexts, masked post-login screenshots and sanitized output; it never exports storage state or records traces. Root run passed 4/4 roles at `D:\Projects\.StudentMentalHealthAI-school-workspace-20261011\browser-qa\20261011T131858Z-056830cb1b774849af66725327681bf2`. Initial missing C-drive browser cache and ADMIN/frontend SCHOOL_ADMIN expectation mismatch were diagnosed; D-drive cache and exact API role mapping are now used. Earlier partial evidence remains preserved. Next priorities remain task APIs/role operations, specialist case/publication workflow, independent AI conversations, original assets and safe support failure resolution.

## Continuation and remaining gates

Runner is a lease/checkpoint/recovery state CLI, not a coding executor. Its current root lease/checkpoint is stored in ignored `.autonomous/`. Heartbeat `psynova` is configured ACTIVE/90 minutes; first actual scheduled trigger, unattended/reboot continuation and sustained operation remain unproven. Do not mark the whole mission complete at a checkpoint.

Other homepage/Heartbridge/brand assets still require per-file provenance or compatible original replacement. Final packaging, least-privilege installer recovery/portability, full E2E, professional review and real pilot/production permissions remain open. Synthetic engineering continues.
