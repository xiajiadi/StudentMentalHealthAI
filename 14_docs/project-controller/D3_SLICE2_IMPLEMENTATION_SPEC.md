# D3 Slice 2 · Assessment Interpretation Adapter Implementation Spec

Status: `APPROVED_FOR_BOUNDED_IMPLEMENTATION`

This specification is derived from the frozen D3I-01 through D3I-40 decision in
`D3_ASSESSMENT_INTERPRETATION_TECHNICAL_DECISION_V1.md`. It defines a small,
module-owned D3-2 boundary. It does not promote a root contract or create a
psychology decision.

## 1. Scope and ownership

The implementation lives only in `03_assessment-adapter`. It consumes an
already completed, CAT-produced `assessment.v1` result and returns a typed,
canonical interpretation result for later consumers. CAT remains the only
authority for `theta`, `se`, item/stopping evidence and score computation.

D3-2 has no network client, LLM, RAG, Safety service, database, Prompt Engine
or role projection dependency. It does not change `CONTRACTS.md`, root schemas,
OpenAPI, CAT, D3-1, Safety, RAG, Backend or the new D2 corpus.

## 2. Data flow

```text
completed assessment.v1
        + trusted interpretation context
        + exact policy reference and policy pack
        -> deterministic validation and policy selection
        -> typed canonical interpretation result
```

The assessment is untrusted input even when it was produced by CAT. The
trusted context is a capability-like, typed object created by an internal
integration seam. A caller cannot replace it with a plain mapping to claim a
mode, population, Safety state or eligibility. The process-local seam is not a
cryptographic boundary against hostile code that can import private names or
rewrite memory in the same Python process.

## 3. Internal request and trusted context

`InterpretationRequest` contains:

- a deep-copied `assessment.v1` mapping;
- `policy_id`, `policy_version` and `policy_hash` supplied by the caller;
- request and trace identifiers for audit correlation.

The adapter validates the complete frozen assessment shape before reading
fields. It requires the instrument id/version, assessment population, status,
dimension identifiers, CAT-provided `theta`/`se`, item counts, risk state and
provenance. It never recalculates, rounds, bins or otherwise derives a CAT
measurement.

`TrustedInterpretationContext` contains only trusted integration state:

- execution mode (`SYNTHETIC_DEMO` or `RESEARCH_ONLY`);
- assessment population and context identity;
- trusted Safety action (`PROCEED`, `PROCEED_WITH_BOUNDARY`,
  `CRISIS_ROUTE`, `REVIEW_REQUIRED` or `BLOCK`);
- a context version and opaque capability marker.

`REAL_USER` is rejected before policy selection. Public APIs accept the typed
context, never a caller-provided dictionary. The trusted builder is private or
explicitly test/integration-only.

## 4. InterpretationPolicyPack

Policy packs are versioned JSON assets parsed into typed records. Each pack
must contain:

- `policy_id`, `policy_version`, `policy_hash` and `effective_version`;
- `instrument_id`, `instrument_version` and one exact `population_scope`;
- `allowed_modes` and an explicit `synthetic_only` marker where applicable;
- separate engineering/controller scope and `psychology_review_status`;
- `review_decision_id`, `evidence_refs` and review-status metadata;
- typed `construct_policies`, `allowed_claims` and `forbidden_claims`.

Construct names, directions, high/low meaning and claim codes are data in the
policy pack. They are never hard-coded in adapter logic. A construct without
approved metadata causes a deterministic abstention or `MEASUREMENT_ONLY`
result; it never receives a generic interpretation.

The committed current policy is deliberately conservative: it is explicitly
synthetic-only, controller-approved only for synthetic engineering use,
`psychology_review_status=REVISIONS_REQUIRED` with
`review_status_detail=RECEIVED / REVISIONS_REQUIRED / SIGNATURE_BLANK`, has no
validated cutoff and emits
`MEASUREMENT_ONLY` with typed limitations (`SYNTHETIC_ONLY`,
`NOT_DIAGNOSTIC`, `NO_VALIDATED_CUTOFF`, `NO_CLINICAL_INFERENCE`,
`NO_CRISIS_INFERENCE`). It must not claim that the synthetic CAT is a valid
psychological instrument. A separate, clearly labelled `SYNTHETIC_TEST_ONLY`
policy may be constructed inside tests with a neutral construct such as
`Synthetic Construct A` solely to exercise a ready/claim path; it is not a
shipped psychology policy.

## 5. Policy hashing and exact selection

