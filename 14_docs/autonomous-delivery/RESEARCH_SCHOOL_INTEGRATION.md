# Research-purpose school CAT integration

Date: 2026-10-14. Status: `SOURCE SURVEY / DESIGN ONLY`.
Source checkout: `xiajiadi/autonomous-delivery-20261011`, HEAD
`eeeba189c90aca4091396080cd54a3dd85959d33`.

This design targets an end-to-end **synthetic-account research demonstration**:
800 fictitious school users authenticate, take a CAT built from public IPIP
items and explicitly research-only SAPA-derived parameters, then enqueue a
bounded education-support attempt and make a held candidate available for
assigned specialist review. It is not a school pilot, student-data study,
psychometric approval, clinical workflow, or authorization to publish feedback.
No code, service, database, account, index, or GPU was changed or run for this
survey.

## Decision

Reuse school identities, classes, task enrollment and access checks; encrypted
response persistence; `UnitOfWork`; transactional idempotency/audit; the durable
post-assessment lease queue; the existing Safety, RAG and 7B clients; and
task-scoped specialist assignment. Add a separate research-profile binding and
CAT-session adapter. Do not represent SAPA parameters as `synthetic`, use the
school saved-bank/activation path, bypass `ItemBank.assert_runtime_ready()`, or
change the frozen `assessment.v1`, `api.v1`, or published-bank rules.

The current public observed-response split cannot support 800 completed
adaptive sessions. The parity-gated observed replay completed only 1, 1, 8, 59,
and 29 paths across the five domains because MFI often selected an item that was
planned-missing in a respondent's source record. Preserve those NAs and stop
that profile's replay; never impute or silently choose a replacement. If the
acceptance requires 800 *completed* fictional accounts, use the distinct
`model-generated` simulation mode: real public item wording and research-fit
curves, with responses generated from those curves and clearly labelled as
virtual. This is an engineering scenario, not observed respondent answers or
school-student evidence.

## Facts at this source revision

| Area | Existing source fact | Integration consequence |
|---|---|---|
| Synthetic accounts | The current-state record reports 800 fictitious accounts authenticated and school-scoped in an isolated workspace, while recording zero assessment sessions at the captured checkpoint. | Account/login evidence is reusable; it is not CAT, 800 completion, RAG, model, queue, or review acceptance. Reconcile counts again in the eventual target workspace. |
| School tasks | `MeasurementTask.cat_binding_mode` and `AssessmentSession.cat_binding_mode` permit only `FIXTURE` and `SAVED_VERSION`; tasks bind school/class/enrollment and use server-side actor checks. | Add an explicit `RESEARCH_PROFILE` binding or a separately scoped research-task binding. Do not encode it as `FIXTURE` or a saved/published school bank. |
| Saved CAT assets | Internal CAT asset documents require `SyntheticMetadata(synthetic=true, intended_use=engineering_test_only, psychological_interpretation_allowed=false)`. `SchoolCatActivation.purpose` is constrained to `SYNTHETIC_ENGINEERING`; saved plans bind exact versions. | Those validators and activations are for synthetic engineering assets. A public-source bank with research estimates is not eligible, even though the school accounts are synthetic. |
| CAT runtime | `Session.initialize()` calls `ItemBank.assert_runtime_ready()`. `AdaptiveTestingProvider.start_session()` also calls it; `CATProvider` accepts `ItemBank`. Research runner code calls mature `adaptivetesting` MFI/EAP/GRM objects directly and never constructs an online `ItemBank` or `Session`. | A research adapter can reuse library item-selection/estimation and persistence primitives, but cannot enter the unchanged online `Session` path by relabelling a bank. Keep the existing published path untouched. |
| Encryption and transaction | `AssessmentResponse` and `AssessmentResult` store versioned ciphertext. `SqlAlchemyUnitOfWork` wires assessment, audit, idempotency and `post_assessment_jobs` repositories in one transaction. The school assessment-save path rechecks task binding and writes the completed result and job in that UOW. | Reuse the UOW and crypto provider. Give research results an explicit research DTO/table or keep estimates out of standard `assessment.v1`; do not leak unapproved research estimates through a normal Assessment response. |
| Durable queue | Migration `20261014_0011` adds `school_post_assessment_jobs`, tenant/task/enrollment/session composite FKs, lease constraints and idempotency key `(school_id, assessment_session_id, job_kind, policy_version)`. Current DB `job_kind` check is exactly `EDUCATION_SUPPORT`. The worker reauthorizes before processing, requires qualified source metadata and policy hash, and defaults to a fail-closed processor that abstains. | Reuse lease/retry/UOW mechanics. Add a separately dispatched research job purpose/kind and processor; do not weaken the standard job qualification predicate or assume a queued job calls RAG/LLM. Keep current `ABSTAINED` behavior until all independent gates pass. |
| RAG | Independent student retrieval only accepts `university_freshman` or `university_student`, and filters `role_scope=student`, `review_status=approved`, `rights_status=verified`, and the exact population. Existing approved publication is K-12-only; current university candidate materials remain pending review. | A university query currently returns no eligible university evidence and must abstain. Do not relabel K-12 chunks, auto-approve KPU/OpenStax, call the 7B without eligible citations, or invent a normal answer. |
| Review/publication | Task-scoped specialist cases bind a completed assessment and assignment; case state includes `OPEN/IN_REVIEW/APPROVED/REJECTED`. Existing `school_feedback_records` are constrained to `level='L3'` and `synthetic_only=1`; there is no L2 preapproved catalogue. | A reviewer decision is not validity or L2 approval. Held research output must remain private; do not use the synthetic-only feedback table to publish research-derived output. |

