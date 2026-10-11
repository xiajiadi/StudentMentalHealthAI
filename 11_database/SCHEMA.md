# Database Schema Round 1

The authoritative implementation is the SQLAlchemy metadata plus the reviewed
Alembic chain ending at `20261011_0003` (`20260905_0001` initial,
`20260906_0002` contract provenance, and `20261011_0003` school membership and
session context). `DATA_DICTIONARY.md` records column-level details. The schema
has 22 domain tables, all
explicitly configured as InnoDB/utf8mb4/utf8mb4_0900_ai_ci. Machine identifiers
use case-sensitive ASCII collation. All business timestamps are UTC
application values stored as `DATETIME(6)`.

## Common rules

- Resource tables use an internal `BIGINT UNSIGNED AUTO_INCREMENT` primary key
  and a unique UUID4 `public_id`.
- Foreign keys use explicit names and `RESTRICT`; no uncontrolled cascade is
  used. Synthetic lifecycle code deletes children in a documented order.
- State columns are VARCHAR values with application vocabularies and database
  CHECK constraints, not MySQL native ENUM values.
- Sensitive payloads are versioned JSON bytes encrypted by the application;
  raw answers, raw support text, internal prompts, chain of thought, rejected
  unsafe candidates, and full RAG chunks are not plaintext columns.
- `created_at`/`updated_at` are technical timestamps. There is deliberately no
  universal `deleted_at` mixin.

## Tables

### `accounts`

Authentication identity only. Stores `login_name`, `password_hash`, status,
timestamps, internal ID, and UUID4 public ID. It has no subject, assessment,
psychological, display-profile, or raw-password column. `login_name` and
`public_id` are unique. Owner: authentication persistence.

### `roles`

Stable role vocabulary (`student`, `teacher`, `parent`, `reviewer`, `admin` may
be seeded as reference data). `role_code` and status are queryable and unique.
Owner: authorization data supplied to Backend.

### `schools`

School tenant reference, active state, origin, and provenance. `data_origin`
uses the shared origin vocabulary; the application repository currently permits
only `SYNTHETIC`. Required `provenance_ref` values are opaque tokens matching
the registered value `SYNTHETIC_REF_AUTH_TENANT_FIXTURE_V1`, which points to
the synthetic school fixture recipe in
`11_database/tests/test_mysql_integration.py::test_school_contexts_grants_and_sessions_are_same_school_and_fail_closed`.
Do not put names, free text, PII, credentials, member data, or source content in
the field. School creation requires explicit synthetic origin and registered
non-sensitive source/fixture provenance.

### `account_school_memberships` and `membership_roles`

School-scoped account membership and role context with status, validity, and
revocation state. Only student, teacher, psychological-specialist, and admin
school roles are allowed. Internal `REVIEWER` remains in the platform role
system and is not a school membership role.

### `account_roles`

Join table between `accounts` and `roles`, with active/revoked state and grant
timestamps. Foreign keys are restricted. A unique account/role pair prevents
duplicate active assignments. Owner: authorization persistence.

### `subjects`

Pseudonymous person under assessment/support. Stores only `subject_ref`,
optional tenant `school_id`, `data_origin`, lifecycle status, retention marker,
erasure timestamp, and technical identity. A NULL school id retains explicit
legacy isolation. It has no direct identifier and is not an account. Owner:
subject-scoped persistence.

### `subject_access_grants`

Records a supplied relationship between a principal account and a subject:
relationship type, optional tenant `school_id`, active lifetime, validity, and
revocation. A school-scoped grant must match the subject's school and an active
same-school membership. NULL-scoped legacy grants are not tenant grants. It does
not decide whether a request is authorized. Index: principal/subject/status.
Owner: access relationship persistence.

### `consent_records`

Append-oriented versioned consent metadata: subject, consent type, policy
version, scope, grant actor/relationship, grant/withdrawal timestamps, status,
trace, and retention marker. It does not store legal wording and is not a
claim of legal sufficiency. Owner: consent provenance persistence.

### `auth_sessions`

Opaque server-side session record. Stores SHA-256 hashes of the session token,
optional CSRF token, and optional user-agent value; expiry/revocation fields
are queryable. It stores no raw cookie or client IP. Unique token hash and
account/expiry indexes support lookup and revocation. Owner: authentication
persistence.

### `assessment_sessions`

Assessment workflow metadata: `assessment_ref`, subject, instrument/version,
item-bank/config versions, `assessment.v1` schema reference, state, timestamps,
trace, and retention marker. It does not calculate psychometrics or contain
clinical labels. Index: subject/created and status/created.

### `assessment_responses`

Sequenced response provenance: session, sequence, item reference, trace, and
retention marker. The response payload is a nullable MEDIUMBLOB ciphertext with
format/key/payload-schema versions. Unique session/sequence and session/item
constraints prevent duplicate answers. Owner: assessment persistence.

### `assessment_results`

One versioned result payload per assessment session. Schema reference and
completion metadata remain queryable; result JSON is encrypted MEDIUMBLOB.
There are no depression, diagnosis, or risk-label columns. Owner: assessment
persistence.

### `support_sessions`

Workflow/session metadata only: subject, optional assessment reference, target
role, state, timestamps, trace, and retention marker. It intentionally does
not hold conversation text. Index: subject/created.

### `support_messages`

Only `USER_INPUT` or `APPROVED_OUTPUT` message payloads may be persisted by the
repository. The payload is encrypted MEDIUMBLOB with version metadata. A
support-session sequence is unique. Rejected unsafe candidates, prompts, and
chain-of-thought are not accepted by the persistence API. Owner: support
persistence.

### `support_runs`

Execution metadata: run reference, support/assessment links, generation and
retrieval references, trace, workflow action, state, bounded component-version
JSON, timings, and retention marker. It does not copy large upstream responses.
Indexes: session/created and trace.

### `support_evidence`

RAG provenance references only: citation/source IDs, source version/hash,
locator, and rank. It does not duplicate corpus text. Unique run/citation and
run/rank indexes support reproducible citation display. Owner: provenance
persistence.

### `safety_decisions`

Stores the supplied engineering `SafetyAction`, policy version, guard revision,
trace, run link, and retention marker. Detailed reason/context is encrypted
MEDIUMBLOB. The database does not interpret the action or turn it into a
clinical label. Owner: safety workflow persistence.

### `review_cases`

Human review queue fields: review reference, subject, source safety decision,
priority, state, assignee, timestamps, version, and retention marker. The
optional case note is encrypted. The `version` predicate provides optimistic
concurrency protection; queue indexes keep state/priority/time queryable.
Owner: review workflow persistence.

### `review_events`

Append-oriented review history: case, event type, actor, status transition,
trace, timestamps, and retention marker. Detailed notes are encrypted. The
case/created index supports audit history without decrypting notes. Owner:
review history persistence.

### `idempotency_records`

Stores scope, SHA-256 key hash, request hash, state, result pointer, and expiry.
The `(scope, key_hash)` unique constraint and transaction/savepoint path prevent
two concurrent claims from creating two authoritative effects. Raw keys and
full responses are not stored. Owner: reliability persistence.

### `audit_events`

Append-oriented safe audit record: actor reference, action, resource type/public
reference, result, trace, allowlisted JSON metadata, and timestamp. There is no
raw chat, answer, result, password, token, key, safety payload, or full review
note. Owner: audit persistence.

## Deliberately absent

There are no school/classroom ERP tables, analytics copies, long-term
psychological profiles, vector-corpus duplicates, notification tables,
clinical-diagnosis fields, direct student identifiers, or database-owned
authorization policy tables in Round 1.
