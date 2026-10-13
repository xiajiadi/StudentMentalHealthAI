# Research CAT persistence slice

Date: 2026-10-14. Status: `IMPLEMENTED SCHEMA SLICE / REVIEW REQUESTED`.
Source branch: `xiajiadi/autonomous-delivery-20261011`.
Source HEAD inspected: `7f0961e5657d843229a03d0b496a02ee4ac9f513`.

This document records the persistence boundary for a school-scoped,
research-purpose CAT lane. The additive ORM/migration and ordinary-start guard
are implemented. Additive DDL has run in NEW isolated J3318 after populated
I0011 backup restoration; native strict current-schema verification passed.
One exact pinned NHANES v2 profile was then stored encrypted as PENDING /
CANDIDATE_RESEARCH_ONLY; no profile was enabled. Native decrypt recovered the
original UTF-8 bytes and SHA exactly. Duplicate version, wrong registry hash
and cross-school loads were denied with UOW rollback. Evidence:
J/logs/native-research-profile-764252fe8e9b4bc0b567fca432ae1f48.json.
This directly tests repository persistence, not the missing authenticated API.
The encrypted repository slice is implemented with ten focused tests and an
independent follow-up review of strict flags and consistent lock ordering;
Backend research routes and actor authorization are not yet implemented.
The public SAPA/IPIP profile remains
research-only and not approved for operational use or psychological
interpretation. School identities remain synthetic. Response origin is exactly
`PUBLIC_OBSERVED` or `MODEL_GENERATED`; public responses are never represented
as answers from the synthetic account holder. No source participant identifiers,
demographics, theta, or scores belong in this slice.

## Decision for Controller

Use existing `MeasurementTask`, `TaskEnrollment`, school/subject grants,
class roster, membership checks, `SqlAlchemyUnitOfWork`, its encryption provider,
audit and idempotency stores. Add `RESEARCH_PROFILE` as an additive value to
`measurement_tasks.cat_binding_mode` only. Keep
`assessment_sessions.cat_binding_mode` unchanged at `FIXTURE` / `SAVED_VERSION`.
Persist research CAT sessions in a separate table and call the existing
in-memory `ResearchCATSession` adapter through a dedicated research route.
Keep the existing `FIXTURE` server default and do not rewrite existing task
rows.

This lets ordinary CAT code fail closed on a research task before an
`AssessmentSession` is created. A task-mode value is a routing marker; it does
not mean a research profile or task is published, professionally reviewed, or
valid for the task's population.

Do not write a research estimate to `AssessmentResult`, create an
`AssessmentSession`, create a `SchoolProfessionalReviewCase`, or insert into
`SchoolPostAssessmentJob`. The latter three schemas require a normal assessment
session. They are not safe containers for a research-only session. Durable
research work and held-candidate review are a later slice with their own
research-scoped tables and gates.

## Implemented schema fields

All three new tables use the project's `ResourceIdentityMixin` identity fields
(`id BIGINT UNSIGNED`, `public_id`, `created_at`, `updated_at`), InnoDB,
`utf8mb4_0900_ai_ci` table options, explicit indexes, named constraints, and
`ON DELETE RESTRICT`. Relational ID columns that reference existing keys must
use the exact referenced type and sign (`BIGINT UNSIGNED`). Opaque refs and
hash strings use the existing ASCII-binary ID convention.

### `school_research_profile_versions`

One immutable item/parameter payload per school, profile reference, and
version. The current schema does not use a trigger to prevent payload updates;
the future research repository must reject content mutation and verify the
payload hash against an independently trusted profile registry. Only execution
eligibility may transition through that repository; changed content, source
mapping, model parameters, or license evidence requires a new version.