Source pointers: `11_database/database_layer/models.py:477-570,636-737,1015-1137,1140-1184,1468-1584,1615-1715`; migration
`11_database/migrations/versions/20261014_0011_post_assessment_job_outbox.py`;
`11_database/database_layer/unit_of_work.py:27-70`;
`09_backend/src/smhai_backend/adapters/database.py:1566+,2408-2515`;
`09_backend/src/smhai_backend/domains/school_tasks/service.py:90-155`;
`09_backend/src/smhai_backend/domains/post_assessment/service.py:191-235,530-604`;
`01_cat-engine/src/cat_engine/domain/session.py:38-106`;
`01_cat-engine/src/cat_engine/providers/adaptivetesting_provider.py:57-101`;
`01_cat-engine/src/cat_engine/research/empirical_cat_replay.py`;
`05_rag-engine/src/rag_engine/independent.py:80-130,138-195`;
`14_docs/autonomous-delivery/UNIVERSITY_KNOWLEDGE_INTAKE.md:8-16` and
`14_docs/autonomous-delivery/EMPIRICAL_CAT_REPLAY_PROTOCOL.md`.

## Public material, profile, and response semantics

The acquired source is SAPA v3.0 / Harvard Dataverse DOI
`10.7910/DVN/C40K1U`, reported `CC0-1.0`; sample population is
“Self-selected Internet respondents” (2010–2013), not a university cohort,
school norm, clinical sample, or student gold standard. The response-only
artifact has 128,464 source records and 99 exact-key IPIP response columns;
demographics and source participant IDs were excluded. `q_1483` is excluded
because the source stem did not exactly match the official key. IPIP's official
item pages describe copying/modifying/translating/using the items; preserve
item-level attribution, source URL, text hash and license separately from the
SAPA response-data license. Do not assume the dataset license alone governs
every item, fit, adaptation or downstream distribution.

Current fits are five independent one-dimensional mirt graded-response models,
not a five-dimensional model: Agreeableness 20 items (14 positive / 6 reverse),
Conscientiousness 19 (11 / 8; `q_1483` excluded), Emotional Stability 20
(5 / 15), Extraversion 20 (10 / 10), and Intellect / Imagination 20 (13 / 7).
They are research point estimates (1D graded, Gaussian N(0,1), EM, 41
quadrature points, no parameter SEs) from 10,000 calibration records. Exact
source category/key mapping is preserved: raw categories 1..6; reverse-key
score index `6 - raw`, positive-key index `raw - 1`; missing remains missing.
No `q_1483` substitute, common five-trait score, diagnosis, risk threshold,
high-school norm, or college-population claim is supported.

