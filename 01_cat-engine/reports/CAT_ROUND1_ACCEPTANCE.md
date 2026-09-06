# CAT Round 1 Acceptance

## 1. Conclusion

`PASS`

CAT V0.1 Engineering Baseline has a runnable synthetic GRM CAT path, an
adapter-isolated provider, a guarded session state machine, structured traces,
assessment.v1 mapping, reproducible simulation, and passing CAT plus frozen
Contract checks. The result is an engineering baseline only; it is not a
psychological instrument or an interpretation result.

All Round 1 item parameters and outputs are:

`NOT FOR PSYCHOLOGICAL INTERPRETATION`  
`DEMO / ENGINEERING USE ONLY`

## 2. Implemented

- Versioned synthetic item bank with nine five-category GRM items and explicit
  non-interpretation metadata.
- Configuration-driven GRM, EAP, MFI, minimum/maximum item and SE stopping
  settings.
- Provider-neutral domain models and `CATProvider` interface.
- `AdaptiveTestingProvider` over the observed public `adaptivetesting` API.
- `CREATED -> INITIALIZED -> IN_PROGRESS -> COMPLETED` lifecycle plus reserved
  `PAUSED`, `CANCELLED`, and `ERROR` states.
- Answered/missing-response handling for `answered`, `skipped`, `timeout`,
  `invalid`, and `not_presented`; missingness is never scored as zero.
- Per-item trace records containing selection, response status, theta/SE before
  and after, versions, timestamp and sequence number.
- `CATResult -> AssessmentMapper -> assessment.v1` mapping with externally
  supplied risk; CAT does not calculate risk or psychological bands.
- Real provider-based simulation and JSON/CSV/Markdown report export.

## 3. Architecture

```text
Synthetic Published Item Bank + CAT Config
                 |
                 v
             CATService
                 |
                 v
              Session
                 |
                 v
             CATProvider
                 |
                 v
      AdaptiveTestingProvider
                 |
                 v
        adaptivetesting GRM/EAP/MFI
                 |
                 v
        CAT Trace + CATResult
                 |
                 v
        AssessmentMapper
                 |
                 v
            assessment.v1
```

The adapter is the only production code that imports `adaptivetesting`. The
assessment mapper omits raw responses and does not expose provider-specific
objects.

## 4. Third-party dependency

Verified environment: Python `3.14.6` in
`01_cat-engine/.venv314`.

| Dependency | Version | Role |
| --- | --- | --- |
| adaptivetesting | 1.2.1 | GRM model, EAP/BM estimators, MFI information and response generation |
| numpy | 2.5.2 | transitive numerical dependency |
| pandas | 3.0.5 | adaptivetesting dependency |
| scipy | 1.18.1 | adaptivetesting numerical dependency |
| matplotlib | 3.11.1 | adaptivetesting dependency |
| numdifftools | 0.11.1 | adaptivetesting dependency |
| tqdm | 4.70.0 | adaptivetesting dependency |
| jsonschema | 4.26.0 | assessment.v1 validation |
| pytest | 8.4.2 | CAT test runner |

`adaptivetesting==1.2.1` was successfully integrated through
`AdaptiveTestingProvider` on Python 3.14.6. Its package metadata says Python
`>=3.12`, but importing it on Python 3.12.12 failed because the installed
source imports `warnings.deprecated`, which is unavailable there. The
compatibility finding and MPL-2.0 license notice are recorded in
`ADAPTIVETESTING_COMPATIBILITY_REPORT.md`. The dependency is pinned in
`pyproject.toml` and `uv.lock`.

## 5. Tests

| Command | Result |
| --- | --- |
| `& .venv314\\Scripts\\python.exe -m pytest` | 24 passed, 0 failed |
| `& .venv314\\Scripts\\python.exe -m unittest discover -s ..\\00_architecture\\tests -p 'test_contracts.py' -v` | 13 passed, 0 failed |
| `& .venv314\\Scripts\\python.exe -m compileall -q src tests` | PASS |
| `uv pip check --python .venv314\\Scripts\\python.exe` | 28 packages compatible |

The CAT test suite covers item-bank negative cases, provider initialization
and updates, state transitions, completed-session rejection, missingness,
adaptive behavior, mapping, schema validation, reproducibility and metrics.
The root test suite validates the unchanged frozen governance and public
Contract assets.

No ruff, mypy, pyright or Vale configuration/tool was present; these are
recorded as `NOT CONFIGURED`, not as passing checks.

## 6. Simulation

