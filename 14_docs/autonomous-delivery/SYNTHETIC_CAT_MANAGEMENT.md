# Synthetic CAT management increment

Controller direction, 2026-10-12. This increment connects current fixture inspection and reproducible engineering simulation to the specialist workspace. Full draft item-bank/version/plan management remains a later increment; this document does not redefine that requirement as complete.

## Scope and constraints

- Only an active school psychological specialist can access the Backend gateway. Recheck persisted role before the CAT request and before returning its response. Students, ordinary teachers, school administrators and cross-profile actors are denied.
- Inspect the actual runtime bank and fixed configuration. Require explicit synthetic metadata, engineering-only intended use and psychological interpretation disabled. Unknown or non-synthetic assets fail closed.
- Preserve existing assessment.v1, CAT sessions, published fixture files, item parameters and frozen research evidence. No editing, activation, clinical interpretation or report publication in this increment. Do not expose item parameters, per-simulation examinees, internal paths or credentials over HTTP.
- Simulation uses a separate real AdaptiveTestingProvider and SimulationRunner, the current immutable bank/configuration and its fixed seed. Do not add simulated subjects to the live CAT session registry or write reports/files/DB rows. Return aggregate metrics and stopping counts only. Permit one simulation at a time; reject concurrent requests rather than queue unbounded work.

## Internal CAT transport

GET `/internal/cat/management/catalog` returns:

```
schema_version: synthetic_cat_management.v1
engineering_only: true
psychological_interpretation_allowed: false
item_bank: {item_bank_id, version, instrument_id, item_count, dimension_count,
            status, validation: STRUCTURE_VALID}
config: {config_version, model, estimator, selection_method, min_items, max_items,
         se_threshold, seed}
simulation: {available: true, sample_sizes: [100, 1000], fixed_seed}
```

POST `/internal/cat/management/simulations` accepts only strict `{n_examinees: 100|1000}`; default100. No seed or parameter override. Response uses the same schema_version/engineering-only flags and includes `item_bank_id`, `item_bank_version`, `config_version`, `n_examinees`, `seed`, `metrics` (bias, rmse, mae, mean_test_length, median_test_length, mean_se) and `stopping_reason_distribution`. Metric values must be finite and counts sum to sample size. No results array or subject/session identifiers. Benchmark current CPU execution before deciding the gateway timeout.

## Backend and browser

Add compatible school routes outside frozen OpenAPI: GET `/api/v1/school/cat-management/catalog`, POST `/api/v1/school/cat-management/simulations`. Authenticate and apply CSRF to simulation requests; fresh role checks and metadata-only access/run audits use the established UOW. This operation is deterministic engineering computation and creates no business resource; do not label it a professional approval or silently retry it. Dependency failure remains an explicit error, never cached/fake output.

The specialist can inspect the current synthetic configuration, run the selected fixed batch and compare repeatable aggregate output. Show loading, unavailable, forbidden and busy/error states. Label the values as engineering simulation and pending psychological validation. Browser acceptance must match UI output to real API aggregates and verify role denials, CSRF, repeatability and unchanged live CAT session count.

## Verified increment — 2026-10-12

- CAT management uses a dedicated600s read budget after actual local N1000
  provider timing298.342s. Existing assessment/LLM/Safety budgets are unchanged.
- Root fresh suites: CAT37 passed; Backend392 passed; Frontend162 passed and
  production build passed. Added shared transport tests2 passed, including cookie,
  CSRF and exact path checks; scoped Frontend ESLint passed. Harness Python10 and
  Node5 passed. These are engineering checks, not psychological validation.
- Actual specialist browser workflow passed all14 declared stages: real catalog,
  two real N100 runs, DOM metrics matching API, repeat comparison, pending controls,
  masked desktop/mobile screenshots and logout. Root inspected both screenshots.
  Evidence: original external workspace browser-qa/
  20261012T152140Z-3743dd13f7804ddf92f75e6c4a3704c9.
- Separate native public HTTP proof covers student/teacher/admin403, missing
  CSRF403, float/bool/string/out-of-range/extra-field422, actual catalog, concurrent
  busy409 and N1000 aggregate response. Actual N1000 gateway duration318.593s;
  CAT health session_count remained0 before/after. Evidence: original logs/
  cat-management-http-3af9f18e1b52406fb0776dfb563db8f1.json. The first native harness
  attempt used an incorrect ADMIN enum and failed login-context selection; it was
  corrected to the existing API enum, without changing authorization behavior.
- Root loaded reviewed source into original CAT8180 and Backend8088 after fresh
  ownership checks and stopping only owned foreground handles. Current CAT exec
  88502/PID45844, Backend exec87089/PID45564; exact identities and history are in
  external school-processes.json. Frontend exec90451/PID36496 remains active.
- Independent source review found missing role/CSRF/session invariance in the
  browser harness itself; the separate native HTTP proof above supplies those
  checks. Cancellation and mid-run persisted-role rejection are covered by focused
  tests, not native connection-loss/revocation experiments. No whole-product
  acceptance, professional approval, draft CRUD or plan activation is claimed.