| Required columns | Purpose |
|---|---|
| `school_id`, `profile_ref`, `version_number` | Tenant scope and immutable logical version. |
| `dimension`, `instrument_id`, `source_population_scope` | Safe provenance projection; the full source population wording stays inside encrypted provenance. |
| `profile_sha256`, `manifest_sha256`, `fit_sha256`, `calibration_sha256` | Exact profile and source/fit hashes. Validate lowercase SHA-256 before insert and after decrypt. For `profile_sha256`, retain the exact original UTF-8 JSON bytes in the encrypted envelope (for example, base64 bytes plus encoding metadata) and hash those bytes; do not reserialize parsed JSON and claim it matches the source file hash. |
| `rights_status`, `execution_status` | Keep source-rights review separate from execution eligibility. `rights_status` is `PENDING`, `VERIFIED`, or `REVOKED`; `execution_status` is `CANDIDATE_RESEARCH_ONLY`, `SIMULATION_ENABLED`, or `DISABLED`. No `APPROVED` or `PUBLISHED` state. |
| `research_only`, `human_curated`, `psychological_interpretation_allowed`, `publication_status` | Database checks pin these respectively to `1`, `0`, `0`, and `not_approved_for_publication_or_operational_use`. |
| `payload_ciphertext MEDIUMBLOB`, `cipher_format_version`, `key_version`, `payload_schema_version` | Encrypted wrapper containing exact original profile JSON bytes plus parse/encoding metadata: item text, category/key mapping, parameters, rights and provenance. Verify the inner original bytes against `profile_sha256` after decrypt. |
| `created_by_membership_role_id`, `status_changed_by_membership_role_id`, `simulation_enabled_at`, `rights_revoked_at`, `disabled_at` | Scoped operator provenance and timestamps for import/enable/revoke/disable actions. |

Required constraints:

- `PRIMARY KEY(id)` and unique `public_id`.
- `UNIQUE(school_id, profile_ref, version_number)`.
- An exact-scope unique key for downstream FKs:
  `UNIQUE(id, school_id, profile_ref, version_number, profile_sha256)`.
- `FOREIGN KEY(school_id) REFERENCES schools(id)`.
- Both creator-role references use
  `FOREIGN KEY(membership_role_id, school_id) REFERENCES
  membership_roles(id, school_id)`.
- Checks restrict rights/execution enums, pin the research-only flags, and
  require `version_number >= 1`. `SIMULATION_ENABLED` still means only that the
  isolated research simulator may use this version; it is never professional
  approval.
- The payload and all cipher metadata are `NOT NULL`. No raw respondent answer,
  participant ID, demographic column, person score, or ability estimate is
  permitted in this table.

For a profile used by multiple schools, import a separately authorized,
tenant-scoped version into each synthetic school. Do not create a global
shortcut that bypasses the normal school scope check.

### `school_research_task_bindings`

One immutable profile/config/response-mode binding for one research task.
Normal task enrollment and task schedule fields remain on existing rows.

| Required columns | Purpose |
|---|---|
| `school_id`, `task_id`, `class_id` | Exact task and tenant/class scope. |
| `profile_version_id`, `profile_ref`, `version_number`, `profile_sha256` | Exact immutable profile FK; duplicated refs/hashes make mismatches rejectable by the FK. |
| `response_origin`, `status` | `MODEL_GENERATED` or `PUBLIC_OBSERVED`; `ACTIVE` or `REVOKED`. Origin is task provenance, not a profile license or approval state. |
| `config_version`, `config_sha256`, `config_ciphertext`, `cipher_format_version`, `key_version`, `payload_schema_version` | Exact research CAT config needed to create and restore the same session. Do not overload `MeasurementTask.config_version` as a profile approval or fit hash. |
| `created_by_membership_role_id`, `revoked_at` | Scoped author and revocation provenance. |

Required constraints:

- `UNIQUE(task_id)`; a task has exactly one immutable research binding.
- An exact-scope unique key for session FKs:
  `UNIQUE(id, school_id, task_id, profile_version_id, profile_ref,
  version_number, profile_sha256, response_origin)`.
- Task FK `(task_id, school_id, class_id)` references
  `measurement_tasks(id, school_id, class_id)`.
- Profile FK `(profile_version_id, school_id, profile_ref, version_number,
  profile_sha256)` references the matching exact unique key on
  `school_research_profile_versions`.
