# CAT Technical Decision V1

Status: `PROVISIONALLY_FROZEN`

Document Version: `1.0`

Date: `2026-09-04`

Depends on: Contract `v0.1.0 FROZEN`

## 0. Scope and scientific boundary

This document defines the engineering baseline for CAT Round 1. It does not
freeze a psychological instrument, a target population, a factor structure,
an interpretation rule, a clinical cut-off, or a production item bank.

The Round 1 item bank and all generated results are synthetic:

- `synthetic: true`
- `intended_use: engineering_test_only`
- `psychological_interpretation_allowed: false`
- `NOT FOR PSYCHOLOGICAL INTERPRETATION`
- `DEMO / ENGINEERING USE ONLY`

The values in the synthetic bank are hand-authored engineering parameters.
They must never be described as validated psychological item parameters or as
evidence of student mental-health status.

## 1. CAT positioning

CAT is the project's Measurement Layer. Its input is:

```text
Published Item Bank + CAT Config + Participant Responses
```

Its output is a machine-valid `assessment.v1` result after mapping. CAT owns
item-bank loading and validation, item selection, response recording, ability
estimation, uncertainty, stopping, session state, simulation, trace records,
and result mapping.

CAT does not own diagnosis, counselling, RAG, LLM generation, teacher or
parent advice, medication advice, final risk definitions, crisis detection,
or formal psychological item design.

Risk is injected into the assessment mapper by an approved upstream or
downstream ruleset. CAT does not calculate or interpret `risk.level`.

## 2. Online and offline separation

The future calibration path is:

```text
Response Matrix
  -> Psychometric Analysis
  -> IRT/MIRT Calibration
  -> Validation
  -> Version Release
  -> Published Item Bank
```

The Round 1 runtime path is:

```text
Published Item Bank
  -> CAT Runtime
  -> CAT Result
  -> AssessmentMapper
  -> assessment.v1
```

Online runtime loads immutable, versioned parameters only. A response never
updates `a`, `b`, category thresholds, or any other item parameter. Future
calibration may use R `mirt`/`mirtCAT` or another specialist tool, but that
workflow is offline and outside this Round 1 runtime.

## 3. Provider architecture

Business code depends on the internal `CATProvider` interface. Third-party
types are confined to a provider adapter:

```text
Session Service
  -> CATProvider
  -> AdaptiveTestingProvider
  -> adaptivetesting
```

The interface responsibilities are:

- `start_session`: create an opaque provider state from an immutable bank and
  configuration;
- `select_next_item`: select an unadministered item and return the criterion
  and an optional provider selection score;
- `submit_response`: record an answered response and update the estimate;
- `estimate_ability`: return the current theta estimate;
- `get_uncertainty`: return the current standard error;
- `should_stop`: evaluate configured stopping criteria;
- `get_result`: return a provider-neutral result snapshot.

`ExperimentalMirtProvider` and future providers are extension points only;
they are not required production dependencies in Round 1. No provider-specific
object may cross the `assessment.v1` boundary.

## 4. Item-bank decision

The internal item-bank model is versioned and validates at load time. Its
minimum metadata is:

```text
item_bank_id, version, instrument_id, target_population,
measurement_model, dimensions, items, status
```

Each item carries:

```text
item_id, dimension, stem, response_type, response_options,
scoring, model, parameters, source, status
```

Online loading accepts `published` banks only. The demo bank is intentionally
marked `published` so it exercises the same runtime gate, while its metadata
explicitly says that it is synthetic and engineering-only. It is not a
psychological publication decision.

The demo bank is one-dimensional only to avoid silently freezing the pending
four-dimension proposal. Its instrument, population, model and interpretation
remain `PENDING_PSYCHOMETRIC_CONFIRMATION`.

## 5. Session state

The session state machine is:

```text
CREATED -> INITIALIZED -> IN_PROGRESS -> COMPLETED
```

Reserved exceptional states are `PAUSED`, `CANCELLED`, and `ERROR`. A
completed, cancelled, or errored session cannot accept another response. A
response cannot be submitted before initialization, and initialization cannot
silently replace the item bank or configuration version.

