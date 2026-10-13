# Research CAT Backend API slice

Status: **design proposal; routes and Backend authorization are not implemented**

## Implementation delta — 2026-10-14

The historical inspection below predates schema0013. Research persistence is
now committed, including v3 published-reference parameter provenance; it no
longer requires fictitious fit/calibration hashes. The server registry supports
v1/v2/v3 storage compatibility without granting execution eligibility.

A separate Python3.14 private CAT HTTP bridge is committed in4a6f86c. It accepts
explicit bindings, authenticates before parsing private requests, bounds actual
body bytes/JSON structure and returns signed Backend-private state plus L1
metadata. Root ran104 research tests; independent QA ran64 bridge/session tests
with actual pinned PROMIS artifacts. Backend remains Python3.12 and must use
HTTP rather than importing the CAT runtime. Client/runtime wiring is in progress.

Scope locks now take roster before a refreshed enrollment, matching roster
revocation. Ordinary start filters research tasks before taking scope locks;
the post-lock normal-mode guard remains. Root ran33 repository tests and45
Backend start/audit/authorization/binding tests with configured DB dependencies.
Native MySQL contention verification is pending. Do not compose the historical
helper with the research prefix or declare global concurrency acceptance. Every operation still needs live
account/membership/SELF/roster/task-window checks, CSRF, idempotency and encrypted
CAS persistence. No research session API, online800 run or AI publication is
established by the bridge tests.

## Historical design inspection
Inspected source: branch `xiajiadi/autonomous-delivery-20261011`, HEAD
`a6e442a01e3d0d60db1666d7b56af35bd6dd3ce0`, 2026-10-14.

This note defines the smallest Backend slice for a separate, research-only CAT
session. It preserves the existing assessment/API contracts and leaves
professional review and publication gates unchanged. The response projection
is lifecycle-only L1: no theta, standard error, score, interpretation, normal
assessment result, post-assessment job, or professional review case.

## Verified current implementation