- Creator FK `(created_by_membership_role_id, school_id)` references the active
  school membership-role key; repository authorization must additionally check
  role status and the explicit research-operator capability.
- Checks constrain `response_origin`, `status`, and
  `revoked_at IS NULL OR status='REVOKED'`.

Binding creation is one UOW transaction: the task must have
`cat_binding_mode='RESEARCH_PROFILE'`; profile and binding must belong to the
same school; profile status must be `SIMULATION_ENABLED`; rights must be
`VERIFIED`; and the profile hash, config hash, instrument/dimension and response
mode must exactly match the explicit import. Lock profile/task rows while
validating. Profile `DISABLED` or `rights_status='REVOKED'`, or binding
`REVOKED`, blocks start, answer, and resume, including for an in-progress
session. Historical reads are limited to L1 lifecycle metadata and cannot
return questions, responses, or snapshots.

### `school_research_sessions`

One resumable CAT state per active task enrollment. It is intentionally not an
`assessment_sessions` subtype.

| Required columns | Purpose |
|---|---|
| `school_id`, `task_id`, `task_enrollment_id`, `subject_id` | Exact task/enrollment/subject scope. `class_id` and `class_student_id` can be derived through the immutable binding and enrollment; do not duplicate them without a demonstrated query need. |
| `task_binding_id`, `profile_version_id`, `profile_ref`, `version_number`, `profile_sha256`, `response_origin` | Exact binding/profile/origin snapshot. The composite FK prevents profile or task swaps during restore. |
| `session_ref`, `config_version`, `config_sha256` | Stable session identity and exact CAT config binding. |
| `status`, `state_version`, `items_answered`, `stop_reason`, `started_at`, `completed_at`, `retention_due_at` | Content-free lifecycle and concurrency metadata. `stop_reason` is a bounded allowlisted code. |
| `snapshot_ciphertext MEDIUMBLOB`, `cipher_format_version`, `key_version`, `payload_schema_version` | Encrypted adapter snapshot, including its authenticated envelope and accepted ordinal responses. Persist no plaintext answer rows. The HMAC/authentication key is app-managed and never stored in the database. |

Required constraints:

- `UNIQUE(session_ref)` and `UNIQUE(task_enrollment_id)` make start/replay
  idempotent: one research CAT session per enrollment in this one-profile task.
- An exact-scope unique key for future research-job FKs:
  `UNIQUE(id, school_id, task_id, task_enrollment_id, subject_id,
  task_binding_id, profile_version_id, profile_ref, version_number,
  profile_sha256, response_origin)`.
- Enrollment FK `(task_enrollment_id, task_id, school_id, subject_id)` references
  `task_enrollments(id, task_id, school_id, subject_id)`; this proves the
  existing active roster enrollment belongs to this exact task and subject.
- Binding FK `(task_binding_id, school_id, task_id, profile_version_id,
  profile_ref, version_number, profile_sha256, response_origin)` references the
  exact-scope binding unique key above.
- Subject FK `(subject_id, school_id)` references `subjects(id, school_id)`.
- Checks constrain `status` to `IN_PROGRESS`, `COMPLETED`, `ABANDONED`, or
  `FAILED`; require `state_version >= 1`, `items_answered >= 0`; and require a
  completion timestamp exactly when `status='COMPLETED'`. State ciphertext and
  cipher metadata are non-null.
- No `assessment_session_id`, `assessment_result_id`, `theta`, `se`, `score`,
  `band`, or psychological interpretation field exists here.

Use existing durable idempotency receipts for start/answer writes and lock the
session row (or compare `state_version`) in the same transaction as snapshot
replacement. On a repeated key, return the original result; different content
under the same key conflicts. Start and every resume revalidate actor school,
SELF subject grant, active enrollment, roster, task window, active binding,
profile hash and profile execution status before decrypting. A disabled/missing
key, ciphertext/hash mismatch, or scope mismatch fails closed without returning
session state.

