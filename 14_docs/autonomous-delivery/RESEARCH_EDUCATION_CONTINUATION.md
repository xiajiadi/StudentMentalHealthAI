# One explicit research input-review continuation

Controller engineering direction2026-10-15, extending the0021 evidence increment.
This is an assigned specialist's research workflow action concerning a fixed,
nonpersonal request. It is not professional/clinical/content/publication approval.
The existing Safety decision is never changed or labelled PROCEED. No change to
frozen external Contractv1,Guard/policy,model,source texts or old evidence.

## Binding and state

- Default disabled. A trusted Backend/deployment opt-in enables
  RESEARCH_INPUT_REVIEW_ONCE_V1; each grant stores its exact version/hash.
- Only authentic captured INPUT/REVIEW_REQUIRED/requires_human=true with sole
  CONTENT_CONTROVERSIAL is eligible. No retrospective receipt,crisis/BLOCK,
  missing identifiers,additional reasons or retrieval/output continuation.
- PENDING v1 may become CONTINUATION_AUTHORIZED v2 by explicit current assigned
  Scope C action with CSRF,idempotency,expected version and fixed24h/retention
  expiry. Atomically create one round1 outbox job. Original round0 remains terminal.
- AUTHORIZED v2 may be REVOKED v3 before storage,or CONSUMED v3 in the same UOW
  as candidate insertion and HELD completion. CONSUMED cannot be reopened or
  revoked; candidate discard and feedback revoke remain separate workflows.
- Recheck original receipt,digests,scope,source/policy/prompt,grant policy,expiry,
  exact authorizing membership/assignment at dispatch and storage. Revocation,
  stale scope/pins or expired lease prevents dispatch/storage. Never auto approve
  or retry generation. Worker max_attempts remains1 for each distinct job.

## Database compatibility (0022)

- Jobs add generation_round=0(default)/1 and nullable input_review_id. Existing
  enqueue/ref/batch replay is always round0. Extend session/policy uniqueness to
  round; one continuation per review. Round1 requires the fixed general policy
  and an exact review scope. Preserve original session/job FKs and round0 bytes.
- Review/event status columns must widen from16 to24 characters. Add explicit
  authorization policy pins and consumed_at; update status/version/event checks.
- Candidates add generation_round=0 and nullable input_review_id/input_review_state.
  Normal:round0,NULL,NULL,input action safe. Reviewed:round1,nonnull,CONSUMED,
  input action REVIEW_REQUIRED. Retrieval/output always safe. Explicit IS NOT NULL
  checks prevent SQL UNKNOWN from accepting a partial pair.
- Add nonnullable candidate(job_id,generation_round,session,school)->job unique
  FK so NULL review cannot attach a round0 candidate to a round1 job. Separately
  bind candidate(job_id,review_id,session,school) and review(id,status,session,school)
  to exact indexed parents. A review's original job must be round0. No cascades.
- Payload v1 encrypted bytes and content hash remain unchanged. Actual original
  input action/reasons are retained in its existing provenance fields; immutable
  row sidecar supplies grant lineage. The v1 hash does not cover the sidecar.
  Validate sidecar/job/CONSUMED review on every candidate and feedback access.
- Downgrade refuses any round1,lineage,authorization/consumption or v3 events.
  Restore manifests must retain older revision layouts and physical ALTER order.

## Processor and API

Only the worker receives a typed reviewed-input capability loaded from current
authorized DB state; HTTP callers cannot supply it. Its job/trace,pins,policy and
expiry are validated. Continue after the original input decision to the existing
retrieval and output guards; always return HELD or a truthful stopped outcome.
Grant/dispatch failure never creates substitute content. Publication remains a
separate case/adoption/draft/publish/revoke sequence.

Dispatch validates the live grant in a short transaction, then releases locks
before local inference. Revocation cannot recall an already transmitted model
request: an in-memory call may finish. Storage opens a new transaction and
rechecks the grant, exact authorizing membership/assignment, lease, expiry and
source pins; a revoked grant cannot persist a candidate or consume the review.
No database locks are held throughout model inference.

API/UI distinguish original and continuation jobs. Explicit action is named
"授权一次继续"; no APPROVED state or automatic batch authorization. Normal APIs
and disabled deployments remain compatible. Real source selection must preserve
policy/theory/intervention layers,full excerpts/qualifiers/citations and6000-char
runtime budget; reducing raw top_k alone is insufficient (offline5840 layered
selection versus7386 all4; top3 lost policy and still6139).

Required evidence:normal-job compatibility; no duplicate continuation; atomic
authorization/enqueue and consume/store; wrong role/scope/trace/pins/expiry and
revoke race deny; max1 dispatch under crash/lease; old payload hashes unchanged;
all guards exercised and actual reviewed candidate still HELD; native specialist
and student publish/read/revoke journey before800 workload.
