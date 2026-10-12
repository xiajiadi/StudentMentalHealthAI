# School synthetic CAT assets and versions

Controller direction, 2026-10-12. Base4405bd32. This implements the next part of
the full CAT management requirement; immutable version storage alone does not
complete task-bound execution, publication or the overall delivery mandate.

## Product and authorization

An active school psychological specialist can create a school synthetic bank,
edit items in a working form and save a new immutable version, inspect previous
versions, and create/version a CAT plan referencing an exact bank version.
Student, teacher and administrator accounts cannot access the asset content.
Every operation resolves the persisted school context/role in Backend. All writes
require CSRF and a stable idempotency key. Cross-school public IDs return404.
Only synthetic engineering content is supported; no clinical/psychometric claims.

## Increment and compatibility

Store bank items as one encrypted, schema-validated version document using the
existing application encryption. A separate item table is unnecessary for this
bounded immutable document model: individual item edits create a new version.
Never update a saved payload or reuse a version number. Bank/plan metadata can be
renamed or archived using expected_revision; prior versions remain readable.
No physical delete or cascading removal. Current published JSON fixtures and
existing assessment.v1 sessions remain unchanged.

Additive0008 provides four tables, with resource identity/timestamps conventions:

- SchoolCatItemBank / school_cat_item_banks: school_id, display_name(120),
  status ACTIVE|ARCHIVED, revision>=1, creator_membership_role_id.
- SchoolCatItemBankVersion / school_cat_item_bank_versions: school_id, bank_id,
  version_number>=1, creator_membership_role_id, item_count, dimension_count,
  payload_ciphertext, cipher_format_version, key_version, payload_schema_version.
- SchoolCatPlan / school_cat_plans: school_id, display_name(120),
  status ACTIVE|ARCHIVED, revision>=1, creator_membership_role_id.
- SchoolCatPlanVersion / school_cat_plan_versions: school_id, plan_id,
  version_number>=1, bank_version_id, creator_membership_role_id,
  payload_ciphertext, cipher_format_version, key_version, payload_schema_version.

Unique(id,school_id) and same-school composite FKs for parents, exact referenced
bank version and creator membership role; unique(parent_id,version_number).
ON DELETE RESTRICT. Version allocation locks the parent row, checks expected_revision
and increments it atomically; an archived parent cannot accept versions. Content
and parameter payloads never appear in audit or generic list DTOs. Existing audit,
idempotency and encryption helpers are reused, with fresh scope checks on replay.
Schema/backup/restore supports exact0005/0006/0007 manifests plus0008 without
assuming new tables existed in old snapshots. Root owns runtime gates/native DDL.

## Interface contract

Prefix /api/v1/school/cat-assets, hidden from the frozen OpenAPI. IDs use
CBANK_, CBVER_, CPLAN_, CPVER_ opaque refs. Strict extra-forbid DTOs.

GET /template: current real synthetic bank/config document for specialist editing.
GET /banks?limit=30&skip=0: metadata rows only.
POST /banks: {display_name, bank_document}; creates identity and version1.
GET /banks/{bank_ref}: metadata plus ordered version metadata.
PATCH /banks/{bank_ref}: {expected_revision, display_name?, status?}.
POST /banks/{bank_ref}/versions: {expected_revision, bank_document}.
GET /bank-versions/{version_ref}: metadata plus decrypted bank_document.
GET /plans?limit=30&skip=0: metadata rows only.
POST /plans: {display_name, bank_version_ref, config_document}.
GET /plans/{plan_ref}: metadata plus ordered version metadata.
PATCH /plans/{plan_ref}: {expected_revision, display_name?, status?}.
POST /plans/{plan_ref}/versions:
  {expected_revision, bank_version_ref, config_document}.
GET /plan-versions/{version_ref}: metadata, bank_version_ref, config_document.

Top-level responses include engineering_only:true and
psychological_interpretation_allowed:false. List payload {items,has_more}; metadata
bank/plan {bank_ref|plan_ref,display_name,status,revision,created_at,updated_at}.
Version metadata {version_ref,version_number,created_at}; bank versions additionally
item_count/dimension_count. Create/version returns parent detail plus version_ref.
Mutation stale_revision/key-content conflict409; unknown/scope404; role403;
schema/structural invalid422; real validator unavailable502/504. No fake success.

