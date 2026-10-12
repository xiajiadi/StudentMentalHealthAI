# Synthetic school directory and account configuration

Controller decision:2026-10-12. This extends the authorized four-role synthetic school platform. It does not change frozen assessment contracts, professional publication rights or real-student authorization.

## Data and ownership

- Add nullable display_name(String120) to schools, school_classes and account_school_memberships. Identifiers remain stable. A school-scoped roster name must not be added to psychological Subject records or inferred from global login names.
- New migration20261012_0006 follows0005. Add school_account_batches and school_account_provisions for newly created synthetic student/teacher accounts only. Batch/account provenance is operational, not a measurement approval.
- Batch:batch_ref(unique), school_id, created_by_membership_role_id, optional class_id, row_count(1..100), inherited public identity/timestamps. Scope creator/class through composite school foreign keys; add(id,school_id) uniqueness.
- Provision:school_id, batch_id, account_id(unique), membership_id, membership_role_id, row_no, role_code(student/teacher), status(PENDING_ACTIVATION/ACTIVE), activated_at(nullable). Composite scope FKs for batch/membership/role; account FK; unique(batch_id,row_no). Membership must belong to account, checked transactionally. Public identity/timestamps are inherited.
- Add a specific allowlisted synthetic directory provenance reference for new student subjects/SELF grants if the existing schema requires provenance. Never invent a professional approval or reuse a broad review grant.

## Additive school-admin interfaces

All interfaces require a persisted active same-school synthetic admin context; writes require CSRF. They stay module-local, outside frozen OpenAPI contracts. Requests forbid extra fields.

- GET /api/v1/school/admin/directory returns school{school_ref,display_name}, classes with existing metadata plus display_name, and members{user_id,display_name,role,account_status,provisioning_status}. No password/hash, private subject content, other-school metadata or login credential is returned. Existing student/teacher selection DTOs gain optional display_name only.
- POST /api/v1/school/admin/school/name, /admin/classes/{class_ref}/name and /admin/members/{user_id}/name accept{display_name}. Trim and require1..120 characters; stable refs and existing rows remain unchanged.
- POST /api/v1/school/admin/accounts/preview and /admin/accounts/import accept{class_ref:null|string,rows:[{row_no,login_name,display_name,role}]}. Maximum100 rows; distinct positive row numbers; role exactlystudent/teacher; login_name matches SYNTHETIC_[A-Za-z0-9_]{1,100}. CSV columns are login_name,display_name,role; class selection is separate. Reject unknown/password columns, blank names, malformed/oversized input and case-insensitive duplicates.
- Preview returns{valid,row_count,errors:[{row_no,code}]} and never echoes CSV rows. Global login conflicts use LOGIN_UNAVAILABLE without identifying the conflicting account or school. No preview writes or long-lived preview token.
- Import revalidates all rows and the optional same-school active class inside one transaction. All rows succeed or none do. Require the existing idempotency mechanism with a resource receipt pointing to the batch; replay rechecks scope and reconstructs the same safe batch result. HTTP201 response{batch_ref,created_count,accounts:[{row_no,user_id,display_name,role,status:PENDING_ACTIVATION|ACTIVE}]}; replay reflects current activation state. HTTP409 with a valid invalid-preview envelope means a definite whole-batch rejection and requires another preview; other409 ProblemDetails or network failures retain the same request key for uncertain-result recovery. Positive row numbers need not be contiguous, and one row may have multiple distinct errors.
- GET /api/v1/school/admin/accounts/batches/{batch_ref} returns the same safe result within scope.
- POST /api/v1/school/admin/accounts/{user_id}/activate accepts{new_password}. SecretStr input, strong password validation and Argon2id hashing; never log/echo/persist plaintext or include password in idempotency fingerprints. This operation deliberately uses a one-time state transition, not a password-bearing replay receipt. An already active/non-provisioned account is refused, never silently reset.

## Provisioning and activation

Imported accounts start SUSPENDED, with unusable random credential material hashed using the established password adapter. No generated initial password is returned or delivered. In the same import transaction create school membership/role and, for students, a new synthetic Subject and narrowly scoped SELF grant. No teacher psychological grant is created.

Activation is restricted to a PENDING_ACTIVATION provision in the current school with no other-school membership, matching account/membership/role identity and current active admin. Lock account/provision/target class, hash the submitted password, set account/provision active and optionally insert the batch's typed class-student/class-teacher relation. Use current activation time; refuse an archived/foreign class. Never modify an existing unrelated/shared account's credential. Subsequent real login and school-context selection must work for both new roles.

Audit names/import/activation with an attributed actor, scoped operational resource and existing safe metadata keys(count/state/reason_code/source/schema_version); never put names, login identifiers, CSV rows or secrets into audit metadata. Audit and the business write share a transaction.

## Compatibility and acceptance

Runtime schema requirements remain profile-specific: retain legacy/frozen requirements; advance only school_tenant to0006 after reviewed native migration. Preserve v2 backup restore support for exact0005 and0006 schemas with explicit revision manifests; do not accept arbitrary head. For an old snapshot, restore its trusted original migration/schema first, verify data, then perform a separately recorded additive runtime upgrade before current school services start.

Acceptance includes fresh strict DTO/parser tests, same-school and cross-school denials, transaction rollback/replay/conflict/activation guards, native migration without old-row loss, browser name editing/CSV preview/import/activation, real new-student/new-teacher login and usable assigned workflow. No static UI or suspended account alone proves account configuration complete. Root owns integration, native operations and final review; Workers own disjoint source files and must not touch live databases or secrets.

## Verified synthetic increment,2026-10-12

- Original owned3308 upgraded0005→0006 after sealed backup/readback. All27 pre-existing business tables/668 stored rows retained exactly under their previous columns.0006 snapshot contains30 tables and passes trusted restore preflight/readback; this is not a new0006 native restore demonstration. Restored3309 stays stopped at0005.
- Real HTTP checks passed for directory disclosure, class/member naming, privacy-safe invalid preview, two-account import and resource replay, one-time activation, both new role logins/admin denial, cross-school batch denial, typed class assignments, new-student task visibility and teacher aggregate. Latest safe evidence:external school-directory-qa-c3de946b84794b18ab08f9779227bc6a.json. Original NULL school name was deliberately skipped by that HTTP round-trip; browser subsequently configured it as合成示范学校 A and verified a rename/restore cycle.
- Real MySQL fault-injection check uses only an independent QA adapter instance, raising at audit after import flush. Fresh connection confirms zero accounts/memberships/roles/batches/provisions/receipts/import-audit residuals. Evidence:external school-directory-transaction-qa-796f5339b61f498496d6df11bf156d22.json. No production service method or safety policy was replaced.
- Fresh browser17 stages passed, with Root-inspected masked images at external browser-qa/20261012T063526Z-7454afa16d1346cc90e5d4b7f7b7f603. Earlier run's child succeeded with original-NULL partial status, but wrapper failed on released-variable cleanup; this error and its evidence remain preserved. Cleanup was fixed before the fresh successful run.
- Root:85 DB/backup/restore focused tests,40 Backend directory/idempotency/task/CSRF tests, prior full frontend102 tests and final affected21 tests passed. A stale DOM selector failed after the multi-role ID repair; Root corrected it and added a dual-role shared-name regression, independently rerun21/21. Selected Ruff, lint/typecheck/build and diff checks passed. Evidence is bounded to this synthetic directory increment; professional publication, complete role/CAT/AI product acceptance and deployment remain separate.