## Routing and compatibility with existing flows

| Existing path | Source behavior | Required boundary for research tasks |
|---|---|---|
| Student task list | `school_list_student_tasks` joins enrollment to `AssessmentSession` and returns normal assessment metadata only. | Add a distinct research task list/history projection, or an explicit server-owned workflow discriminator with separate DTO. Do not infer workflow from client input; do not expose answers/profile item text in task history. |
| Admin task listing/publishing | `school_list_class_tasks` and the normal task publication response call `_task_cat_binding_fields`, which currently rejects all modes beyond fixture/saved. | Add a safe research-mode branch for listing metadata; create research tasks only through the dedicated profile-binding transaction. Never make the saved-bank activation route accept a research profile. |
| Normal school task start | `SchoolTaskService.start_task` calls `school_prepare_task_session`; the DB adapter creates/recovers `AssessmentSession` and then resolves only `FIXTURE` / `SAVED_VERSION`. | Reject `RESEARCH_PROFILE` before creating `AssessmentSession` and before invoking CAT. Use a dedicated research start route and `school_research_sessions`. Ensure rejection rolls back any idempotency claim. |
| CAT binding checks | `_task_cat_binding_fields`, `_school_task_assessment_binding`, and `AssessmentService._cat_session` recognize only fixture/saved modes; the AssessmentSession DB check has the same two values. | Extend the `measurement_tasks` check only. Do not extend the `assessment_sessions` check. Normal `AssessmentService` and `CATProvider` remain unchanged and reject a research record if one is incorrectly routed there. |
| Enrollment/roster | `TaskEnrollment` binds task, school, class, class student and subject with composite FKs; SELF grant and task window are rechecked on writes. | Reuse existing enrollment/roster/SELF records and authorization predicates. No synthetic account duplication or independent research roster. |
| Teacher progress | `SchoolOperationsRepository.task_progress_counts` counts `AssessmentSession` states. `school_teacher_progress` returns aggregates. | Add a research-mode aggregate branch over `school_research_sessions`; Scope A receives only counts/lifecycle. The existing normal projection must not interpret research sessions as not-started or expose profile identity/item content. |
| Student assessment history | Current history joins `AssessmentSession`, `AssessmentResult`, and normal task metadata. | Research history reads only `school_research_sessions` projection. Do not add profile answers or estimates to `/assessments` or `assessment.v1`. |
| Professional review | `SchoolProfessionalReviewCase` has a non-null FK to `AssessmentSession`; feedback records bind that case and are locked to synthetic L3. | Existing case/review/feedback tables cannot represent this lane. Do not invent an `AssessmentSession` or `AssessmentResult` just to reuse the FK. Later add research-held candidate/review storage bound to the research session and reuse task-scoped specialist assignment only where its task scope is exact. L1 completion is never L3 review or publication. |
| Post-assessment queue | `SchoolPostAssessmentJob.assessment_session_id` is non-null with an exact composite FK; `job_kind` CHECK permits only `EDUCATION_SUPPORT`. | Do not insert research sessions in the existing outbox or weaken its eligibility predicate. A later research queue needs its own session/profile/task composite FKs, lease/idempotency fields, processor and held-candidate state. |

The `RESEARCH_PROFILE` task mode is visible only as a workflow discriminator.
The existing generic student list may instead filter these tasks out, provided
the dedicated research list is the authenticated route used by the student UI.
For either option, ordinary CAT start must reject this mode even if the client
posts directly to its normal endpoint.

## Unit-of-work boundary and slice order

Reuse one `SqlAlchemyUnitOfWork` and add a research repository port; do not
clone the UOW, assessment repository, task enrollment logic, or crypto provider.
The repository participates in the caller's transaction and never commits on
its own. Dedicated research service responsibilities are:

1. **Profile import and task binding:** validate exact hashes/schema/rights,
   encrypt the payload/config, write profile version + task binding + audit in
   one transaction; only an explicitly authorized synthetic research operator
   may set `SIMULATION_ENABLED`.
