# SAPA observed-answer CAT replay protocol

Date: 2026-10-14. Status: `RESEARCH TOOL IMPLEMENTED; RUN COMPLETED; CONTROLLER REVIEW PENDING`.
The offline runner and targeted tests exist under `01_cat-engine`; the completed
run remains research-only evidence. This protocol does not authorize item-bank
publication, school activation, database writes, student assessment, or trait
interpretation.

## Decision summary

Use the 800-record disjoint evaluation split for a **retrospective observed-answer
replay**. The replay asks which CAT items the current scalar engine would select
when it receives real answers already present in the non-adaptive SAPA response
matrix. It does not recover the answers that would have been given to items the
source respondent never received.

Separately, use the five mirt one-dimensional fits to drive an **800-case-per-domain
model-generated forward simulation**. Those responses are generated from the
fitted item curves and a declared synthetic theta distribution. They are virtual
cases, not the 800 evaluation respondents. Keep the experiment results separate
in files, manifests, metrics, and conclusions. The forward design is five
independent domain runs (800 virtual cases each; 4,000 scalar trajectories
total), not 800 joint five-domain profiles.

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

Before using mirt parameters in the research adapter, verify the installed
`adaptivetesting==1.2.1` GRM source and compare public EAP posterior means and
SEs with the same mirt graded-logistic likelihood. The tool checks every fitted
item at 17 theta points from -4 to 4, then checks all six response categories
for one item in each domain against the library's public EAP interface. The
observed maximum mean and SE differences are recorded in each run summary. The
verified link is `P(Y>=k)=logistic(a*(theta-b_k))`; the slope scale is 1.0, with
no D=1.7 conversion.

Source review found that the library's `generate_response_pattern` applies
softmax to the vector of GRM category probabilities. That changes the modeled
probabilities, so this research forward run does not call that generator. It
samples categories from the six cumulative-logit differences directly. The CAT
adapter still uses `adaptivetesting` for MFI item selection and EAP estimation.
If the pinned source or EAP likelihood check changes or fails, the research run
must stop before replay or simulation.

## Evidence semantics

| Experiment | Responses and item selection | Supported evidence | Not supported |
|---|---|---|---|
| Observed-answer replay | For each held-out record, the full domain bank is eligible. Run MFI from the start and submit only the actual observed answer for the selected item. If the selected item is NA, censor that replay immediately. | Selection mechanics on a subset of actual recorded answers; source-coverage, censoring, stop and item-exposure counts. | What the respondent would have answered to an unobserved item; estimation bias/RMSE against a true theta; prospective adaptive-test effectiveness. |
| Model-generated forward simulation | Draw theta from Gaussian N(0,1) and sample each selected answer from the verified mirt graded-logistic probabilities. Run 800 independent virtual cases **per domain**, seed `20261014`; derive and record a deterministic sub-seed for each domain. | Software/model recovery metrics relative to generated theta; stopping and item-exposure summaries under this generator. | Empirical SAPA accuracy, student norms, school representativeness, or independent validation. The response generator and estimator use the same fitted item curves, so this is a model-consistency simulation. |

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

The forward run generates theta and answers; it does not use SAPA response rows.
`SimulationRunner` remains unchanged, and its per-case export is not used. The
research tool streams bias/RMSE/MAE, length, mean SE, stop distribution and
item-exposure aggregates without writing case IDs, theta values or answer rows.
Each domain is a separate scalar run; the output does not form a joint five-trait
score.

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

## Implemented research-only runner

The low-level library API is sufficient without constructing an online
`ItemBank`: the research adapter builds `adaptivetesting.TestItem` and
`TestAssembler` objects from one validated fit at a time. It uses the public
library MFI selection and EAP estimation methods, plus a research-local GRM
categorical sampler for the probability-preserving forward responses. It does
not import or construct `Session`, `ItemBank`, `CATResult`, or `assessment.v1`.
The production `AdaptiveTestingProvider.start_session()` and
`ItemBank.assert_runtime_ready()` remain unchanged.

