# D4 Slice 1 · Evaluation Foundation Evidence

Status: **READY_FOR_CONTROLLER_ACCEPTANCE**

This document records the bounded D4-1 foundation implementation. It is an
engineering evidence record only. It is not D4 acceptance, psychology approval,
clinical validation, legal or consent approval, real-student authorization, pilot
authorization, or production enablement.

## Binding

- Baseline: `e052e18906dba0256814c1f26209d43f101e919e`
- Tested D4-1 implementation commit: `5944f91a0a00a823bc7a3a97ae2069e28d01c3c3`
- Evidence closure commit: this evidence-only closure commit.
- Branch: `exp/d4-evaluation-foundation-v1`
- Worktree: `D:\Projects\StudentMentalHealthAI-d4-evaluation`
- Accepted D3 baseline remains `d3-slice4-r1-accepted` → `80140de6fbb63d3239ecc425f9c3daaaf34fb4d7`.
- Formal manifest: `12_evaluation/d4-evaluation-r1/manifests/run_manifest.json` binds
  `git_commit` to `5944f91a0a00a823bc7a3a97ae2069e28d01c3c3` and accepted tag
  `d3-slice4-r1-accepted`. The fictitious `d4-foundation-v1` tag is not present.
- Schema-only zero-commit sample: `harness/foundation/fixtures_valid/run_manifest_SAMPLE_ONLY.json`.
- No merge, push, D4-1 tag, D4-2 start, or product-source change was performed.

## Delivered foundation

- Strict Draft 2020-12 schemas:
  `spec/d4_scenario.schema.json`, `spec/d4_run_manifest.schema.json`, and
  `spec/d4_machine_evidence.schema.json`.
- Authority registry:
  `spec/d4_semantic_authority_registry.json`, binding D4E-01..60 and
  D4SUP-01..20 to the frozen D4 technical decision.
- Evaluation-only foundation harness under `harness/foundation/` for canonical
  UTF-8 JSON/SHA-256, immutable run IDs, split and semantic-family controls,
  fixture isolation, sealed mutation/anti-tuning, manifest writing, evidence
  normalization, and artifact path safety.
- Minimal synthetic DEV, REGRESSION, and SEALED_EVAL fixtures, plus named valid
  and negative schema fixtures.
- Canonical sample manifest:
  `12_evaluation/d4-evaluation-r1/manifests/run_manifest.json`.
- Machine evidence sample:
  `12_evaluation/d4-evaluation-r1/results/foundation_machine_evidence.json`.
- Summary artifacts:
  `12_evaluation/d4-evaluation-r1/d4_slice1_foundation_evaluation.json` and
  `12_evaluation/d4-evaluation-r1/d4_evaluation_summary.json`.

## Hard-gate evidence

| Gate | Result |
|---|---|
| Focused D4-1 pytest | **37 passed** |
| All three D4 schemas parse and validate as Draft 2020-12 | **PASS** |
| Authority registry ranges and source binding | **PASS**; D4E 60, D4SUP 20 |
| Expected/observed response semantics | **PASS**; separate enums and fields |
| Fixture file existence and SHA-256 binding | **PASS** |
| DEV/REGRESSION/SEALED_EVAL split integrity | **PASS**; 1/1/1 cases |
| Cross-split semantic-family collision guard | **PASS** |
| SEALED review and mutation/anti-tuning guard | **PASS**; required review must be explicit `COMPLETE`, optional review `NOT_REQUIRED` |
| Run manifest hash, run ID, schema, and immutability checks | **PASS** |
| Result path traversal/product/secret path guard | **PASS** |
| Python compile/import | **PASS** |
| `git diff --check` | **PASS**; only Git line-ending warnings |
| Root Contract | **13/13 PASS** |
| OpenAPI | **PASS** using the local Backend test extra |
| Frozen Root | **8/8 unchanged** |
| Ruff check | **NOT_RUN_UNAVAILABLE**; direct `ruff check 12_evaluation/d4-evaluation-r1/harness` attempt exited 1 because `ruff` is unavailable |
| Ruff format | **NOT_RUN_UNAVAILABLE**; direct `ruff format --check 12_evaluation/d4-evaluation-r1/harness` attempt exited 1 because `ruff` is unavailable |
| Pyright | **NOT_APPLICABLE_NO_CONFIGURED_SCOPE**; no Pyright configuration exists under `12_evaluation/d4-evaluation-r1` |

## Boundary checks

- Promptfoo was not installed.
- No Runtime, Backend, GPU, adversarial model, behavioral grader, or network run
  was performed.
- No real-student data, secret, cloud fallback, or clinical threshold was used.
- Product directories, D3, Root, OpenAPI, contracts, and database artifacts are
  unchanged from the baseline.
- Remaining D4-1 P0 items: **NONE**.
- Preserved P1 items: baseline Backend Pyright SQLAlchemy import-resolution
  errors; historical GPU/fixed-output-budget robustness; D5 cleanup PID.
- D4 overall status remains **NOT_RUN / NOT_ACCEPTED**. D4-2 through D4-7 remain
  outside this slice.

## Worker ledger

- Worker A — Schema / Authority Foundation: completed; no commit.
- Worker B — Manifest / Hash / Split Harness: completed; no commit.
- Worker C — Independent Foundation Review: **REVIEW_READY** after remediation;
  no commit.

## Recommendation

`D4_SLICE1_READY_FOR_CONTROLLER_ACCEPTANCE`.

Controller review should focus on the authority registry binding, exact versus
legacy fixture separation, explicit human-review state transitions, sealed-set
immutability, and the fact that this slice supplies evaluation infrastructure
only. Real pilot remains **BLOCKED**.