The actual Round 1 batch used the real provider response generator and CAT
loop, not `true_theta + random noise`.

| Field | Value |
| --- | --- |
| N | 1000 |
| Seed | 20260904 |
| Bias | 0.1828483808 |
| RMSE | 1.4281148373 |
| MAE | 1.1955245394 |
| Mean Test Length | 7.218000 |
| Median Test Length | 8.000000 |
| Mean SE | 0.5528322348 |
| MAX_ITEMS_REACHED | 343 |
| SE_THRESHOLD_REACHED | 657 |

Full per-examinee JSON and CSV outputs are in `reports/`; the concise summary
is `CAT_SIMULATION_SUMMARY.md`.

## 7. Adaptive Evidence

With the same synthetic bank and configuration, two response paths produced:

```text
never:  ITEM_demo_008 -> ITEM_demo_003 -> ITEM_demo_002 -> ITEM_demo_001
always: ITEM_demo_008 -> ITEM_demo_003 -> ITEM_demo_005 -> ITEM_demo_007
```

The first item is shared because both sessions start at the configured prior
theta. Later selections differ after response updates, and the test asserts a
different post-first-item sequence without hard-coding a replacement choice.

## 8. Assessment Contract

`assessment.v1` validation: `PASS`.

The mapped result contains the required anonymous IDs, demo instrument and
population markers, unknown score band, theta/SE estimate, minimal response
summary, externally supplied risk snapshot, CAT provenance and timestamps.
The shared assessment schema was not modified.

## 9. Reference Validation

`mirtCAT`: `PENDING`.

R and `Rscript` were not configured on this machine. No reference result or
cross-engine agreement is claimed. See
`REFERENCE_VALIDATION_STATUS.md` and `reports/CAT_REFERENCE_VALIDATION.md`.

## 10. Known Limitations

- The current Synthetic Item Bank has no psychological meaning or validity.
- The formal instrument and target population still await psychological
  confirmation.
- Formal risk thresholds and score-band definitions are not defined.
- The demo bank is one-dimensional; the proposed factor structure and
  multidimensional architecture remain pending.
- Exposure control and full content balancing are extension points, not
  implemented Round 1 algorithms.
- Python 3.12 is not a verified runtime for adaptivetesting 1.2.1 despite its
  package metadata; Python 3.14 is the verified environment.
- mirtCAT reference comparison was not executed.

## 11. Files Changed

Module documentation and configuration:

- `CAT_TECHNICAL_DECISION_V1.md`
- `TASK.md`
- `README.md`
- `pyproject.toml`
- `uv.lock`
- `ADAPTIVETESTING_COMPATIBILITY_REPORT.md`
- `REFERENCE_VALIDATION_STATUS.md`

Runtime and fixtures:

- `src/cat_engine/domain/{config,enums,errors,item,item_bank,result,session,trace}.py`
- `src/cat_engine/providers/{base,adaptivetesting_provider}.py`
- `src/cat_engine/service/{assessment_mapper,cat_service}.py`
- `src/cat_engine/simulation/{metrics,models,runner}.py`
- `src/cat_engine/validation/assessment_contract.py`
- package `__init__.py` files under `src/cat_engine/`
- `fixtures/synthetic_item_bank.v1.json`
- `fixtures/demo_cat_config.v1.json`

Tests and reports:

- `tests/conftest.py`
- `tests/unit/{test_item_bank,test_provider,test_session}.py`
- `tests/integration/{test_adaptive_behavior,test_assessment_contract}.py`
- `tests/simulation/test_simulation.py`
- `reports/CAT_REFERENCE_VALIDATION.md`
- `reports/CAT_SIMULATION_SUMMARY.md`
- `reports/cat_simulation_summary.json`
- `reports/cat_simulation_results.csv`
- this acceptance report

No root-level Contract, schema, API, other-module business code, or Git
metadata was modified. The local `.venv`/`.venv314` environments and Python
cache files are verification artifacts, not CAT deliverables.

## 12. Blockers

No Round 1 engineering blocker remains.

Pending decisions that block a formal psychological release are the instrument,
population, factor structure, measurement model confirmation, item parameters,
scoring direction, missing-response policy, stopping thresholds and formal
risk definitions. These were intentionally not decided here.

## 13. Recommendation

Recommend entering CAT Round 2 for provider hardening, reference comparison and
psychology-confirmed configuration only after the pending decisions are
provided. Do not treat this Round 1 PASS as psychological validation or a
production mental-health assessment release.