2. **Student list/start/resume/answer/complete:** reuse existing role, active
   school, SELF grant, enrollment, task-window, CSRF and idempotency checks;
   call only `ResearchCATSession`; persist only the encrypted signed snapshot
   and non-sensitive lifecycle projection.
3. **Teacher progress:** return aggregate research-task counts under the
   existing assigned-class Scope A. Never return individual CAT status,
   category answer, dimension estimate, profile text, or research-review note.
4. **Out of this persistence slice:** research outbox/worker, RAG/7B calls,
   held candidate, assigned professional review, student-facing support and
   publication. These require separate contracts and reviewable sources. Today
   the university RAG allowlist still has no qualifying approved+rights-verified
   university corpus; that blocks a normal evidence-based RAG answer even after
   these CAT tables exist.

Remaining implementation and verification slices:

| Owner | Slice | Acceptance evidence |
|---|---|---|
| Database owner | Three SQLAlchemy models, additive Alembic revision, named checks/unique/composite FKs, encrypted-field manifest and downgrade refusal. | Model DDL compiles for MySQL; SQLite-only schema tests are not accepted as native proof. New cross-tenant/task/profile mismatch inserts fail on MySQL 8.4. |
| Backend owner | Dedicated profile/task binding and research-session use cases over existing UOW/authorization; normal start rejects the new task mode before creating an AssessmentSession. | Same-school synthetic session start/answer/restore/completion; replay and concurrency; cross-school, wrong SELF subject, revoked enrollment/window, wrong profile/config hash, ordinary CAT endpoint and teacher-row probes all fail or return only aggregates. |
| Deployment/restore owner | Revision chain, exact per-revision table manifests, trusted backup/restore projection and downgrade-with-business-data guard. | A sealed 0011 snapshot restores to 0011 then upgrades additively to 0012; a 0012 snapshot restores with new tables and ciphertext/key verification. Preserve both paths and source backup. |
| Independent QA owner | Native MySQL migration, transaction and role-boundary verification. | No DB/GPU/HTTP evidence is inferred from SQLAlchemy compilation or unit tests; report browser/research-worker steps that remain for the next slice. |

## Migration and restore compatibility

The historical three-table slice below targets `20261014_0012`; current source
chain ends at `20261014_0013`. 0013 adds parameter-origin/crosswalk metadata and
strict fitted-versus-published nullability checks while preserving original
encrypted bytes and all negative research flags. An isolated J0012 backup has
restored into NEW K3319 and forward-upgraded0013; native strict schema verification
passed without further DDL. K stored the pinned PROMIS candidate as published
rounded reference with no fabricated fit/calibration hash, recovered original
bytes exactly, and denied duplicate/hash/cross-school attempts. No profile is
enabled and no research route is active. Preserve
`20261014_0011` byte-for-byte and leave its `down_revision` chain intact. The
new revision may alter only the
`measurement_tasks.cat_binding_mode` CHECK and create the three research tables.
It must not rewrite task rows, enrollment rows, assessment sessions, results,
feedback, or the 0011 job table.

Before implementing the revision, update the trusted revision catalog and
restore projections together:

- `13_deployment/school_schema.py`: append 0012 to the linear chain/current
  revision without removing backup support for 0005 through 0011.
- `13_deployment/school_restore_plan.py`: add the new tables to the current
  model manifest and include each table only for 0012 snapshots. It currently
  derives the full live model table set then removes tables by revision; the new
  filter must preserve exact 0011 table/column lists. Its
  `MODEL_TABLE_COUNT = 27` constant is not currently referenced; do not treat it
  as the 42-table current ORM assertion.
- `13_deployment/school_backup.py`, `restore_school_workspace.py`,
  `migrate_school_workspace.py`, runtime revision preflights, and workspace
  schema manifests: accept both old snapshot revision 0011 and new current
  revision 0012, verify each against its exact trusted table/column manifest,
  restore only to a new target, then upgrade older snapshots forward.