## 6. CAT trace

Every administered item creates one structured trace record. It includes the
item ID, response status and response value (when present), theta and SE
before/after, selection criterion, provider selection score when available,
timestamp, sequence number, provider version, item-bank version, and config
version. A missing provider score is recorded as `null`, never invented.

Missing responses are represented internally as one of `answered`, `skipped`,
`timeout`, `invalid`, or `not_presented`. Missingness is not converted to zero
or to the lowest category. The frozen public response endpoint remains the
source of truth for its accepted scalar response shape.

## 7. Algorithm candidates and configuration

These are engineering candidates, not psychological conclusions:

| Concern | Round 1 candidate | Status |
| --- | --- | --- |
| Likert/polytomous model | GRM candidate; use the provider's supported model for the PoC if integration requires a simpler model | `PENDING_PSYCHOMETRIC_CONFIRMATION` |
| Ability estimation | EAP candidate | `PENDING_PSYCHOMETRIC_CONFIRMATION` |
| Unidimensional selection | MFI candidate | `PENDING_PSYCHOMETRIC_CONFIRMATION` |
| Multidimensional selection | D-optimality candidate | `PENDING_PSYCHOMETRIC_CONFIRMATION` |

The model, estimator, selection criterion, prior, minimum items, maximum
items, SE threshold, seed, and provider version are configuration values.
They are not constants hidden in business logic. If the selected provider
does not expose a requested internal score, the result remains unavailable.

## 8. Stopping and exposure/content extension points

Round 1 supports configured minimum items, maximum items, and an optional SE
threshold. The effective stop reason is explicit, for example:
`SE_THRESHOLD_REACHED`, `MAX_ITEMS_REACHED`, `MANUAL_TERMINATION`, or `ERROR`.
Demo thresholds are engineering-only and do not define a formal assessment.

The provider boundary leaves room for future exposure control (`randomesque`,
`Sympson-Hetter`, `progressive`) and content balancing (`Blueprint`,
`Maximum Priority Index`, `Weighted Penalty`). Complex controls are not
implemented in this baseline.

## 9. Simulation and reproducibility

Simulation is a core CAT capability, not a shortcut that adds noise to the
true theta. Each simulated examinee:

```text
true theta
  -> item-response probability from the provider/model
  -> sampled response
  -> real CAT provider selection and update
  -> configured stopping
```

Batch results record `true_theta`, `estimated_theta`, `bias`, `RMSE`, `MAE`,
`SE`, `items_administered`, and `stopping_reason`. A batch records its seed,
CAT engine version, provider version, item-bank version, config version,
Python version, and dependency versions. The same seed and immutable inputs
must reproduce the same result.

## 10. Assessment mapping

`CATResult` is an internal object. `AssessmentMapper` is the only boundary
adapter that emits `assessment.v1`. It supplies the required contract fields,
keeps the synthetic instrument/population explicit, and accepts an externally
provided risk snapshot. It does not derive or reinterpret a risk level.

The mapped demo result uses `band: "unknown"` and a null score because no
psychological score-band mapping has been approved. The result is suitable
for schema and engineering tests only.

## 11. LLM isolation

`LLM NEVER PARTICIPATES IN PSYCHOMETRIC ESTIMATION.` CAT contains no LLM
dependency and does not call the Prompt, RAG, safety, or generation layers.

## 12. Third-party decision record

`adaptivetesting` is the primary production candidate for the Python online
provider. Its package version, supported Python version, public API, license,
and actual adapter behavior must be recorded in
`ADAPTIVETESTING_COMPATIBILITY_REPORT.md` and in the acceptance report after
local inspection. The package is used only behind `AdaptiveTestingProvider`.

R `mirt`/`mirtCAT` is a reference implementation, `catsim` is a simulation
reference, Concerto is a product reference, and Cameron-Lyons/mirt is an
experimental future provider. Deep CAT, MAQuA, LLM item generation and
open-ended LLM psychometric assessment are out of scope.

