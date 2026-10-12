# Exact synthetic CAT activation and task binding

Controller direction, 2026-10-13 Beijing. Implementation pending. This follows
saved-version simulation; it does not approve psychological interpretation,
personal feedback, real student use or professional publication.

## User outcome

A school specialist explicitly enables an immutable saved plan version for a
synthetic task. The school administrator selects that enabled version by metadata
when publishing a class task. The enrolled synthetic student receives the saved
items/configuration, and an interrupted assessment restores that exact version.
Ordinary teachers and administrators never receive bank documents or parameters.
Existing fixture tasks and frozen assessment.v1 remain compatible.

## Persistence and authority

Use additive0009 attachment tables, preserving all existing task/session column
values and rows: activation, task binding, session binding. Add an explicit
cat_binding_mode FIXTURE/SAVED_VERSION marker to task and session, default FIXTURE
for old rows. SAVED_VERSION requires its exact binding; absent binding never
selects the fixture, even when saved documents were cloned from that fixture.
FIXTURE additionally requires exact D3_IDENTITY. Update supported restore manifests
explicitly for the new columns rather than accepting arbitrary schema differences.
Each activation identifies
one exact same-school plan version, creator role, ACTIVE/REVOKED state, revision,
and engineering-only purpose. New activation of a revoked version is explicit;
never reactivate a historical activation or substitute the latest plan version.
Activation and revocation require specialist role, CSRF, stable idempotency and
fresh persisted authorization. Activation is eligibility, not measurement validity.

Task binding is unique per task and records exact activation/plan-version IDs.
Session binding is unique per assessment and includes its task enrollment,
subject, school and task binding. Use composite same-school/subject foreign keys
against existing0007 scope keys and exact activation/plan-version keys; RESTRICT
deletion. No automatic backfill and no interpretation of ambiguous version strings
as saved document identities. Missing expected binding fails closed.

Publishing accepts an optional explicit activation_ref. Omitted/null preserves
the old fixed-fixture path. Fresh locked eligibility checks, task/enrollment/binding
inserts, metadata audit and idempotency receipt share one short UOW. Metadata lists
for administrators expose only names, refs, version numbers and eligibility state.

New starts require current task/enrollment/roster authorization and active
activation plus active bank/plan parents. Assessment creation and immutable session
binding share one short UOW. A newer version never changes a bound task/session.
Asset archive or activation revocation blocks new assessments; an already
IN_PROGRESS authorized bound assessment retains its original saved documents.
A CREATED session still requires active eligibility; idempotent start/retry cannot
replace its original binding. Current identity, enrollment, published task and
time-window authorization continue to apply to every access, including recovery.
Explicit enrollment/roster/access revocation still denies continuation under the
existing policy. Never grandfather access after user authorization is withdrawn.

## CAT execution and recovery

Add a separate internal saved-session start route with exact binding refs plus
validated published synthetic bank/config documents. Preserve the old internal
fixture-start route. Validate subject and binding identity on reuse, reject
mismatches409, and keep the provider/session registry independent from simulation.
State and completion must use the session's own bank/config, including item prompt,
options, stopping rule, max items and reported versions. Preserve existing fixture
behavior and provider/math/frozen research assets.

Backend resolves/decrypts the session binding in an authorized short UOW before
network work. CAT404 recovery loads only that immutable version and replays stored
responses in sequence. No latest lookup, fixture fallback, repaired answers,
invented timestamps or transaction held across CAT network work. Fresh scope checks
before storing/returning responses remain mandatory. CAT-only restart must preserve
the exact next item and completion behavior from persisted responses.

## Required evidence

Source tests for scope/FKs/concurrency/replay, strict internal document/start
identity, session-owned state, archive/revocation semantics and legacy compatibility.
Reviewed native additive migration with exact old-row preservation and sealed
backup; actual four-role HTTP/UI task publication and saved-version CAT completion,
cross-school/role denials, idempotency and transaction rollback. Demonstrate partial
answer persistence, verified CAT process restart, exact-version resume and outcome.
Do not claim full recovery, L2/L3 publication or professional approval from this slice.