`01_cat-engine/src/cat_engine/research/empirical_cat_replay.py` validates the
response manifest, exact 99-item crosswalk, 10,000/800 split hashes, source and
fit provenance, per-domain item sets, directions, categories, missing counts,
positive slopes, ordered finite thresholds and convergence. It then runs each
of the five independent domains. For observed replay, a selected source NA
increments the exposure count and stops that path as
`source_response_unavailable`; it is never submitted as a score and MFI does
not select a replacement. For forward simulation, it generates 800 Gaussian
N(0,1) virtual cases per domain using a fixed seed and the fitted six-category
GRM probabilities.

Before either mode runs, the adapter checks the pinned library GRM source and
compares 30 public EAP posterior mean/SE results (six categories in each
domain) with independent numerical integration of the declared logistic
likelihood. It also verifies probability-vector normalization for each of the
99 item parameters at 17 theta points from -4 to 4. A mismatch blocks the run.
Source review found the library's response generator softmaxes already-normalized
GRM category probabilities; the research adapter records that source/hash and
uses its direct cumulative-logit sampler instead. MFI and EAP still come from
`adaptivetesting`.

Each new external run directory contains `run_manifest.json`, one aggregate
checkpoint per completed domain, and `summary.json`. Checkpoints contain only
domain-level counts/metrics and a canonical result hash. No source row ID,
individual theta, selected item sequence, raw answer, per-case estimate, or
response-row dump is written. The command is local only; it makes no HTTP calls,
database writes, school activation or published-bank changes.

### Completed run evidence

The first attempted command used run ID `cat-replay-20261014-990d2c97` before
the probability-parity gate was added. It was stopped, created no output
directory, and is not a completed run. The parity-gated run is
`D:\Dev\datasets\psynova-public-research\research-runs\cat-replay-20261014-v2-c7991d38\summary.json`;
its SHA-256 is
`7fcdce40d7de57354479d9e05e688c690508ff0ce7e0ce1c2dd7ba58397ab3cd`.
That run directory contains only `summary.json` and reports
`research_only_completed`, with `publication_status=not_approved_for_publication_or_operational_use`
and `psychological_interpretation_allowed=false`.

The parity evidence checked 1,683 probability vectors (99 items × 17 theta
points) and 30 public EAP likelihood cases. Maximum probability-sum error was
`1.11e-16`; maximum EAP mean and SE differences were `3.08e-7` and `2.95e-7`,
below the declared `1e-3` tolerance. The pinned GRM, EAP and response-generator
source hashes are recorded in the run summary.

| Domain | Evaluation records | Completed observed paths | Censored before minimum | Censored after minimum | All-missing | Forward paths completed |
|---|---:|---:|---:|---:|---:|---:|
| Agreeableness | 800 | 1 | 793 | 0 | 6 | 800 |
| Conscientiousness | 800 | 1 | 788 | 4 | 7 | 800 |
| Emotional Stability | 800 | 8 | 773 | 1 | 18 | 800 |
| Extraversion | 800 | 59 | 724 | 0 | 17 | 800 |
| Intellect / Imagination | 800 | 29 | 733 | 28 | 10 | 800 |

The observed replay mostly stopped when MFI selected a blank source response.
Those counts are coverage and censoring diagnostics only. Completed-path counts
are low, respondents have no reference theta, and this replay supplies no
bias/RMSE or CAT-effectiveness evidence. All five model-generated runs completed
800 paths with no recorded simulation errors; these are model-consistency
results because their responses and estimator use the same fitted item curves.
The forward aggregate metrics are retained in the external summary, not
interpreted as evidence about SAPA respondents or students.

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

Implemented CLI. It requires an explicit candidate config; there is no implicit
demo fixture or default seed. This example runs 16 virtual Extraversion cases.
Observed replay still consumes exactly 800 evaluation records per selected
domain; `both` and `model-forward` require an explicit `--forward-cases` value.

```text
uv run --project 01_cat-engine python -m cat_engine.research.empirical_cat_replay `
  --artifact-root 'D:\Dev\datasets\psynova-public-research' `
  --config 'D:\Dev\datasets\psynova-public-research\research-runs\configs\research-cat-sapa-candidate-20261014.json' `
  --output-root 'D:\Dev\datasets\psynova-public-research\research-runs' `
  --run-id '<new-unique-run-id>' --mode model-forward `
  --domain Extraversion --forward-cases 16
