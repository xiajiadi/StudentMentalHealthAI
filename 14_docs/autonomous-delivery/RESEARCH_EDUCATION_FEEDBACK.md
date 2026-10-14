# Research education feedback delivery

## Scope

Extend the existing school review/publication workflow to completed research
sessions without fabricating legacy assessment sessions. This is an isolated
fictional-school engineering workflow. It does not approve a bank, population,
psychological interpretation, real student use, ethics or school production.

The research outbox remains content-free. Its no-policy consumer abstains.
Manual general educational feedback is a separate, explicitly reviewed path;
real-source model candidates remain gated by source qualification and Safety.

## Persistence and authorization

Revision0017 adds research review case/event and feedback record/event tables.
Case and feedback bind the exact twelve-column research session scope. Existing
tables and frozen contracts are preserved. Notes and feedback bodies are encrypted;
events contain transition metadata only. No answer, score or CAT snapshot enters
these records. Case creation requires a completed session and current task-level
specialist assignment. Every read/write freshly checks tenant and current scope.

Review states are OPEN, IN_REVIEW, APPROVED and REJECTED. Feedback states are
DRAFT, PUBLISHED and REVOKED. Approval does not publish. Publication requires
explicit action and matching case/state versions. Student visibility requires a
current SELF grant, enrollment and PUBLISHED feedback. Teachers and administrators
cannot read content. CSRF, idempotency and optimistic versions apply to writes.

Feedback kind is GENERAL_EDUCATIONAL_SUPPORT, research_only remains true and
psychological_interpretation_allowed remains false. PUBLISHED means visibility
inside this research workflow; source publication/professional approval flags
remain unchanged. Students must see that this is research simulation feedback,
without measurement scores or interpretation.

## Interfaces

API prefix: `/api/v1/school/research-feedback`.

- Specialist: tasks; per-task eligible sessions, cases, case detail and decisions.
- Specialist: case draft creation/list; feedback explicit publish/revoke.
- Student: own published feedback list/detail.
- Lists use bounded pagination and closed DTOs with research references.
- Draft title120/body4000 and private review note4000 are maximum lengths.

Acceptance covers an assigned specialist's complete create/review/draft/publish/
revoke flow, student visibility before/after each transition, wrong-role/school/
assignment denial, stale version/idempotency behavior, encrypted persistence,
additive migration/restore and representative actual browser interaction.
Use focused checks and one native journey rather than repeating the800 replay.

## Current state

Implemented in source a1b62d0 with MySQL DISTINCT ordering corrected in626b93e.
Native isolated O0017 restore imported the preserved0016 data and verified keys;
the actual API journey approved one research case, created a general educational
draft, published it, read it as the student, revoked it, and confirmed removal.
The r6 artifact records those successful transitions but ends BLOCKED on a helper
denial-code comparison. The corrected r7 recognizes the revoked state and proves
five sensitive requests denied403, without replaying publication; it is PARTIAL.
Both artifacts are retained under D:/Dev/temp/psynova-o0017-research-feedback-r*.json.

Independent native read-only verification authenticated one encrypted case note
and one feedback payload, checked schema/reference/revision/scope, and emitted no
plaintext. Proof: D:/Dev/temp/psynova-o0017-feedback-cipher-readback-r1.json,
SHA2561e806e4551b31a1d0ab6fb697149d251ba6f0aeadc4c1baff4dca991e9d11a17.
Fresh Edge browser r3 passed draft creation, explicit publication, student refresh
visibility, explicit revocation and removal after student refresh; both sessions
logged out. Root inspected three cropped screenshots in
O/browser-qa/20261014T121217Z-e18d43c77c86413aa65229d1c3ccb8d0/.
Proof: D:/Dev/temp/psynova-o0017-research-feedback-browser-r3.json.
There is no professional approval or real-source RAG/model generation acceptance
from these results.
