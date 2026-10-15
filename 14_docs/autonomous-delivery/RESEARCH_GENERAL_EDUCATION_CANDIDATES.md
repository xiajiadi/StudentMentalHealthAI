# Task-bound research general-education candidates

Controller direction2026-10-15; additive engineering increment. The required path is
completed research session -> real RAG/local-model candidate -> assigned specialist
review -> explicit feedback publish/revoke. Verified progress is in CURRENT_STATE.md. It does not
replace private independent conversations with a taskless review portal.

## Invariants

- New explicit policy RESEARCH_GENERAL_EDUCATION_DRAFT_V1 with a required pinned
  policy hash; reuse0016 outbox with a separate policy key. Old no-policy and
  staff-programme policies/records remain unchanged; do not relabel/requeue them.
- Only explicitly enabled synthetic/public-observed completed sessions and current
  task/profile/enrollment/SELF/source-policy scope. Existing800 sessions are used
  without CAT replay. New-policy enqueue is bounded/idempotent and audited.
- Inputs are a fixed general-education request and pinned task/source metadata.
  Never load/decrypt/send responses, snapshots, scores, theta or risk labels.
- Real R3 excerpts, three layers, fixed local7B, all three Safety stages,
  citation/hash and claim checks. No cloud/model substitution or fixture output.
- Every successful generation is HELD for source-limit/content review. Safety
  success never implies semantic correctness, professional approval or release.
  Candidates are not visible to students/teachers/administrators.
- New encrypted education-candidate persistence is exactly session/job-bound.
  It must not repurpose0018 STAFF_REFERENCE_ONLY programme candidates or safety
  cases. Original generated payload is immutable; reviewer notes are encrypted,
  state transitions versioned/audited. No silently rewritten failed answer.
- Candidate payload includes full structured citations and exact source excerpts/
  populations/limitations from the pinned source package, preserving qualifiers.
  Reviewed feedback can be corrected in a new draft; retain candidate lineage.
- Detail adds a closed review_lineage projection after server verification of the
  actual consumed input/output review sidecars. It is separate from immutable
  encrypted payload v1; candidate summaries stay unchanged. Historical
  REVIEW_REQUIRED remains the original Safety action,never an automatic approval.
  Candidate and consumed-review creation timestamps use one UTC transaction clock.
- Scope C is current assigned-task access, rechecked on every operation. Existing
  review-case authorization and case APPROVED/version gates remain. ADOPTED is
  a research workflow action, not professional/clinical approval or publication.
- Candidate-to-feedback draft requires exact school/session/task/profile/source
  pins, adopted candidate, current assignment, approved case and explicit request.
  Keep existing explicit publish and revoke; student only sees own published
  feedback and its source information. Manual v1 feedback remains compatible.
- Existing private conversations, default university behavior, frozen Contracts,
  safety/crisis routes, original databases and professional approval flags stay
  within their existing boundaries. No new model attempts until processor and
  held/review persistence are implemented and reviewed.

## First implementation boundaries

Database owner: additive0020 candidate/event schema and exact job/session FKs,
repository/UOW, new policy registry entry, optional feedback candidate lineage,
revision/restore registration and focused tests. Candidate body/citations remain
encrypted; repositories never load CAT snapshots. Downgrade with data refuses.

Backend owner: new closed domain DTOs/processor ports and held-only generation
orchestration. Reuse Knowledge/Generation frozen v1 and current source/Safety
clients; no backend container/route wiring until Root reviews the contracts.

Then integrate bounded worker/enqueue and assigned-specialist candidate/detail/
adopt/draft APIs; extend feedback encrypted payload as explicit v2 while retaining
v1 decode. Add source display in existing specialist/student feedback UI.

## Acceptance

Focused schema/repository/processor tests; wrong-role/school/task/student denials;
source revocation and stale-case/candidate versions; original payload preservation;
no student visibility before explicit publish and no visibility after revoke;
one isolated native generation plus database/browser review/release journey.
Only then enqueue the remaining bounded800 workload and measure real processing,
recoverability and status counts. A small passing batch is not800 acceptance.