- `11_database` schema/data dictionary and schema-contract/outbox tests: update
  expected table inventory (the existing outbox schema test asserts 42 ORM
  tables) and add table/FK/cipher/downgrade checks. Keep 0010/0011-specific
  migration tests passing; update no existing constraint as a side effect.

Downgrade 0012 must first count rows in all three new tables and count
`measurement_tasks` where `cat_binding_mode='RESEARCH_PROFILE'`. If any business
row exists, raise before dropping anything. Only when all are empty may it drop
research sessions, task bindings, then profile versions; then replace the task
mode CHECK with its old `FIXTURE` / `SAVED_VERSION` definition. It must not
weaken or skip the populated-row refusal pattern used by migrations 0009–0011.

### MySQL 8.4 feasibility

This schema uses features already used by the current models: InnoDB composite
foreign keys to named unique keys, enforced CHECK constraints, unsigned BIGINT
tenant IDs, ASCII-binary references, and MEDIUMBLOB ciphertext. MySQL requires
matching types/sign for FK columns and a suitable referenced index; MySQL 8.4
also supports enforced table-level CHECK constraints. Every proposed FK points
to an explicitly unique parent tuple, avoiding deprecated non-unique referenced
keys. The existing project database evidence records MySQL 8.4.8; the static
design is compatible with that baseline, but this task did not execute DDL or
claim native migration proof. See [MySQL 8.4 foreign-key constraints](https://dev.mysql.com/doc/refman/8.4/en/create-table-foreign-keys.html),
[MySQL 8.4 CHECK constraints](https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html),
and [MySQL 8.4 foreign-key online DDL notes](https://dev.mysql.com/doc/refman/8.4/en/innodb-online-ddl-operations.html).

## Source pointers checked

- `11_database/database_layer/models.py:477-569`: task, enrollment and
  assessment-session scope, existing mode checks and composite keys.
- `11_database/database_layer/models.py:636-736`: `AssessmentSession`,
  encrypted `AssessmentResponse`, encrypted `AssessmentResult`.
- `11_database/database_layer/models.py:1015-1138, 1140-1184`: professional
  review requires an assessment session; feedback is locked to synthetic L3.
- `11_database/database_layer/models.py:1615-1709` and
  `11_database/migrations/versions/20261014_0011_post_assessment_job_outbox.py:36-139`:
  existing outbox session FK, idempotency tuple and `EDUCATION_SUPPORT` CHECK.
- `09_backend/src/smhai_backend/domains/school_tasks/service.py:99-151`;
  `09_backend/src/smhai_backend/adapters/database.py:235-366, 1288-1565,
  1566-1793, 1821-1870`; and
  `09_backend/src/smhai_backend/domains/assessment/service.py:528-621`:
  normal list/start/binding/resume/progress routing boundaries.
- `11_database/database_layer/unit_of_work.py:27-70`:
  transaction-owned repositories, crypto provider and commit/rollback boundary.
- `11_database/database_layer/repositories.py:1060-1100`:
  teacher aggregate currently reads `AssessmentSession` states.
- `11_database/migrations/versions/20261013_0009_synthetic_cat_task_binding.py:55-80, 169-195, 230-262`,
  `20261013_0010_school_feedback_publication.py:13-15, 64-168, 254-270`,
  `20261014_0011_post_assessment_job_outbox.py:13-15, 36-139, 143-160`:
  current linear chain and additive business-row downgrade refusal.
- `13_deployment/school_schema.py:3-18`,
  `13_deployment/school_restore_plan.py:29-76, 95-205`,
  `13_deployment/school_backup.py:18-25, 215-253`, and
  `13_deployment/restore_school_workspace.py:117-182`: revision catalog,
  exact manifests and forward-only isolated restore.
- `11_database/reports/DATABASE_ROUND1_ACCEPTANCE.md:23-41, 214-220`:
  existing MySQL 8.4.8 project verification evidence.
- `14_docs/autonomous-delivery/RESEARCH_SCHOOL_INTEGRATION.md`:
  parent research lane design; this document narrows only its persistence and
  restore slice.