Internal CAT management GET /template and POST /validate-assets accept/return the
actual domain document. Validate synthetic flags, field bounds, finite parameters,
unique IDs, option/scoring alignment and config/item-count compatibility using
existing ItemBank/Item/CATConfig code plus strict input shape. Payload<=256KiB,
items<=100, dimension1 for the current GRM provider; seed is a strict integer.
Return only validated documents/counts; no online sessions or files changed.
Backend checks role before and after validation; no DB transaction spans network.
Documents are immutable once stored; structure validation is not professional approval.

## Required evidence and following increment

Source/DTO/schema tests; native additive migration with old-row preservation;
real CRUD, encrypted version readback, immutable history, expected_revision race,
idempotency/revocation/school/role/CSRF failures and audit rollback; browser item
edit/save and plan version/history desktop/mobile;0008 backup/restore evidence.

Following work must implement reproducible simulation of an exact saved version,
controlled synthetic engineering activation, task/session version FKs and runtime
loading keyed by immutable school+version identity. Pending drafts never enter
student sessions automatically. Existing frozen fixture remains a compatible
path; synthetic activation does not confer professional or student-report approval.

## Root verification — 2026-10-13 Beijing

- Additive0008 applied to the original owned3308 workspace after stopping its
  verified Backend handle and sealing/readback-verifying the0007 snapshot.
  All32 pre-existing business tables/1494 stored rows matched exactly after DDL;
  four new tables were empty. External cat-assets-migration-
  514e9e548a514729ae0efd77c22b09fd.json records the proof and backup path.
- Native public CRUD proof passes role/CSRF checks, true201 create/replay,
  key-content conflict, version history/readback, concurrent200/409, exact plan
  binding, cross-school404, rename/archive and pre-validation archive/stale/scope
  rejection. Original logs/cat-assets-http-bfc8f42780d249d6a3a1f46f08432df3.json.
- Real browser27 stages pass after fixing the absent optional Boolean prop:
  Vue cast active tofalse, while tests passed active:true. The default nowtrue
  and absent/explicit-false regressions cover the actual parent mount. Latest
  desktop/mobile screenshots inspected at browser-qa/
  20261012T164021Z-82cd4907f40247de8e44300476f1a7b9. Item/plan edits, exact binding,
  versions and reload match actual API; changed Chinese copy reviewed with
  Humanizer-zh, keeping synthetic and professional boundaries.
- Native process-local audit failure after append/flush proves bank creation,
  bank version and plan version rollback. Exact projections of four asset tables,
  idempotency and audit remain unchanged; encrypted payload checks pass. Live
  Backend was never patched. logs/cat-assets-transaction-qa-
  421e470775014840ab8be0add950e24a.json. Earlier harness failures are retained:
  API does not expose context_id; DAO role/school matching resolves it; an invalid
  reparse-helper argument masked that failure; repeated successful validation
  legitimately added audits between fault snapshots. Corrected harness validates
  before all fault snapshots and preserves original errors on evidence-write failure.
-0008 sealed backup restored into new isolated targetD
  D:\Projects\.StudentMentalHealthAI-school-restore-20261013-d on3312:
  36 business tables/1651 stored-value-verified rows,3 imported sessions revoked,
  127 encrypted fields readable. Current runtime preflight passed; target apps,
  browser and shutdown/restart are not yet checked. External cat-assets-restore-
  5836c6006a624356942d285464caf545.json; snapshot remains a point-in-time copy.
- Fresh Root checks: Backend413, CAT49, Frontend184 plus full lint/build,
  DB schema15, selected deployment154; new rollback harness fake11. Scoped Ruff
  passes. Older fixed0007 runtime fixtures were updated to current revision while
  retaining explicit old-revision rejection. Initial201 override, pre-validation
  ordering, plan-ref DTO breadth and latest-version order defects are repaired.
- Current original owned Backend exec86252/PID44360 on8088, CAT exec91295/
  PID50324 on8180, Frontend exec90451/PID36496 on4178. Fresh manifest/listener/
  runtime checks pass; exact ownership and history stay external. Do not treat
  historical IDs or restored targets'0007 revisions as current source compatibility.

This slice is ENGINEERING_PASS for synthetic asset editing/versioning. Exact
saved-version simulation, controlled activation/task/runtime binding, student
publication, grounded university support and full install/recovery acceptance
remain required before ENGINEERING_DEMO_READY.