The canonical policy hash is SHA-256 over UTF-8 JSON after parsing the policy,
removing `policy_hash`, sorting keys and using separators `(',', ':')` with
`ensure_ascii=False`. The stored value is compared exactly. A missing,
duplicate, malformed or hash-mismatched policy is rejected.

Selection is exact over policy id/version/hash, instrument id/version,
assessment population and trusted execution mode. No wildcard, latest, default,
first-match or generic fallback is allowed. The policy population must equal
the assessment population; content/RAG population is outside this module.

## 6. Status machine and reason codes

The adapter returns one explicit status and one or more stable reason codes;
empty interpretation is never used:

- `READY_FOR_RENDERING`: only a test-only neutral policy may reach this state;
- `MEASUREMENT_ONLY`: accepted synthetic measurement with no psychological
  meaning claims;
- `ABSTAIN_POLICY_MISSING`, `ABSTAIN_POLICY_MISMATCH`,
  `ABSTAIN_POLICY_HASH_MISMATCH`;
- `ABSTAIN_INSTRUMENT_MISMATCH`, `ABSTAIN_VERSION_MISMATCH`,
  `ABSTAIN_POPULATION_MISMATCH`;
- `ABSTAIN_CONSTRUCT_UNAPPROVED`, `ABSTAIN_REAL_USER_BLOCKED`,
  `ABSTAIN_SAFETY_BYPASS`, `ABSTAIN_MODE_NOT_ALLOWED`;
- `ABSTAIN_INPUT_INVALID` for malformed or incomplete assessment data.

Reason codes identify the first deterministic boundary failure and preserve
the trusted context identifiers. They do not expose a psychological diagnosis
or create a Safety action.

## 7. Canonical result contract

The module-owned `interpretation_result.v1` schema contains status, reason
codes, assessment/instrument/policy identity, policy version/hash, typed
role-neutral claim records, typed limitations and audit provenance. Claim
records contain stable machine codes and structured values only. Natural
language, student/teacher/parent presentation, diagnosis, disorder, clinical
severity, suicide/self-harm inference, crisis-risk inference, treatment and
Level 1–5 fields are forbidden.

Raw `theta` and `se` may be read to validate the CAT result, but neither raw
value nor a renderable alias (`score`, `band`, interval or precision-as-risk)
appears in the public result. Any internal audit reference must be opaque or
metadata-only and must not serialize those values. Confidence intervals are
not calculated.

The result never changes or emits Safety actions. If trusted Safety is
`CRISIS_ROUTE`, `REVIEW_REQUIRED` or `BLOCK`, the adapter returns
`ABSTAIN_SAFETY_BYPASS` while preserving that action only as trusted audit
context; all three states are tested separately.

## 8. Modes, population and human review

Only explicitly allowed `SYNTHETIC_DEMO` and `RESEARCH_ONLY` policy scopes may
run. `REAL_USER` is always blocked. The current population direction is
university freshmen, suggested age 17–19; existing consent, privacy and minor
gates remain. Population expansion requires new validation and review,
including measurement invariance/DIF where cross-group comparisons are
proposed. Parent production delivery remains paused; synthetic/demo capability
does not restore production delivery.

Human psychology status, controller scope and evidence identity are stored as
separate policy fields. The adapter must not turn a received review package or
an empty signature into approval.

## 9. Test and verification obligations

The module tests must cover valid assessment validation, deterministic output,
exact policy and hash matching, missing/duplicate policy, instrument/version/
population mismatch, unapproved construct, REAL_USER and untrusted-mode
escalation, all three Safety bypass actions, raw theta/se and forbidden-claim
absence, no network/LLM/RAG imports or calls, test-only ready path, shipped
synthetic measurement-only path and D2-intake exclusion.

The implementation must pass module pytest, Ruff with zero findings, Pyright
with zero errors, compile/import checks, the canonical CAT regression, the
accepted D3-1 regression, Root Gate/OpenAPI and frozen-root blob comparison.
The fresh closure evidence must report actual results and changed files. A
successful D3-2 engineering run is not psychology approval, psychometric or
clinical validity, real-pilot readiness or production readiness.

## 10. Acceptance boundary

Only `03_assessment-adapter`, this D3-2 decision/spec, D3-2 evidence and the
D3-2 machine evaluation may be changed. One local commit is allowed after all
hard gates pass. Merge, push and accepted-tag creation remain prohibited.

The Execution Lead must return the worktree and evidence to the Project
Controller for final review. D3-3, D3-4, D4, D5 and D6 are not started by this
spec.