Use two explicitly different simulation modes:

| Mode | Input | Missing and completion rule | What 800 accounts can demonstrate |
|---|---|---|---|
| `OBSERVED_PROFILE_REPLAY` | One-to-one, deterministic assignment of the 800 held-out response-only profiles to 800 fictitious accounts; retain a split-manifest hash and seed. Never persist source participant IDs, source row offsets, or whole rows in school DB/logs. | A selected source NA censors the path immediately. Do not impute, record it as a student's skip, or reselect. | Login, task scope, assignment mapping and observed-coverage/censoring. Does not meet 800 completed CAT sessions with the existing split. |
| `MODEL_GENERATED_RESEARCH` | Each fictitious account gets a deterministic synthetic theta seed and responses sampled online from the exact research GRM curves. Record `response_origin=MODEL_GENERATED`; do not call it an empirical SAPA response. | Generate a category for each selected item; no public respondent row is assigned. Errors stop the path and are counted. | End-to-end CAT completion and queue recovery with real public item text/research curves, subject to all unapproved-research labels. Not observed-data accuracy or an approved instrument. |

In observed mode, the selected observed ordinal response necessarily enters that
session's encrypted response record so the CAT can update and resume; only the
selected cells are submitted. Retain no full source row or row-to-account map in
school persistence/logs. Reconstruct assignments in the external run harness
from the fixed response-only split, seed and deterministic roster ordering.

The existing small candidate used min 3/max 8 and SE 0.55; all 16 forward
Extraversion cases stopped after 3 items. This is an unapproved engineering
candidate, not a professionally selected CAT length/threshold. A full five
domain profile would require five separately bound one-dimensional tasks per
fictional account (up to 4,000 sessions). Do not describe it as one joint
99-item or five-dimensional CAT.

## Minimum isolated product path

```mermaid
sequenceDiagram
    participant A as Synthetic school account
    participant B as Backend research-task lane
    participant C as Research CAT adapter
    participant D as School DB/UOW
    participant W as Research outbox worker
    participant R as Safety + eligible university RAG + local 7B
    participant P as Assigned specialist
    A->>B: login, choose research-purpose task
    B->>D: resolve synthetic school, SELF subject, roster, enrollment, task/profile version
    B->>C: start/resume exact RESEARCH_PROFILE session
    C-->>A: current public item and ordered 1..6 options
    A->>B: answer via scoped, idempotent response command
    B->>D: encrypt response; commit session state
    A->>B: complete
    B->>D: persist encrypted research result + unique research job in one UOW
    D-->>A: L1 completion only
    W->>D: claim one job with existing lease; reauthorize current scope
    W->>R: generic task-topic query; no CAT score/raw answer
    R-->>W: cited candidate, ABSTAIN or safety/review route
    W->>D: persist encrypted candidate/aggregate status
    P->>D: assigned-scope manual review; candidate remains held
```

### Profile and task binding

Create immutable, versioned research tables, not a `school_cat_item_banks`
version. Proposed lifecycle is `CANDIDATE_RESEARCH_ONLY` ->
`SIMULATION_ENABLED` -> `DISABLED`; `SIMULATION_ENABLED` means only that an
isolated engineering simulation may run, never that an instrument or output is
professionally approved. Keep distinct `rights_status` (`pending`, `verified`,
`revoked`), `psychometric_status` (`unreviewed`, `reviewed_research_only`,
`not_validated`), and source `population_scope` fixed to
`adult_sapa_self_selected_internet`. There is no generic profile `approved` or
`published` state. Minimum `ResearchCATProfile` metadata: opaque profile/version refs;
purpose `PUBLIC_EMPIRICAL_RESEARCH`; fixed `research_only=true`,
`publication_status=not_approved_for_publication_or_operational_use`,
`human_curated=false`, `psychological_interpretation_allowed=false`;
instrument/domain and exact item count; source dataset DOI/license/population;
item-text source/license/attribution; response split and calibration/evaluation
hashes; key/crosswalk hash; mirt method/version/fit hash; category and
reverse-key maps; missing policy; parameter hash; allowed execution modes; and
independent rights, content, psychometric and technical review states. Store the
item/parameter payload as immutable encrypted JSON or a content-addressed,
access-controlled artifact with verified hash. A source record ID, raw
response row, personal theta, or respondent demographics must never be in this
profile.

