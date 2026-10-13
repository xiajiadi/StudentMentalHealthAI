# SAPA observed-answer CAT replay protocol

Date: 2026-10-14. Status: `DESIGN_ONLY`. This protocol describes two offline
research experiments. It does not authorize item-bank publication, school
activation, database writes, student assessment, or interpretation of traits.

## Decision summary

Use the 800-record disjoint evaluation split for a **retrospective observed-answer
replay**. The replay asks which CAT items the current scalar engine would select
when it receives real answers already present in the non-adaptive SAPA response
matrix. It does not recover the answers that would have been given to items the
source respondent never received.

Separately, use the five mirt one-dimensional fits to drive an **800-case-per-domain
model-generated forward simulation**. Those responses are generated from the
fitted item curves and a declared synthetic theta distribution. They are virtual
cases, not the 800 evaluation respondents. The two experiment results must remain
separate in files, manifests, metrics, and conclusions.
The proposed forward design is five independent domain runs (800 virtual cases
each; 4,000 scalar trajectories total), not 800 joint five-domain profiles.

Do not load either research bundle through the school bank/plan API. The current
CAT provider and session state machine reject banks whose status is not
`published`; the school asset API accepts only explicitly synthetic engineering
documents. Do not assign `published` or `synthetic=true` to SAPA-derived research
parameters to get past those checks.

## Evidence inputs and exact item mapping

The source is SAPA v3.0, Harvard Dataverse DOI `10.7910/DVN/C40K1U`, license
`CC0-1.0`, population “self-selected Internet respondents”; it is not a validated
school cohort. The response-only extraction keeps 99 exact-key IPIP columns from
128,464 source records and drops demographic and identifier fields. The seeded
reservoir split (`20261013`) is disjoint: 10,000 calibration records and 800
evaluation records. Calibration SHA-256 is
`449f63d363f953eff69d5478fb6d404d77b4da1da6a6275c63858a89dd959c23`; evaluation
SHA-256 is `abb772d4f6566e6e29cb80d26a9f26c9092d94bfaadd397cb15feb5a442a8054`.
The durable split evidence is
`D:\Dev\datasets\psynova-public-research\derived\sapa-ipip99-20261013-v1\manifest.json`.

Use each fitted domain as its own scalar GRM. Do not combine the five fits into a
five-dimensional bank or share theta across them.

| Domain | Exact-key items | Positive / reverse | Held-out records with at least 8 observed domain answers | Held-out all-missing |
|---|---:|---:|---:|---:|
| Agreeableness | 20 | 14 / 6 | 490 / 800 | 6 / 800 |
| Conscientiousness | 19 | 11 / 8 | 480 / 800 | 7 / 800 |
| Emotional Stability | 20 | 5 / 15 | 482 / 800 | 18 / 800 |
| Extraversion | 20 | 10 / 10 | 485 / 800 | 17 / 800 |
| Intellect / Imagination | 20 | 13 / 7 | 482 / 800 | 10 / 800 |

Conscientiousness is the exact-match 19-item subset: `q_1483` was excluded
because no official-key wording match was found. Do not restore it by semantic
guessing. The category labels in the acquired codebook are:

| Source code | Option label |
|---:|---|
| 1 | Very Inaccurate |
| 2 | Moderately Inaccurate |
| 3 | Slightly Inaccurate |
| 4 | Slightly Accurate |
| 5 | Moderately Accurate |
| 6 | Very Accurate |

