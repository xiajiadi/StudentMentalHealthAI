# Data Retention Policy V0.1

Status: ENGINEERING PLACEHOLDER  
Not legal approval, ethics approval, or a final retention schedule.

## Round 1 behavior

- Only synthetic fixtures are allowed.
- Sensitive rows may carry `retention_due_at`; the value is supplied by the
  test or deployment policy rather than hardcoded in the schema.
- A synthetic retention run can clear encrypted payload columns and key
  metadata after the supplied due time. It records a safe count and state in
  `audit_events`.
- A synthetic subject-erasure run deletes child assessment/support/review
  records in an explicit dependency order, anonymizes the subject reference,
  marks the subject `ERASED`, and leaves no raw psychological content in the
  audit tombstone.
- No universal `deleted_at` field is used. Operational closure and personal
  data erasure are separate operations.

## Future real-data review questions

Before enabling real data, the project owner must approve the purpose,
population, data classes, shortest necessary retention period, legal/ethics
basis, consent and withdrawal handling, guardian semantics where applicable,
access roles, backup retention, deletion evidence, and exceptions where a
limited safety or legal record must remain. The database layer must then be
updated through a reviewed decision and migration if the approved design
requires structural changes.

The PIPL minimum-necessary retention principle is an engineering input, not a
claim that this placeholder answers the legal question.