Add task purpose `RESEARCH_SIMULATION` and add `RESEARCH_PROFILE` as a distinct
task/session binding mode, or use a new
`SchoolResearchTaskBinding`/`ResearchAssessmentSession` pair with composite
school/task/enrollment/subject FKs. Bind exactly one immutable profile version,
one dimension and one response mode at task creation. Do not create
`SchoolCatActivation`, `SchoolCatTaskBinding`, or
`SchoolCatSessionBinding` for this path: the existing activation is restricted
to `SYNTHETIC_ENGINEERING`. Existing account, roster, membership, enrollment,
login/session, CSRF and idempotency records remain `SYNTHETIC`; only the
instrument/profile is public-source research.

Keep standard `assessment.v1` frozen. It represents results for registered
tools and is consumed by normal support; it is not a safe carrier for
unapproved SAPA trait estimates. Use a separate strict `research-assessment.v1`
result DTO/table with source population `adult_sapa_self_selected_internet`,
research profile/version hashes, one-domain estimated values if persistence is
needed, `research_only=true`, and no psychological interpretation. Return the
student only a research-task completion projection (task/session state and item
count), not theta/SE/band or trait labels. If the research demo does not need
score persistence, omit estimates entirely and keep the adapter state ephemeral.
Reuse Fernet format/key-version/schema-version fields, `AssessmentResponse`
encryption semantics, UOW, audit and idempotency machinery; never write research
values as a normal `AssessmentResult` and expose them through `/assessments`.

### API and role scope

Add an additive, versioned research router, outside the frozen `api.v1`
contract. Suggested resources (exact names remain Controller-owned):

| Operation | Required server-side scope | Response boundary |
|---|---|---|
| Create/import profile version and create research task | Explicit research-operator capability in the isolated environment; active `SYNTHETIC` school; profile hash/schema checks; existing same-school admin/task boundaries. | Profile and task provenance only; no source row or response export. No published/saved-bank routes. |
| List/start/resume/answer/complete | Authenticated `STUDENT`; current active school context, SELF grant, same-school class roster, active task enrollment, task window, exact profile-version binding. CSRF and durable idempotency on writes. | Current item/category options, accepted response state, final L1 completion metadata only. No self-selected profile ID or answer sequence in general history. |
| View class progress | `TEACHER` Scope A; exact assigned same-school class/task. | Counts and lifecycle only; never individual answer, parameter estimate, public profile mapping, candidate text or review note. |
| Read/review held cases | Currently assigned same-school psychological specialist, task/enrollment/assessment scope checked on every read/write, expected state version + CSRF/idempotency. | Exact held candidate, eligible citations and research caveat only as required for review. No task-wide or cross-school access. Admin sees operations metadata only. |

The existing student school task routes (`/api/v1/school/tasks/student`,
`/tasks/{task_ref}/start`) and completion/response routes can be extended only
through a server-validated `RESEARCH_PROFILE` binding branch. Do not trust a
client-supplied purpose, item bank, population, fit hash, score, profile ID or
approval flag. A distinct research router/DTO is easier to audit and avoids
letting research fields drift into the ordinary assessment or school-plan API;
it should still call existing authorization, roster/enrollment and UOW services
rather than clone their implementations.

### Queue, RAG, model and review

