# Synthetic task feedback publication

Controller direction, 2026-10-13. Module-local school workflow; frozen
assessment/report contracts and Safety REVIEWER routes remain unchanged.

## Outcome and boundaries

Students receive completion metadata as L1. A separate L3 feedback record can
be drafted and explicitly released by the currently assigned specialist after
the exact task review case is APPROVED. A review note is never copied into a
feedback body. Completion and review decisions do not publish anything by
themselves. This increment has no L2 template catalogue: L2 creation must be
rejected, since no independently preapproved catalogue currently exists.

All records and output carry server-owned synthetic_only=true and level=L3.
The release action is a synthetic workflow acknowledgement of the exact draft,
not psychometric validation, clinical approval or authorization for real data.
No CAT score, diagnosis, threshold, raw response or model interpretation is
generated or inserted into feedback. Tests use neutral synthetic body text.
The existing Backend claim-boundary matcher is reused unchanged for draft
validation and decrypted publication/read content; this API cannot introduce
the claims that the ordinary support route rejects.
The independent AI service does not read these records; no implicit sharing.

## Durable records and API

Each immutable content revision is bound to the exact school, task, enrollment,
subject, assessment and review case. Store encrypted title/body separately from
case notes. Draft content is immutable: a changed body creates a new revision.
The state is DRAFT -> PUBLISHED -> REVOKED, with event/version history. Never
delete or overwrite a released content revision. Case locking allocates revision
numbers and serializes create/publish/revoke. Row state_version is distinct
from content_revision and from review case version.

Module prefix `/api/v1/school/feedback`:

- GET/POST `/cases/{case_ref}`: assigned specialist history/create draft.
- POST `/{feedback_ref}/publish`: explicit release of this exact draft.
- POST `/{feedback_ref}/revoke`: remove student visibility, preserving evidence.
- GET `/student`: only the active student's currently authorized PUBLISHED rows.
- GET `/student/{feedback_ref}`: the same student scope and publication gate.

Draft request: strict expected_case_version, title (1..120), body (1..2000).
Transition request: strict expected_case_version and expected_state_version.
Unknown fields, blank text, booleans-as-versions and client-selected owner,
school, role, level, synthetic flag or approval scope are rejected.
Draft/list projection includes feedback_ref, case_ref, assessment_ref, level,
synthetic_only, content_revision, state_version, case_version, status, title,
body, created_at, published_at and revoked_at. Student projections omit
case_ref/case_version and expose only PUBLISHED content. Responses are strict
allowlists, never ORM serializations or ciphertext.

## Authorization and transactions

Every operation re-resolves current membership/role/school and exact task scope
inside its database unit of work. Specialist access requires current assignment,
active enrollment/roster/subject and a completed assessment. Students require
their current SELF grant, active roster/enrollment/task and matching subject and
school. Default fail closed after task/enrollment/role revocation. Teachers,
admins and Safety REVIEWER cannot read or publish private feedback content.
Published feedback may remain available for a CLOSED task or after its due date:
the deadline controls assessment entry, not ownership of already released feedback.
Explicit task REVOKED and revoked identity/roster/enrollment/SELF grants deny access.

Publish additionally requires case APPROVED and its current version equal both
expected_case_version and the draft's case_version. A later case decision cannot
silently approve an older draft. Revoke requires the same assigned specialist
scope and current expected versions, but does not need to reinterpret content.
An authorized repeated key returns the same immutable resource; changed content
with the same key conflicts. Fresh authorization precedes every cached receipt
replay. Draft/state/event/audit/receipt changes commit atomically; an injected
audit failure must roll all of them back. No network/model call inside a UOW.

## Migration and acceptance

Additive revision after0009 only; composite FKs enforce case/task/enrollment/
assessment/subject/school linkage. Preserve old stored columns and all old rows.
Downgrade refuses new feedback business rows. Restore manifests include the new
tables only for the new revision, preserving0005..0009 snapshots exactly.

Before native migration: source/schema tests and independent source review.
Before engineering acceptance: sealed pre-DDL backup; actual migration and old
row preservation; native draft/publish/student-read/revoke; stale version,
replay, changed-body conflict, wrong school/role/subject, revocation and rollback;
real specialist/student browser flows with masked screenshots; restore/restart.
Until those pass, this is implementation in progress and not a completed product.