The mirt fits were calibrated from `calibration.csv`; they are mirt 1.47,
unidimensional graded, EM, Gaussian N(0,1), 41 quadrature points, `SE=FALSE`.
The five fit manifests and item parameters are under
`D:\Dev\datasets\psynova-public-research\R-runtime\mirt-crosscheck\domains-20261014-final\`
for Agreeableness, Conscientiousness, Emotional Stability and Intellect / Imagination.
Extraversion is the separate
`D:\Dev\datasets\psynova-public-research\R-runtime\mirt-crosscheck\mirt-extraversion.json`.
The five-fit batch hash/provenance manifest is
`D:\Dev\datasets\psynova-public-research\R-runtime\mirt-crosscheck\mirt-remaining-domains-20261014-final.json`.
Every fit is point-estimate research output with no parameter standard errors.

### Response direction and category scores

Preserve the original six source labels for every item. The current CAT provider
uses categorical indexes `0..5`, not SAPA's numeric `1..6` values. Map:

- Positive-key item: `keyed_value = raw_value`; provider score is `raw_value - 1`.
- Reverse-key item: `keyed_value = 7 - raw_value`; provider score is
  `keyed_value - 1`, equivalently `6 - raw_value`.
- Missing source cell: keep `None`/NA. Never convert it to zero, a midpoint,
  the reverse of a missing code, or any of the six response scores.

For example, a reverse-keyed raw `1` (“Very Inaccurate”) is score index `5`,
while a positive-keyed raw `1` is score index `0`. A reverse-keyed raw `6` is
score index `0`; positive-keyed raw `6` is index `5`. Match the source option
label to the contiguous scoring map, then pass the resulting index to the
provider. Passing raw `1..6` as the provider index is wrong: the provider accepts
only indexes `0..5`, so raw `6` is invalid and raw `1..5` would be mis-scored.

Before using mirt parameters in the CAT provider, require a direct probability
parity check for every item at a fixed theta grid and all six categories. The
provider maps `a` and thresholds directly into `adaptivetesting` GRM items; the
installed `adaptivetesting` source computes category probabilities with a
logistic graded-response form. Correlated mirt/GIRTH parameter estimates do not
prove mirt/`adaptivetesting` probability parity. If the parity check fails, stop
and resolve the link/parameterization mapping; do not silently multiply slopes
or thresholds by a guessed scale constant.

## Evidence semantics

| Experiment | Responses and item selection | Supported evidence | Not supported |
|---|---|---|---|
| Observed-answer replay | For each held-out record, the full domain bank is eligible. Run MFI from the start and submit only the actual observed answer for the selected item. If the selected item is NA, censor that replay immediately. | Selection mechanics on a subset of actual recorded answers; source-coverage, censoring, stop and item-exposure counts. | What the respondent would have answered to an unobserved item; estimation bias/RMSE against a true theta; prospective adaptive-test effectiveness. |
| Model-generated forward simulation | Draw theta from the predeclared synthetic range and generate each selected answer from the mirt parameterized GRM. The recommendation is 800 independent virtual cases **per domain**, seed `20261014`, theta Uniform(-2.5, 2.5) to match `SimulationRunner`'s current default range. This range is an engineering stress range; it differs from the calibration fit's Gaussian N(0,1) prior and must not be called an empirical population distribution. | Software/model recovery metrics relative to generated theta; stopping and item-exposure summaries under this generator. | Empirical SAPA accuracy, student norms, school representativeness, or independent validation. The response generator and estimator share the fitted model, so this is a model-consistency simulation. |

Observed replay must retain all 800 as the accounting denominator, including
all-missing records and those censored at a selected-but-unobserved item. An
unobserved planned-missing item was not administered in the source survey. It is
not an unanswered CAT item: do not call `Session.record_missing()`, do not select
a different item to replace it, and do not impute. Report completed paths,
censoring before/after the minimum length, and the observed-item coverage by
domain. The counts of records with at least eight answers in the table are only
upper bounds on complete 8-item replay paths; MFI may select an unobserved item
earlier.

The SAPA split has no true theta values. Therefore the observed replay must not
report bias, RMSE, MAE, pass rates, cut scores, or a mean “ability” as validity
evidence. If the number of complete paths is too small for a useful descriptive
summary, report the coverage/censoring result and stop. Any minimum effective-N
threshold for comparisons must be declared by the Controller before a run; it is
not inferred from the observed data after the fact.

The forward run is different: theta is generated, not observed. `SimulationRunner`
currently samples `Uniform(-2.5, 2.5)` and its `SimulationSummary.results` and
`write_reports()` contain per-case IDs, true theta, estimates, SEs and stop
reasons. A research report may retain aggregate bias/RMSE/MAE, length, mean SE,
stop distribution and item-exposure counts only. Do not serialize the per-case
result tuple or write its CSV/JSON reports. Keep one run per independent domain;
do not imply a joint five-trait score.

## Existing CAT and bank interfaces

The current CAT provider is scalar: it stores `theta: float`, loads each item's
`a` and threshold vector into one `adaptivetesting.TestItem`, selects with MFI,
and submits integer category indexes (`01_cat-engine/src/cat_engine/providers/adaptivetesting_provider.py`).
`Session.initialize()` and `AdaptiveTestingProvider.start_session()` both call
`ItemBank.assert_runtime_ready()`, which rejects any bank not `published`.
`Session.record_missing()` represents an item that was selected/presented but
not answered; it cannot represent retrospective source unavailability without
changing the meaning of a trace (`domain/session.py`).

The existing internal `/internal/cat/management/validate-assets` and
`/simulate-assets` paths require `SyntheticMetadata` with `synthetic=true`,
`intended_use=engineering_test_only`, and
`psychological_interpretation_allowed=false`; the bank schema is one-dimensional
GRM. The simulation path also requires a runtime-ready published bank and only
accepts batch sizes 100 or 1000 (`01_cat-engine/src/cat_engine/api/assets.py`).
Do not label SAPA-derived mirt output as synthetic to pass that validator.

The Backend's `/api/v1/school/cat-assets` POST bank/version/plan routes create
encrypted immutable database versions, are restricted to a school psychological
specialist with CSRF/idempotency, and validate those synthetic engineering
documents. A plan binds an exact bank version. Saved-version simulation accepts
100 or 1000, not 800. That persistence and activation surface is not a research
import path; this protocol performs no HTTP calls or database writes
(`SCHOOL_CAT_ASSET_MANAGEMENT.md`, `SAVED_CAT_VERSION_EXECUTION.md`).

## Minimum research-only runner needed

No current interface can truthfully run this research bank through the CAT
session/provider path. Do not weaken or reinterpret `assert_runtime_ready()`.
If the Controller later authorizes implementation, the smallest safe increment
is an **offline `CATResearchRunner` plus a typed `ResearchBank`/provenance
bundle** in the CAT research package:

1. Load one mirt domain result, the exact-key crosswalk and one split manifest;
   verify all SHA-256 values, item count, per-item six-category support,
   finite/ordered thresholds, positive finite slopes and response-key maps.
2. Provide a separate `start_research_session()` adapter entry that shares the
   existing provider session-construction/selection/estimation math, but accepts
   only the explicit research bundle. Keep `start_session()`, `Session`'s
   published check, CATService, HTTP routes, schemas and bank statuses unchanged.
   The research runner should drive provider methods directly and emit its own
   research trace; it must not construct `CATResult`/`assessment.v1` objects.
3. Represent an unobserved source answer as a research event
   `SOURCE_RESPONSE_UNAVAILABLE` that censors the replay before any response
   submission. Do not map it to `ResponseStatus`, since no item was presented.
4. Add an aggregate-only forward-run result type. Keep `SimulationRunner`'s
   current synthetic output semantics unchanged; do not call
   `SimulationSummary.to_dict()` or `write_reports()` for the research bundle.
5. First expose a local CLI or test harness, not an API route, activation,
   school task, school plan, registry write, or database resource.

If using a separate implementation would duplicate provider math, first extract
only a private shared construction helper without changing its normal published
gate. The explicit research admission must not be usable by CATService or any
Backend/session route. A future implementation needs independent code review of
that boundary before execution.

## Next-stage isolated research-profile and task path

The offline runner is the first reproducibility step, not the only eventual
integration target. After the runner's source/key checks and probability-parity
gate pass, a separate research-profile flow can make the 800-per-domain
model-generated simulation reviewable through the application. This is a new
research surface; current school bank, plan, activation, task and assessment
endpoints cannot safely be repurposed for it.

| Concern | Minimum isolated design | Existing boundary to preserve |
|---|---|---|
| Asset/profile | New discriminated `ResearchCATProfile` with `profile_kind=research_only`, immutable profile/version refs, exactly one domain, exact 19/20-item list, source DOI/license/citation, source and calibration hashes, mirt version/model/link/prior/quadrature/fit metadata, original source population, key-map hash, `human_curated=false`, and `psychological_interpretation_allowed=false`. | Do not put SAPA estimates into `ItemBank`'s synthetic engineering validator, school `/cat-assets`, or an asset with `published`/`synthetic` status. Do not modify `ItemBank.assert_runtime_ready()`. |
| Enrollment/task | A distinct `ResearchSimulationTask` binds one research profile version, fixed simulation config, `n=800`, seed, theta generator, and `mode=model_generated_forward`. Generate opaque virtual case IDs from the run seed/index only; do not create users, enrollments, school classes, subject records, or actual responses from people. | Do not use `/school/tasks`, student task lists, task publication/activation, `/assessments`, or any school CAT plan. A school actor/student ID must not be sufficient to start this task. |
| Results | Store/expose only run-level aggregate counts, metrics, item exposure, warning/convergence state, and provenance. In a separate research DTO, `result_disposition=L1_COMPLETION_ONLY` may report run completion to its authorized operator; set `interpretation_status=HELD_FOR_REVIEW` for any requested psychological interpretation. Expose no individual trait estimate or label to a virtual case. | Never emit `assessment.v1`, L2 feedback, risk bands, diagnoses, student norms, or a personal report from these parameters. A review marker does not convert a research estimate into an approved conclusion. |
| Isolation and audit | Separate research router/service, permission scope, storage namespace and audit event family; require research-run authorization and immutable source/config/profile version bindings. Export only aggregate artifacts; no per-case theta, score, answer sequence, respondent ID, or SAPA row. | Existing authorization, Backend school isolation, encrypted asset tables, professional review and published gates remain unchanged. No fallback from research lookup to a school asset or profile. |

Minimum additional concepts, pending Controller architecture decision: a research
profile schema and immutable version store; a research simulation task/run schema;
a separate service/router with an explicit research permission; and an aggregate
result DTO. The runner may reuse the provider's scalar mechanics behind a private
shared helper, but it must not construct school `Session`, `CATResult`,
`assessment.v1`, or `StudentTask` objects. The 800 forward simulations are the
generated CAT runs. The task interface starts and reviews those runs; it does not
represent virtual cases as real students or interactive examinees.

Illustrative API shape for that later work is
`POST /api/v1/research/cat-profiles`,
`POST /api/v1/research/simulation-runs`, and
`GET /api/v1/research/simulation-runs/{run_ref}`. These routes and DTOs do not
exist. The profile write would accept verified calibration artifacts and
provenance; the run request would bind one exact profile version, one domain,
`mode=model_generated_forward`, `n_examinees=800`, seed and configuration hash;
the result route would return aggregate-only evidence. Controller must decide
whether this remains an isolated research API/store or receives a dedicated
application profile/task surface before implementation. Do not add these fields
to frozen `assessment.v1` or `api.v1`.

This path does not require a second population label: keep SAPA's self-selected
Internet respondent source population in profile provenance; the virtual
simulation population is the declared generator only. Any later real-person
interactive research would be a separate authorization and consent design, not
part of this protocol.

Proposed CLI shape (not implemented):

```text
uv run --project 01_cat-engine python -m cat_engine.research.empirical_cat_replay \
  --mode observed-replay --manifest <response-split-manifest> \
  --fit-dir <mirt-fit-directory> --domain <one-exact-domain> \
  --config <research-config.json> --output <aggregate-output.json>