On research completion, atomically save the encrypted result/session state and
enqueue exactly one research education job. Reuse the current lease, bounded
retry, audit and same-UOW pattern, but add a non-overlapping job purpose/kind and
processor. Current `job_kind='EDUCATION_SUPPORT'`, default processor, and
qualification checks remain fail-closed. Bind job to the exact research task,
profile version, run mode, policy hash, source snapshot and source population;
do not place response text, scores, theta, prompt or candidate body in the job
row. Reauthorize the live school/task/enrollment/session before each claim and
before any finalization. Concurrency stays bounded; 800 enrolled accounts do
not imply 800 simultaneous Ollama requests.

For the education-support leg, send a fixed generic task-topic query (for
example, planning a study schedule), never the CAT score, item answers, source
profile mapping, diagnosis-like trait label or raw assessment. Preserve
input-safety -> eligible retrieval -> retrieval-safety -> local 7B -> output
safety/claim/citation validation. The current independent RAG filter only
returns `approved` + `verified` university chunks. The KPU source package is
still `pending_review`; OpenStax College Success Concise has a current-source
AI-ingestion restriction/licensing conflict; neither may be force-approved or
added by this task. Therefore today's expected ordinary research-job outcome is
`ABSTAINED/SOURCE_UNQUALIFIED` or `ABSTAINED/POLICY_UNAVAILABLE`, with no model
call. An engineering-only synthetic RAG fixture can validate plumbing but is
not real educational evidence and must not satisfy citation acceptance.

When a genuinely eligible university corpus exists, save only a vetted,
citation-bound candidate in an encrypted held-candidate resource. Create a
task-scoped review case and require a currently assigned specialist to inspect
it. Student remains at L1 completion while the candidate is held. The case may
remain `OPEN`/`IN_REVIEW`; no queue completion, reviewer action, demo switch, or
backend seed can manufacture `APPROVED`, `PUBLISHED`, L2 or psychometric
validity. Do not use `school_feedback_records`: it is deliberately L3 and
`synthetic_only`. No personalized student-visible generated text is released
until a separately approved content/policy/publication route exists.

## Crisis, skip, and save/resume rules

- IPIP/SAPA personality items are not crisis items or validated safety
  screeners. Do not add a compulsory suicide/self-harm item, infer crisis from
  these traits, or invent a threshold. Use the existing Safety circuit breaker
  and its separately approved configuration; a crisis event halts ordinary
  RAG/LLM and routes the existing approved safety response. Synthetic injected
  crisis tests are separate from public-profile response mappings.
- In `OBSERVED_PROFILE_REPLAY`, selected source NA means the source participant
  was not observed answering that item; censor the profile run. Do not treat it
  as a school student's `record_missing`, count it as a scored response, or
  silently reselect. In `MODEL_GENERATED_RESEARCH`, each presented item gets a
  generated ordinal category; any generation failure is explicit, never
  backfilled.
- Persist task/profile-version binding and response sequence atomically with
  stable idempotency; duplicate answer/completion returns the same recorded
  outcome and changed-body replays conflict. On resume, revalidate school,
  account, SELF grant, roster, enrollment, task window and active immutable
  profile hash. A changed/revoked profile version cannot replace the session's
  original binding. Resume from encrypted recorded responses and provider
  checkpoint; do not reconstruct by querying a different public profile row.
- Record only aggregate research run counts/hashes in scenario manifests. No
  raw answer arrays, participant source IDs, per-student theta, prompt, review
  note, or full candidate in ordinary logs. Existing encrypted response storage
  remains retention-governed; generated research results need separate
  retention/deletion rules before running the large scenario.

## Approval and readiness boundaries

