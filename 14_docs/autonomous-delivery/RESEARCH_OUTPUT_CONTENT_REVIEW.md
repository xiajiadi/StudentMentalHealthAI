# Research output content review

Controller decision2026-10-16. The actual native output Safety event for
REJ_44fc4dd3a02d70a19f341aba09564b039d682bc63f394ad81dd156c0cb7df61a
is REVIEW_REQUIRED / CONTENT_CONTROVERSIAL / requires_human=true. Existing code
discards the generated body, so a reviewer cannot inspect or resolve it. This
increment implements that missing research workflow; it does not change Safety
decisions or confer professional approval.

## Eligibility and preservation

- Future outputs only, from the existing fixed non-personal general-education
  research request and qualified source bundle. Never recover discarded bodies,
  replay failed jobs or read CAT answers/scores/private conversations.
- Only an actual OUTPUT action REVIEW_REQUIRED with requires_human=true and
  exactly one reason CONTENT_CONTROVERSIAL is eligible. No CRISIS_ROUTE, BLOCK,
  unsafe/clinical/PII signal, arbitrary reason or unavailable Safety service.
- In the same transaction as the current exact lease terminal disposition, save
  an encrypted Output Review containing the actual structured output, retrieval
  snapshot, citation/source cards, model/prompt/source pins and original decision
  binding. No generated body or matching fragment in logs, audit metadata or list
  responses. Original job stays REVIEW_REQUIRED/SAFETY_BLOCKED; original Safety
  decision and terminal audit remain immutable.

## Review and candidate creation

- Assigned current task Scope C only. Ordinary teachers, administrators, other
  schools and students cannot read review bodies or resolve a review.
- Add list/detail, explicit reject/revoke and create-held-candidate operations.
  Use CSRF, state version, idempotency, current study/assignment/source checks.
  Review transitions PENDING -> REJECTED | REVOKED | CONSUMED; consumption and
  exactly one HELD candidate creation are atomic.
- Candidate creation uses the stored output and stored retrieval snapshot. Run
  existing claim, bibliography, citation, size and source checks again; no new
  retrieval, model generation, Safety re-evaluation or content substitution.
- Preserve actual output_safety_action=REVIEW_REQUIRED and original reason. A
  narrow consumed-output-review lineage permits this candidate; never expand
  the ordinary safe-action allowlist or pretend that Safety returned ALLOW.
- Support original round0 and round1. Round1 input authorization is currently
  AUTHv2 after an output stop. Add a separate tightly scoped consumption method
  for the exact terminal job and pending Output Review; validate all existing
  grant/source/prompt/scope/expiry pins and consume AUTHv2 -> CONSUMEDv3 in the
  same transaction/time as candidate creation. Keep the ordinary live-LEASED
  consume_for_candidate path unchanged. Reject stale, revoked or consumed grants.
- HELD still requires the existing explicit ADOPTED decision, independent case
  workflow, editable feedback draft, publish, self-read and revoke. Output Review
  is research content review, not clinical, psychometric or production approval.

## Persistence, compatibility and acceptance

- Additive0023 review/event tables and nullable candidate sidecar lineage with
  exact school/task/session/job scope and uniqueness. Old rows remain NULL/NULL.
  Preserve encrypted payload version compatibility; no generic terminal-job
  rewrite, schema reset or reseeding. One owner implements database/migration and
  deployment revision/restore inventory updates; Backend and frontend owners use
  the agreed repository contract.
- Verify exact eligibility negatives, atomic rollback, duplicate/stale actions,
  expiry/source/assignment revocation, wrong-role/school/session denial, original
  job/decision preservation and no model calls during review. Only then one new
  isolated native output, actual content review and browser feedback lifecycle.
  Existing failed cases remain preserved. No batch800 inference before that path.
