# Bound input-safety review for research education jobs

Controller engineering direction,2026-10-15. The observed fixed request received
CONTENT_CONTROVERSIAL/REVIEW_REQUIRED before retrieval. This is not a proved code
bug or a professional judgment about danger. The original job stays terminal.
No prompt changes, automatic approvals, Guard tuning or safety-policy changes.

## Intended complete workflow

Capture the actual input decision and a content-free binding to its job. An
assigned Scope C specialist can inspect the fixed, nonpersonal request and its
source/policy provenance, reject it or explicitly authorize one continuation to
retrieval. This action concerns a general research draft, not clinical approval,
case approval, publication or permission for a school deployment. No action may
be inferred from a CAT case or Safety's unauthenticated internal transition API.

Only exact INPUT REVIEW_REQUIRED, requires_human=true, and the sole reason
CONTENT_CONTROVERSIAL can be eligible. BLOCK, CRISIS_ROUTE, missing/invalid Safety
evidence, other reasons and every retrieval/output stop remain stopped. The
original Safety action and reasons are immutable and must remain visible in
provenance. A specialist disposition must never relabel them PROCEED.

The eventual continuation must bind current school/session/task/profile/policy,
source package/study/manifest, prompt and fixed-input digests, original decision,
trace and review reference. It requires current assignment/role, explicit CSRF-
protected action, idempotency, expected version, expiry and one-time consumption.
Recheck these at dispatch and candidate persistence. Revocation or changed pins
prevent dispatch/storage; there is no automatic retry or alternative model.
Retrieval and output Safety still run; every candidate remains HELD and requires
the separate existing adoption,case review,draft,publish/revoke workflow.

## Increment one: preserve evidence; do not enable continuation

1. Extend Backend's internal Safety projection with optional decision_id; old
   responses remain compatible. Capture a strict stopped-input receipt only when
   actual IDs,operation,trace,action,reasons and requires_human bind correctly.
2. Carry this receipt through the research-only Outcome. Its canonical digest
   includes the fixed request,stable SYSTEM/UNKNOWN context,prompt/source/policy
   pins; request/trace IDs are stored separately. No CAT or personal text.
3. Add0021 content-free review and append-only event records bound by exact job
   scope. Atomically store a PENDING record while finalizing the original job.
   Missing receipt retains the current terminal result without invented linkage.
4. Expose exact assigned-task GET and versioned REJECT/REVOKE dispositions through
   Backend. No permissive default,continuation route or auto approval in this
   increment. The review identity and immutable evidence survive process restart.

The historical failed job has no captured decision/reference receipt. It is not
eligible for retrospective manufacture of evidence. Preserve it unchanged.

## Integration and acceptance

Database/repository owner supplies additive migration,12-field scope FK,unique
original job,strict enums/pins/expiry/version,events and UOW wiring. Root owns
Backend adapter/API/authorization and startup/restore registration. Processor
owner supplies strict receipt projection and worker handoff; UI owner consumes
only reviewed Backend DTOs. Keep frozen external Contractv1 unchanged.

Focused verification: old responses/jobs compatible; wrong traces,missing IDs,
non-INPUT,extra reasons,crisis and BLOCK cannot create an eligible receipt;
atomicity and duplicate finalization; cross-school/task/role denials; stale
version/expired/revoked pins; no snapshot loads or plaintext psychological data.
Continuation is not enabled until its explicit authorization and one-shot
dispatch/storage checks exist together and have targeted negative evidence.
No generation attempt is authorized by this design document alone.
