# Task-scoped professional review engineering

Controller decision: 2026-10-12. Synthetic school workflow only; no psychological validity or publication approval is implied.

## First increment

Introduce task-specific specialist assignment and a durable review case bound to one task enrollment and its actual assessment. Keep legacy Safety ReviewCase and its global REVIEWER routes unchanged. This first increment does not publish feedback, expose raw answers, or enable conversation access to professional records.

- School admin may assign an active same-school specialist to a task and revoke that assignment. Admin sees assignment/status metadata only.
- Only the currently assigned, active same-school specialist may list/read/process the task's review cases. Assignment is checked again at each operation, including writes. Teachers and students cannot read professional cases.
- A case requires a completed, task-bound assessment with matching school, enrollment and subject. Standalone assessments are excluded. Enrollment or assignment revocation closes access rather than transferring it implicitly.
- Case lifecycle: OPEN, IN_REVIEW, APPROVED, REJECTED. Decisions require an expected version and CSRF/idempotency; conflicts fail without overwriting an earlier decision. APPROVED describes the synthetic review workflow decision only and never releases a report.
- Notes remain encrypted at rest using the established application encryption facility. Audit/event rows record actor membership role, transition/version and references; they do not copy note plaintext or psychological payloads.
- Additive schema and restrictive foreign keys enforce tenant/task/subject linkage. Downgrade refuses when new business rows exist. Preserve the original demo and old databases; migration/recovery proof runs only in the verified isolated workspace.

## Separate publication gate

Later publication requires a separately versioned feedback entity, approved content scope and explicit release action. L1 completion feedback, L2 professional preapproved personal feedback and L3 human review remain distinct. A review decision or CAT completion cannot substitute for that gate. Existing frozen report contracts are unchanged.

## Acceptance

Prove assigned specialist access and state persistence; reject same-school unassigned specialist, cross-school specialist, teacher, student and admin private-content access. Verify revocation, stale version, repeated key, changed-body conflict, rollback and encrypted storage. Native database/public API/browser verification is required after source-level checks. The evidence below covers the implemented first increment; remaining checks are stated separately.

## Engineering checkpoint, 2026-10-12

- Additive0007 migration preserved29 existing business tables/1116 stored rows; native runtime gate and current-user sealed33-table backup readback passed.0005/0006 restore manifests remain exact. Original and old databases were not reset.
- Root native API proof: `professional-review-api-b8e207cf5d4f41e39a15ed8175ae2854.json` in the external owned workspace logs. Real CAT completion, incomplete-case denial, role/tenant/CSRF denial, concurrent expected-version conflict, stable-key replay and revocation denial passed.
- Read-only storage proof: `professional-review-storage-b27bb3294dea4aa59a75b4ad3a72c92f.json`. Known synthetic note absent from ciphertext and audit; three exact actor/version transitions and metadata-only detail-read audit present. HTTP decrypted-note roundtrip covered separately. No raw stored content is printed.
- Metadata proof: `professional-review-metadata-b513bd997a6a4c4c96b878eef55cf0f0.json`. Admin same-school picker excludes the other school; other roles denied. Revoked task excluded from specialist list and eligible-record access denied.
- Browser: `browser-qa/20261012T131806Z-c0d5fd90fb104564b889ecab6b5c9cdf` under the external owned workspace.24 stages passed, including actual UI writes, persisted note reload, administrator revoke and specialist cache removal; Root inspected three masked screenshots. Native setup completed a genuine synthetic CAT before UI case creation. No fake responses or interceptions.
- Fresh checks: Backend381, Frontend137, DB schema13, deployment backup/restore/runtime70, harness Python12/Node5; build/lint passed. Source-only independent review corroborated migration guard and privilege/DTO boundaries.

Controller status: PARTIAL_PASS for this bounded increment. Native audit-failure injection/rollback,0007 new-isolated-target restore/restart and separate feedback publication remain outstanding. Review state APPROVED is not psychological validity or publication approval. Earlier failed harness runs remain retained. The screenshot helper's subsequent scroll-to-top adjustment awaits its next native run.

## Native rollback and restoration follow-up

The previously pending audit-failure rollback was tested in an isolated QA Python process against the owned synthetic database, without patching the live server. Failure was injected after the audit append/flush. Case/event/receipt/audit projections matched exactly after failed creation; case ciphertext/status/version and all four categories matched after failed decision. Evidence: original external logs/professional-review-rollback-f384355be0484f67947906fefedd081e.json.

A new0007 restore on3310 imported32 business tables/1371 stored-value-verified rows, revoked2 archived sessions and read107 encrypted fields. The restored API subsequently recovered the actual encrypted workflow note with its status/version intact, denied other roles/tenant, and denied access after target-local assignment revocation. After graceful target-only shutdown and resume, all32 business-table projections/1444 current rows remained identical. Fresh restored Backend/Frontend and four-role browser4/4 passed; see SCHOOL_RECOVERY.md for artifacts and environment limits.

These follow-up checks close the first increment's rollback and0007 restore/restart evidence gaps. Separate feedback publication, complete professional content/item-bank governance, professional validity and full-project delivery remain open. Controller records ENGINEERING_PASS only for this bounded synthetic task-review workflow; overall goal remains active and not ENGINEERING_DEMO_READY.