- `school_tasks_router` is mounted under the configured API prefix with its
  schema hidden. Its write helper requires `Idempotency-Key`, fingerprints the
  request, scopes the receipt to actor/school/role/operation, then calls the
  service ([router.py](../../09_backend/src/smhai_backend/domains/school_tasks/router.py#L54)).
  `POST /school/tasks/{task_ref}/start` uses `CsrfActor` but delegates to
  `SchoolTaskService.start_task`; that path calls
  `school_prepare_task_session`, obtains `AssessmentSession` state and returns
  the normal `TaskStartDto` ([router.py](../../09_backend/src/smhai_backend/domains/school_tasks/router.py#L295),
  [service.py](../../09_backend/src/smhai_backend/domains/school_tasks/service.py#L118)).
  This is not a research route.
- `SchoolTaskService._require` enforces `school_tenant` scope and the requested
  role ([service.py](../../09_backend/src/smhai_backend/domains/school_tasks/service.py#L31)).
  The DB adapter resolves the current persisted student account/membership and
  role from the authenticated `Actor` in
  `_school_actor_role` ([database.py](../../09_backend/src/smhai_backend/adapters/database.py#L677)).
  `_lock_school_assessment_write_scope` locks and checks active roster,
  enrollment, class, published task window, active synthetic subject, and the
  current active `SELF` grant for that account ([database.py](../../09_backend/src/smhai_backend/adapters/database.py#L449)).
  A new research use case can reuse these predicates/helpers only if the
  `SELF` grant is checked on every operation in the same transaction; do not
  rely on a repository method for actor authorization.
- The existing normal start performs its own task/enrollment lookup and rejects
  any binding other than `FIXTURE` / `SAVED_VERSION` before CAT binding
  resolution ([database.py](../../09_backend/src/smhai_backend/adapters/database.py#L1566)).
  Preserve that fail-closed boundary. `AssessmentSession` and `TaskStartDto`
  must remain normal-assessment-only.
- `SqlAlchemyUnitOfWork` exposes `uow.research_cat` and the untracked research
  repository implements profile/binding/session persistence. Its session
  methods (`create_or_load_session`, `load_session_for_resume`,
  `save_session_snapshot`, `get_session_l1_metadata`) enforce research DB scope,
  binding/profile/config hashes, session status and state-version concurrency.
  The repository explicitly does not authorize a request actor or validate a
  signed snapshot with an application-owned authenticator; the Backend use
  case must do both before returning any session projection. Its profile
  validator currently accepts schema v1/v2 only, while the CAT engine also
  recognizes a pinned v3 profile. A v3 profile therefore needs an explicit
  repository payload-schema extension before it can be persisted.
- `ResearchCATProfile.from_bytes` requires caller-supplied expected source and
  manifest hashes; `ResearchCATSession` supports start, restore, next-item,
  answer and signed snapshot operations. `SnapshotAuthenticator` is only a
  protocol at present. The engine completion object deliberately omits theta,
  SE and scores. The service integration still needs an app-managed HMAC
  authenticator; signing keys must not be stored in the database or supplied
  by the client.
- Container wiring currently has `school_tasks`, but no research service or
  research router ([container.py](../../09_backend/src/smhai_backend/container.py#L65),
  [app_factory.py](../../09_backend/src/smhai_backend/app_factory.py#L84)).
  No Backend-owned trusted research-profile registry or snapshot-authenticator
  implementation was found in the inspected integration points.
  The persistence design records the intended separate session table and
  explicitly excludes AssessmentSession, AssessmentResult, the regular
  post-assessment outbox and professional-review case
  ([RESEARCH_PERSISTENCE_SLICE.md](RESEARCH_PERSISTENCE_SLICE.md)).

## Proposed minimal student API

The paths below are relative to the configured API prefix (for example,
`{api_prefix}/school/research/...`). Keep them in a dedicated `school_research`
router/service. Require
session authentication on all routes, CSRF protection and `Idempotency-Key`
on writes, and return the existing request/trace envelope. Keep all response
models separate from `TaskStartDto` and assessment v1.

| Route | Purpose and response boundary |
|---|---|
| `GET /school/research/tasks` | List only the authenticated student's eligible research tasks, using the same active school, enrollment, roster, `SELF` subject-grant and window predicates. Return task/session lifecycle metadata only. |
| `POST /school/research/tasks/{task_ref}/sessions` | Start or resume the single research session for that active enrollment. Resolve profile/config/origin from the persisted task binding and trusted server registry; client submits no profile bytes, hashes, config, response origin, subject/account IDs or participant-row ID. Return the first question plus a `state_version` concurrency token. |
| `POST /school/research/sessions/{session_ref}/answers` | Accept `{item_id, raw_value, state_version}` only. Require a strict integer category (`bool` is invalid), current pending item, matching state version, current authorization and active profile/binding. Save authenticated encrypted snapshot and idempotency receipt in one UOW. Return the next question or an L1 completion projection. |
| `GET /school/research/sessions/{session_ref}` | Recheck current actor, `SELF`, roster, task window and binding, then return lifecycle state and the current question only while active. Never return snapshot, accepted-response history, estimates or scores. |
| `POST /school/research/sessions/{session_ref}/abandon` | Optional minimal lifecycle write using the same authorization, CSRF, idempotency and transaction rules. Return lifecycle metadata only. |

Suggested question DTO fields: `session_ref`, `profile_ref`, `profile_sha256`,
`dimension`, `item_id`, `qid`, approved stem/options, `step`, and
`state_version`. Suggested L1 status fields: `status`, `items_answered`,
`stop_reason`, `research_only`, `publication_status`, and
`psychological_interpretation_allowed`. Do not include `assessment_id`, theta,
SE, score, band, keyed response, raw answer history, ciphertext or snapshot.
Treat the item content as eligible for student display only when its rights
and research execution states permit the isolated simulation; this does not
approve operational use or psychological interpretation.

The session-start idempotency receipt must use its own resource type, such as
`research_cat_session`, and resolve replay through the research session
repository. The generic DB receipt currently stores only state, resource type
and public resource ref; it does not preserve the original HTTP response.
Therefore a replay should re-authorize and return the current L1 session
projection, rather than claim to replay a historical question verbatim.
Answer writes should bind request hash to session/item/raw category/state
version, use the receipt and `save_session_snapshot` compare-and-swap in the
same UOW, and return a conflict on changed content or stale version. A
committed receipt must not outlive a rolled-back session update.

## Authorization and trusted data flow

1. Router uses `CsrfActor` for start/answer/abandon; service requires
   `actor.scope_profile == "school_tenant"` and `actor.role == STUDENT`.
2. In one DB UOW, resolve the active persisted account and membership role via
   `_school_actor_role(..., "student", lock=True)`. Resolve the exact task,
   class, active enrollment and roster; lock/recheck the current active,
   unrevoked `SELF` grant whose `principal_account_id` is that account and
   whose subject is exactly the enrollment subject. Revalidate open/due window
   and synthetic school/subject on every write and resume. Do not accept
   account, subject, enrollment or grant identifiers from the request.
3. Resolve the `RESEARCH_PROFILE` task binding and active research profile in
   the same tenant/task/class scope. Load expected profile, manifest, fit,
   calibration and config hashes from a server-owned registry pinned to exact
   source bytes and versions. The client may identify a task/session; it cannot
   assert the trusted SHA, rights state, profile schema, population, or
   `response_origin`. Fail closed if registry material is missing, stale or
   mismatched. Pass registry SHA values to the loader and repository rather
   than trusting hashes embedded in uploaded profile JSON or a client request.
4. Create/restore `ResearchCATSession` only after scope and registry checks.
   Validate snapshot HMAC with an app-managed key before restore; then recheck
   the exact session/profile/config binding and encrypt the newly signed
   snapshot in `uow.research_cat`. Do not persist the HMAC key in DB. Do not
   return the snapshot or its answers.
5. Keep ordinary task start unchanged and rejecting `RESEARCH_PROFILE`.
   Research sessions never create normal `AssessmentSession`,
   `AssessmentResult`, `SchoolPostAssessmentJob`, or
   `SchoolProfessionalReviewCase`. This slice creates no L2/L3 publication
   behavior and no ordinary assessment outbox work.

### Public-response boundary

Profile schema/version and response origin are separate fields with distinct
meanings:

- `psynova.research-profile.v2` or `.v3` describes the candidate profile
  document format. It is not the source dataset version, rights approval,
  calibration validation or population approval.
- `PUBLIC_OBSERVED` or `MODEL_GENERATED` is the server-controlled origin of
  responses attached to a research task binding. It is not a profile schema
  version.

The 800-row public response-only artifact and the 800 fictional roster
accounts are separate assets. The roster generator explicitly records that it
does not copy response rows or create an account-to-row mapping. Thus the
ordinary student answer route must never silently feed public observed rows as
that logged-in student's answers. For the minimal interactive slice, bind
student-entered responses only to that active student's research session and
use a server-controlled synthetic/research binding. Synthetic account
provisioning remains the existing separate roster/admin workflow; this API
does not create accounts or bind response records during provisioning. If a later experiment
replays `PUBLIC_OBSERVED` rows, provide a separately authorized harness with
research provenance visible in its outputs; do not attach source participant
rows to account identity or represent replay as a student's own psychological
responses. `MODEL_GENERATED` likewise cannot be selected by the caller.

## Implementation ownership map and remaining work

| Area | Likely owner files | Work not present in inspected source |
|---|---|---|
| HTTP/DTO | New `09_backend/src/smhai_backend/domains/school_research/{router.py,schemas.py}` | Add the dedicated routes, strict DTOs, CSRF/idempotency and L1 projections. |
| Domain | New `domains/school_research/service.py` | Role checks, trusted registry resolution, session lifecycle and CAT adapter orchestration. |
| DB adapter | `09_backend/src/smhai_backend/adapters/database.py` | Add dedicated research operations inside one existing UOW; explicitly validate actor/SELF/task scope and research receipt replays. Do not alter normal `school_prepare_task_session` semantics. |
| Container/app | `09_backend/src/smhai_backend/container.py`, `app_factory.py` | Inject research service/registry/authenticator and include the router; lifecycle must not start a new service or worker for this slice. |
| Research repository | `11_database/database_layer/school_research_cat.py` and focused tests | Existing session/profile persistence exists, but its profile schema whitelist is v1/v2; add pinned v3 only if this slice uses that profile. Preserve strict trusted-hash parameters and repository non-authorization boundary. |
| Trusted runtime config | Existing D-drive/server-managed research registry/config, not request DTO | Define exact registry source, key management, rotation and failure behavior. No client-supplied digest is a trust root. |
| API tests | New focused Backend research route/service tests | Test SELF/revocation/cross-tenant/window denial, profile/hash/signature mismatch, idempotent replay/conflict, stale state version, normal-start rejection, no normal assessment/outbox writes, and response DTO exclusion of estimates/raw history. |

## Decision boundary

Integration review: the first persistence/API slice is explicitly v1/v2 only.
PROMIS v3 retains raw `not_approved`, a longer dimension description and published
rounded parameters with no locally fitted calibration artifacts. A later schema
must represent published parameter provenance and stable dimension identifiers
explicitly; never label a crosswalk hash as a local fit or fabricate calibration
hashes to satisfy0012. Preserve original source bytes when normalizing only the
safe negative publication projection. No v3 operational compatibility is claimed.

This is an engineering route proposal, not an approval of source rights,
psychometric properties, age/population suitability, student use, professional
feedback or school deployment. The minimal student API supports an isolated
research L1 workflow only. Any public-response replay, account mapping,
professional review, L2/L3 result, RAG/LLM output, or production path needs a
separate scoped design and its own approval/evidence. No service, database or
GPU was started or modified for this note.