| Decision | Required evidence / decision maker | Current state |
|---|---|---|
| Item/response-data rights and attribution | Rights owner/qualified institutional rights reviewer verifies both IPIP item license and SAPA CC0 dataset scope for storage, derived parameters, display, citations and distribution. Preserve each independently. | Existing source manifest supports the stated licenses; this is not a final distribution/legal approval. |
| Parameter/model suitability | Qualified psychometrician reviews one-dimensional model assumptions, planned-missing mechanism, item fit, parameter uncertainty, cross-validation, dimensionality, differential functioning and stop rule for the intended use. | Current fits are research-only point estimates; adult self-selected population; not approved for university/school use. |
| RAG education content | Rights reviewer verifies source terms; university learning-content reviewer qualifies exact population and topic, attribution and adaptation; Knowledge reviewer separately records rights and professional content decisions. | University RAG corpus has zero eligible university chunks. Current KPU/OpenStax candidates remain pending/blocked. |
| Crisis policy | Authorized Safety/clinical professionals approve crisis rule and local response content; test against separated synthetic fixtures. | Public personality data is not crisis evidence. No new crisis item/threshold is proposed. |
| L2/student publication | Qualified professionals approve an exact population-specific policy/catalogue, allowed inputs, citations, claims and revoke path; Controller approves engineering publication path. | L2 catalogue does not exist. Student output stays L1 while held. |
| Real people/school deployment | Separate ethics/IRB, legal, institutional and school authorization, consent, privacy/retention and operational deployment decisions. | Not in scope; all 800 account identities remain fictitious and data-origin `SYNTHETIC`. |

## Implementation slices and acceptance evidence

1. **Research asset contract (01 CAT + Controller):** add strict immutable
   `ResearchCATProfileVersion` and `research-assessment.v1`, explicit status and
   source/item/fit/mode hashes; validate domain item IDs, direction maps,
   categories, parameter finiteness and profile source population. Negative
   tests prove it cannot be submitted to ordinary `ItemBank`, published bank,
   saved plan or activation routes.
2. **Persistence binding (11 Database):** additive migration for research
   profile versions, task/session binding and encrypted research result, with
   composite school/task/enrollment/subject FKs, unique assessment/profile
   binding, immutable versions and downgrade refusal after business rows.
   Preserve all `FIXTURE`/`SAVED_VERSION` constraints and pre-existing rows.
3. **Research CAT session lane (01 CAT + 09 Backend):** adapter uses
   `adaptivetesting` MFI/EAP/GRM mechanics without entering published
   `Session.initialize()`/`ItemBank` admission. Add exact-profile start,
   select, ordinal answer, save/resume, complete and duplicate/reordered
   request handling. No client-selected model, source row, score or profile.
4. **School authorization and task flow (09 Backend + Frontend):** authenticated
   800 synthetic accounts, exact class/enrollment binding, CSRF/idempotency,
   current authorization at every operation, clean student-facing research
   notice and L1 completion. Assert teacher Scope A counts only, admin
   operations-only, and specialist Scope C assigned task only; negative tests
   include other school, unassigned specialist, teacher, admin and revoked
   student.
5. **Research outbox and support processor (09 Backend + 11 Database + 05 RAG
   + 06 Runtime + Safety owner):** one research job per completed session in
   the same UOW; restart/lease/idempotency tests; no score/answer in worker
   input; source qualification fail-closed; valid citations and normal 7B
   answer only when an approved university corpus exists; pending/zero evidence
   makes zero model calls; crisis blocks retrieval and generation.
6. **Held review and scenario run (09 Backend + reviewer workflow + Controller):**
   candidate ciphertext/citations, assigned reviewer access and immutable
   version transitions; student sees only L1 before any separately approved
   publication. Browser and native DB proof reconciles exactly 800 synthetic
   accounts, task enrollments, starts, responses, completed sessions, jobs,
   held/abstained/review cases and terminal outcomes. Run both response modes
   separately; report observed censoring and model-generated completion without
   combining evidence. Measure 7B single-concurrency queue latency, restart and
   restore; do not infer clinical, population or product readiness.

Before a future full 800 run, select one mode and domain count, retention policy,
review workload and expected queue disposition. Under the current source
eligibility, a normal RAG/7B answer is blocked; the system should still show a
valid held/abstained outcome rather than fabricate a citation. A later approved
university corpus and qualified human decisions can unblock the grounded
education-support leg without changing any published CAT-bank gate.
