# School class and measurement task increment

## Outcome

School administrators organize synthetic classes and publish measurement tasks;
students start or resume their own assigned task; assigned teachers see task-level
completion counts. Existing self-initiated student measurements remain available
and are never retroactively linked into school tasks.

## Authority and information boundaries

The authenticated active school context supplies the tenant. Request bodies cannot
choose another school or role. Every operation revalidates the account, school,
membership role, class assignment, subject relationship and enrollment as relevant.
School admins manage organization and tasks, without psychological content access.
Teachers require an active class assignment; TEACHER_OF alone does not grant task
access. Specialist/reviewer roles acquire no organization permissions.

Teacher output contains class/task opaque references, display labels, task status,
time window and task-level counts. It never contains student/subject/assessment
identifiers, individual activity times, answers, item counts, scores, reports or
review states. Aggregate queries read session status columns, without loading or
decrypting assessment results or responses. No privacy threshold is invented.

## Task lifecycle

- Publishing snapshots the class's currently valid synthetic student roster in
  one transaction. Invalid relationships abort the entire publication.
- Each enrollment owns at most one assessment session. Repeated starts resume
  that session. Abandoned/invalid session retakes are not introduced here.
- A task start constructs a new bound session from server-owned task instrument
  configuration and enrollment subject. It cannot attach an existing standalone
  session, including an unanswered or completed session.
- Only PUBLISHED tasks within the open/due window allow start or continued access.
  Closed/cancelled/not-yet-open/expired tasks fail closed. Enrollment revocation
  immediately blocks task-linked assessment get/state/response/complete operations.
- Revoked enrollment rows remain in the publication snapshot denominator. Show
  active and revoked counts separately; do not mislabel revoked students as complete.
  Retaining history does not restore access or permit reusing a standalone result.

## Additive interfaces

New organization/task APIs are module-local and preserve frozen assessment.v1,
knowledge.v1, generation.v1 and existing API envelopes. Use bounded request sizes,
opaque resource refs, CSRF for writes and request fingerprints for idempotency.
Public role responses do not expose database IDs or client-selectable scope.

The first business slice provides:

1. Same-school admin class list/create and typed teacher/student assignment.
2. Admin task publication and enrollment revocation, with atomic snapshot storage.
3. Student own task list and task start/resume, with server-derived instrument/subject.
4. Teacher assigned class/task progress list, exclusively aggregate output.
5. Human-readable class/task labels so the approved role pages can expose real tasks.

Cross-school/nonexistent/unassigned resources are masked as not found; role/session/
CSRF failures use the existing error shell. Conflicts roll back the use-case. A
failed dependency does not create a fake completed session or partial publication.
Durable idempotency writes and associated business mutations share a transaction.

## Integration and evidence

Use additive migration after 0004; never modify an applied migration or old M0 data.
Before native migration, review model/DDL consistency and independent security
findings. Native tests run only on an explicitly owned synthetic test schema.

Required evidence covers same-school publication/start/completion, cross-school and
inactive relationships, closed/time-window denial, revocation during an existing
session, duplicate/concurrent starts, publication rollback, immutable standalone
session separation, teacher output allowlists and no private-repository access.
Then verify the actual four-role browser workflow using generated sealed accounts.
Unit tests and an offline migration alone do not establish business delivery.