uv run --project 01_cat-engine python -m cat_engine.research.empirical_cat_replay \
  --mode model-forward --fit-dir <mirt-fit-directory> --domain <one-exact-domain> \
  --n-examinees 800 --seed 20261014 --theta-uniform -2.5 2.5 \
  --config <research-config.json> --output <aggregate-output.json>
```

The `research-config.json` must copy and hash the exact estimator, MFI,
prior/initial theta, min/max length and SE stop settings used. A copy of
`demo_cat_config.v1.json` is a useful engineering baseline (`EAP`, `MFI`,
min 3/max 8, SE 0.55, N(0,1) prior), but those stop/prior settings remain demo
settings with no psychometric endorsement. Do not change the shared fixture to
make a research run.

## Acceptance criteria for a future authorized run

| Gate | Required evidence |
|---|---|
| Provenance | Calibration/evaluation hashes match the split manifest; 10,000 and 800 counts match; split is disjoint; mirt result records calibration hash; evaluation is never used to refit or choose item parameters. |
| Domain bundle | Exactly one domain per run; 20 items except the 19-item Conscientiousness exact subset; qids equal the crosswalk; no `q_1483`; every scoring map is a permutation of `0..5`; all five mirt fits stay separate. |
| Model compatibility | Every item has `a>0`, five finite strictly increasing thresholds and six supported categories; category-probability parity against the installed `adaptivetesting` GRM is within predeclared tolerance on the fixed theta/category grid. Any mismatch blocks both replay and forward simulation. |
| Observed replay | Exactly 800 input records accounted for per domain; unobserved selected item causes censor-before-score; no selected-source NA is converted to a non-answer or score; aggregate counts reconcile `started = completed + censored + no-domain-response`; report actual effective path count and item-exposure counts. |
| Forward simulation | 800 cases per domain; fixed seed, theta generator, fit hash and config hash recorded; repeated same run reproduces aggregate metrics; true theta and response rows are not persisted; result labels `model_generated_forward`. |
| Output boundary | JSON contains only provenance, aggregate counts/metrics, warnings and domain-level item exposure; no respondent/source row ID, item-response sequence, per-case theta, estimate, score or CSV. Logs follow the same rule. |
| Online isolation | No calls to school CAT assets, internal CAT management, activation, assessment/session routes or database; current online bank gate remains unchanged; no artifact is marked `published`, `synthetic`, student-normed or approved. |
| Research task integration | A future authorized profile/task flow binds exact fit and config hashes, starts 800 virtual cases for one domain, returns only run-level aggregates, and records explicit `research_only` / `HELD_FOR_REVIEW` status. It uses a separate research permission and storage namespace; no school user, enrollment, subject, student task, assessment result, or per-case record is created. |

Passing these criteria means only that the offline replay/simulator is
reproducible and respects its declared evidence semantics. It does not show that
SAPA respondents are students, that CAT estimates are valid, that planned
missingness is ignorable, or that the parameters are ready for a school,
clinical, psychological, or published use. Professional and Controller
decisions remain separate.

## Source pointers

- Source labels, response-only split hashes/population and 10k/800 split:
  `D:\Dev\datasets\psynova-public-research\staging\sapa-background-demographic-codebook.txt`,
  `staging\sapa-ipip100-item-crosswalk.tsv`, and
  `derived\sapa-ipip99-20261013-v1\manifest.json`.
- mirt item parameters and domain fit counts:
  `D:\Dev\datasets\psynova-public-research\R-runtime\mirt-crosscheck\domains-20261014-final\`,
  `mirt-extraversion.json`, and
  `mirt-remaining-domains-20261014-final.json`.
- Scalar provider, scoring and runtime gate:
  `01_cat-engine/src/cat_engine/providers/adaptivetesting_provider.py:57`,
  `:75`, `:128`, `:149`, `:229`; `domain/item.py:72`, `:108`;
  `domain/session.py:102`, `:127`, `:151`; `domain/item_bank.py:115`.
- Forward simulator and per-case export:
  `01_cat-engine/src/cat_engine/simulation/runner.py:37`, `:56`, `:92`, `:111`;
  `simulation/models.py:34`, `:42`.
- Synthetic internal asset validator and one-dimension/published simulation gate:
  `01_cat-engine/src/cat_engine/api/assets.py:37`, `:71`, `:77`, `:79`, `:214`, `:233`.
- School plan/bank persistence boundary:
  `09_backend/src/smhai_backend/domains/cat_assets/router.py:42`, `:105`, `:159`, `:204`, `:257`;
  school class task publication binds a class and optional activation at
  `09_backend/src/smhai_backend/domains/school_tasks/router.py:184` and
  `09_backend/src/smhai_backend/domains/school_tasks/schemas.py:39`; direct school
  assessment start is excluded at
  `09_backend/src/smhai_backend/domains/assessment/router.py:87`;
  `14_docs/autonomous-delivery/SCHOOL_CAT_ASSET_MANAGEMENT.md` and
  `SAVED_CAT_VERSION_EXECUTION.md`.
