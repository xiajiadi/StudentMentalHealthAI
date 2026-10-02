# D4-3B Product Remediation R1 Manifest

Date: 2026-10-02

Branch: `fix/d4-3b-product-remediation-r1`

Evidence class: engineering remediation evidence; not formal product evidence

## Source identities

| Identity | Commit |
|---|---|
| Old accepted product baseline | `dd083d7a9d50e554408571e8b6d8040700d7a88b` |
| Old evaluation head | `a4d6a68908adeb67b8f838593032b1eb18a99721` |
| R1 product remediation commit | `466fef4bf59d10b7d115bf522e9f53b2730adb91` |

The remediation commit is isolated on the R1 branch. The previous formal run
`D4RUN-20261002T082426Z-891e2e1fdce5` remains immutable. No formal run or D4-4
execution was started.

## Changed files

- `09_backend/src/smhai_backend/core/orchestration.py`
- `09_backend/src/smhai_backend/domains/support/service.py`
- `09_backend/src/smhai_backend/integrations/d3.py`
- `09_backend/src/smhai_backend/integrations/d3_chain.py`
- `09_backend/src/smhai_backend/integrations/population_mapping.py`
- `09_backend/src/smhai_backend/integrations/rag.py`
- `09_backend/src/smhai_backend/integrations/safety.py`
- `09_backend/tests/test_d3_backend_integration.py`
- `09_backend/tests/test_population_mapping.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/cli.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/manifest.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/network_integrity.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/observer_proxy.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/results.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/runner.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/service_profiles.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/tests/test_backend_profile_environment.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/tests/test_controlled_product_eval.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/tests/test_observability_hardening.py`
- `12_evaluation/d4-evaluation-r1/harness/controlled_product_eval/tests/test_safety_observer.py`
- `12_evaluation/d4-evaluation-r1/spec/d4_slice3b_case_result.schema.json`

No CAT, assessment-adapter, knowledge-pipeline, RAG-engine, prompt-engine,
Human Gold, frozen Contract, or OpenAPI file changed. The D3-2 binding and the
CAT-to-D3 compatibility fixture identity, approval, and dimension map remain
unchanged. The existing `CONTRACT_FAKE` retrieval fixture mapping is preserved.

## Semantic delta

1. Added the immutable, server-owned mapping
   `MAP_UNIVERSITY_FRESHMAN_SUPPORT_TO_RAG_D3_V1` (`1.0.0`). It links the
   university-freshman synthetic support policy to the observed RAG taxonomy
   `university_freshman`, the D3 evidence eligibility scope, and the D3 content
   identity `UNIVERSITY_FRESHMEN_SYNTHETIC_DEMO`. Unknown mappings fail closed.
   REAL_HTTP no longer sends the K12 fallback. Caller population and CAT
   `pending_confirmation` are not routing inputs.
2. A valid RAG success with zero chunks now persists a deterministic
   `abstained` result with `NO_ELIGIBLE_EVIDENCE`, `generation_status=NOT_RUN`,
   `candidate_source=NOT_RUN`, no citations or content, and no Runtime or
   output-Safety call. Nonempty ineligible evidence remains fail-closed.
3. The Backend contract-fake adapter now uses the existing deterministic
   `EXPLICIT_CRISIS_SIGNAL` reason code for the exact synthetic crisis marker.
   The real Safety policy and its explicit-signal semantics were left intact.
4. The D4 Harness records only run/request/trace-correlated Safety input and
   retrieval actions and allowlisted reason codes. Safety request/response
   bodies, body hashes, and body lengths are not persisted. The new observation
   is evidence-only; response-class logic and P0 scoring are unchanged.

## Verification

| Check | Result |
|---|---|
| `09_backend` full test suite | PASS — 77 passed |
| Backend RAG/EvidenceBundle/D3 focused suite | PASS — 40 passed |
| `08_safety-engine` full test suite | PASS — 20 passed, 1 skipped (the pinned Qwen CPU gate remains delegated to `safety-evaluate`) |
| D4 Harness full test suite | PASS — 176 passed |
| Safety observer and observability focused tests | PASS — 26 passed |
| Python compileall for Backend, Safety, and D4 Harness sources/tests | PASS |
| Staged and working diff whitespace checks | PASS |

The full-repository Gitleaks baseline has seven findings in unchanged files;
their values are not reproduced here. `PREEXISTING_SECRET_SCAN_TRIAGE` remains
separate work required before D4 overall acceptance.

## Controller boundary still requiring reconciliation

The frozen text for `AW-HARD-STOP-MUST-ROUTE-001` does not contain the
`SYNTHETIC_CRISIS_SIGNAL` marker. The current trusted synthetic signal path sets
`explicit_crisis_signal=true` only for that exact marker. The R1 implementation
and tests verify that a non-Human-Gold synthetic request carrying the marker
routes as `CRISIS_ROUTE / EXPLICIT_CRISIS_SIGNAL`, with RAG and Runtime skipped.
They do not establish that the marker-free frozen Human Gold case now routes.
Changing Human Gold or adding a free-text alias was outside the authorization.
The exact Human Gold hard-stop behavior therefore must not be claimed as
remediated until the Controller resolves this input-signal mismatch.

## Handoff state

- Independent C code review: pending.
- Three nonformal, non-Human-Gold synthetic product-shaped smoke paths: pending C
  review readiness.
- Formal 12-case rerun: not authorized by this manifest.
- D4-3B: `FORMAL_MEASUREMENT_COMPLETE / NOT_ACCEPTED`.
- D4 overall: `IN_PROGRESS / NOT_ACCEPTED`.
- D4-4: `NOT_AUTHORIZED`.
- Real pilot: `BLOCKED`.
