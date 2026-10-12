# Exact saved CAT version execution

Controller direction, 2026-10-13 Beijing. Base2958383c. Required next steps remain
saved-version simulation → controlled synthetic activation → immutable task/session
binding and version-keyed runtime. This document specifies simulation first without
calling that smaller slice the complete CAT or four-role delivery.

## Saved simulation

POST /api/v1/school/cat-assets/plan-versions/{CPVER_ref}/simulations with strict
{n_examinees:100|1000}, default100; no seed override. Authenticated school specialist,
CSRF and exact current school scope required. It is stateless computation, creates
no business resource and needs no idempotency key or automatic retry.

Resolve the exact immutable plan version and referenced bank version in a short
fresh UOW; both parent resources must be ACTIVE, else409. Unknown/cross-school404.
Decrypt only those documents, close the UOW, invoke real CAT computation, then
recheck current persisted role and parent scope/state before returning; success
metadata audit shares this final UOW. Revoked access during computation must not
return results. No transaction held across network/CPU work. No response cache,
fake aggregates, background durable-job claim, report or per-examinee records.

Public response:
engineering_only:true, psychological_interpretation_allowed:false,
plan_version_ref, bank_version_ref, item_bank_id, item_bank_version,
config_version, n_examinees, seed, metrics{bias,rmse,mae,mean_test_length,
median_test_length,mean_se}, stopping_reason_distribution.
Strict finite/count validation; exact batch/seed/document identity matches the
resolved saved versions. References identify saved versions even when their
source document version strings are the same as a cloned fixture.

Internal POST /internal/cat/management/simulate-assets accepts
{bank_document,config_document,n_examinees}. Uses the same strict bounded document
validator as asset CRUD, but requires config and bank.assert_runtime_ready().
Draft documents are not silently promoted or normalized to published. The current
published synthetic source cloned by the editor is eligible for independent
engineering simulation; this is not permission to use it in student tasks.
The saved payload/config never change, seed remains exact, provider is separate,
and runtime item_bank/config/sessions are untouched.

## Current evidence

Controller ENGINEERING_PASS for this saved simulation slice, 2026-10-13 Beijing.
Native source workspace0008 logs/saved-cat-simulation-http-
a1b314eb80c54e90801c3e06994ac0f6.json proves exact immutable versions, actualN100
repeat, changed max-items6→3/mean length6→3, N1000 in93.719s, shared409 gate,
role/school/CSRF/strict input denials and unchanged live CAT session count.
logs/saved-cat-midrun-archive-fd7722b8dfc34be7af678039989b74c4.json proves actual
archive during computation denies results with no success audit.
Browser17 stages pass at browser-qa/20261012T175313Z-9da075fdc5a0432f8076d3edcdf23b04;
Controller inspected masked desktop/mobile. Three actualN100 runs match API/DOM,
repeat and unsaved-edit isolation; history switch clears results. Fresh suites:
Backend435, CAT63, Frontend204 plus lint/build; harness Python14/Node12.
Read-only independent source review found no conclusion-changing defect.

Earlier failed browser artifacts remain preserved. They exposed wrong harness
POST-status/key/tab assumptions, unhandled response waits and a real initial-load
tab race. Loading locks and a deferred bank-detail regression fix that product
race. Aggregate extraction now tests the actual projection and separate sibling
source binding. No success interception, fake result, weakened comparison or reset.
This is not task activation, student execution, psychometric validity, professional
publication, install/reboot proof or whole-product ENGINEERING_DEMO_READY.

Reuse one simulation admission lock across existing fixed-fixture simulation and
saved-document simulation. Only one CPU computation at a time; busy409, no hidden
queue. Cancellation retains the lock until actual worker completion and consumes
its outcome. Current management-only600s budget also applies to this computation;
asset template/validation stays30s and ordinary assessment/LLM/Safety unchanged.

The specialist selects a saved plan/history version explicitly and runs its100 or
1000 batch; results show exact bank/plan version labels and aggregate metrics.
Changing version, parent or school context clears old results; unknown outcomes
require an explicit new run, no silent rerun. Repeats compare only matching saved
references, sample size and seed. Show real pending/busy/denied/unavailable states.

## Evidence and following activation/binding work

Required: fixed-fixture regression, strict documents/batches, shared busy/cancel
gate tests; real saved-version100 repeat and changed config demonstrating actual
parameters; native role/scope/CSRF/archive checks and unchanged live session count;
browser select/history/run/compare with API metrics and desktop/mobile inspection.

Next activation must be an explicit synthetic engineering action attached to an
immutable plan version, with metadata audit, current role, version concurrency and
idempotency. It grants eligibility for a specifically bound synthetic task, not
professional approval or L2/L3 publication. Add same-school FK bindings to task
and assessment session, preserve existing fixture sessions with null bindings,
and load immutable version documents on restore/restart. All active sessions
retain their original version when newer assets are created or archived. Do not
change frozen assessment.v1 or silently select the latest version.