```

The config carries candidate-only metadata and an exact source-population match.
Run identity binds raw config-file and canonical-content hashes, source/split/
crosswalk hashes, all fit hashes, parity evidence, adapter source hash, runtime
versions, selected domains, mode and case count. `--resume` is accepted only
when every identity field matches. Aggregate checkpoints are atomically written
per domain and validated before reuse; mismatches and incomplete claimed
checkpoints fail closed.

The adapter honors GRM/EAP/MFI, declared min/max, SE threshold, initial theta,
Gaussian prior, optimization interval and seed. Unsupported estimator/model,
selector, prior, initial-theta, interval, exposure-control or content-balancing
values fail closed. There is no silent item-count cap; `max_items` cannot exceed
the smallest selected domain (19 for all five). The seed is config-bound with
deterministic domain sub-seeds. `--forward-cases` is required for both/forward
modes and rejected for observed-only mode; `--domain` may be repeated.

The candidate file `D:\Dev\datasets\psynova-public-research\research-runs\configs\research-cat-sapa-candidate-20261014.json`
uses min 3/max 8 and SE 0.55 as engineering candidates only. It is not
professionally endorsed, psychometrically validated, or approved for school or
clinical use. The existing production demo config remains unchanged.

### Small candidate-config trial

The 16-case isolated forward trial completed for Extraversion using the
candidate config. Run ID:
`candidate-forward-extraversion-20261014-16f`; summary:
`D:\Dev\datasets\psynova-public-research\research-runs\candidate-forward-extraversion-20261014-16f\summary.json`.
Config raw-file SHA-256:
`8813e7e52468949dc9d975fb2d5eac9ab223ff10cb488bb1b68afb99fc796ed2`;
canonical-content SHA-256:
`9412302ebd834c2107f1c6190c4a6018120f2dae27eae699cf9c3f316f6995b0`;
run identity SHA-256:
`e96ca4a369dafd989bdae39245177a6c1e4be76427c4f3e98566c511e16f51e5`;
summary SHA-256:
`a45a7733c2490f15cb19e3c24de7347177610488e2ad75bf161b5891620a4aa7`.
All 16 virtual paths stopped at three items under the candidate SE setting, with
no recorded error and no individual theta/response rows. This checks config
loading, provenance and small-run execution only; it does not validate the stop
threshold or approve a CAT configuration.

## Research-run criteria and future profile/task boundaries

| Gate | Required evidence |
|---|---|
| Provenance | Calibration/evaluation hashes match the split manifest; 10,000 and 800 counts match; split is disjoint; mirt result records calibration hash; evaluation is never used to refit or choose item parameters. |
| Domain bundle | Exactly one domain per run; 20 items except the 19-item Conscientiousness exact subset; qids equal the crosswalk; no `q_1483`; every scoring map is a permutation of `0..5`; all five mirt fits stay separate. |
| Model compatibility | Every item has `a>0`, five finite strictly increasing thresholds and six supported categories; pinned GRM source check, 99-item probability-vector normalization over the theta grid and 30 public EAP likelihood comparisons stay within `1e-3`. The package response-generator softmax finding is recorded; the research sampler uses direct graded-logistic probabilities. Any mismatch blocks both replay and forward simulation. |
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
  `mirt-remaining-domains-20261014-final.json`; calibration approach and
  research boundaries are documented in `GRM_RESEARCH_PLAN.md`.
- Implemented research runner and targeted tests:
  `01_cat-engine/src/cat_engine/research/empirical_cat_replay.py` and
  `01_cat-engine/tests/research/test_empirical_cat_replay.py`.
- Completed aggregate-only run:
  `D:\Dev\datasets\psynova-public-research\research-runs\cat-replay-20261014-v2-c7991d38\summary.json`
  (SHA-256 `7fcdce40d7de57354479d9e05e688c690508ff0ce7e0ce1c2dd7ba58397ab3cd`).
- Parity source evidence is the pinned package's `math/estimators/__functions/__poly/__grm.py`,
  `math/estimators/__expect_a_posteriori.py`, and `math/__gen_response_pattern.py`;
  their source SHA-256 values are preserved in the run summary.
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
