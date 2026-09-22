# D4-2R · Initial deterministic regression failure preservation

This record preserves the first D4-2 deterministic run before the D4-2R
repair. It is evidence-only and does not change the accepted product,
contracts, D3 behavior, or D4-1 history.

## Initial run binding

- Baseline commit: `d712e466ae63a412808f5598373a7e769f276e2f`
- Branch: `exp/d4-deterministic-regression-v1`
- Initial run ID: `D4RUN-20260922T154800Z-d42p0`
- Initial manifest: `12_evaluation/d4-evaluation-r1/manifests/d4_slice2_fast_regression.json`
- Initial manifest hash: `e5b534936a68d3622d4243b472403be1a92b48e99eeb1789ae490719892640e6`
- Accepted foundation tag: `d4-slice1-r1-accepted` → `05ce1fe59796a4f079e74cc2f425943040dd706a`
- Dataset hash: `0155799e89ee1534baec32a4d9f9f392d44b357d4a7db1b04696c1cb1888f5bb`
- Fixture: exact D3 assessment fixture, SHA-256
  `174c27a4dccbb9e5656afa1d7d79db1920c610768c67ec0705bc58eff7c61398`

The initial scheduled set contained 16 `REGRESSION` cases. Its machine
evidence is preserved by the initial immutable manifest and the current
16-case evidence batch. The initial run reported 15 PASS and one D4E-26 FAIL.
The D4E-55 record carried the accepted product's `TX_` transaction identity
as a limitation against the then-current `TXN_` evidence pattern; D4-2R
reclassifies that mismatch as an explicit evidence `ERROR` rather than a
product PASS.

## Findings preserved for repair

### D4E-26 · hidden existence side channel

The canonical assessment probe returned distinguishable public envelopes:

| Probe | HTTP | Problem code |
|---|---:|---|
| Existing assessment outside the caller's scope | 403 | `forbidden` |
| Unknown assessment identifier | 404 | `resource_not_found` |

The detail also differed (`access denied` versus `assessment not found`). This
was recorded as `observed_outcome=FAIL` and `failure_type=AUTHZ_FAILURE`.

### D4E-55 · transaction evidence mismatch

The accepted product emits `TX_` transaction identifiers. The D4 evidence
schema required `TXN_`, so the evidence layer could not bind the product
transaction identity exactly. D4-2R must correct the evaluation schema to the
actual generator format without changing the product identifier.

### D4-1 foundation fixture mismatch

The accepted D4-1 foundation records expected
`7a18e4a995fe54f00f8d8e0cb5e34b30ae7f99e02f72793391152a3fff6dcc01` for
`datasets/fixtures/synthetic_assessment.v1.json`, while the D4 snapshot
present at the baseline hashed to
`cea8c09796ee0c92ced891b6fc7e1d1114fd4a264262a0ca5bfe375f31e40d61`.
The exact D3 product fixture used by D4-2 hashed to
`174c27a4dccbb9e5656afa1d7d79db1920c610768c67ec0705bc58eff7c61398`.
No hash was rewritten in this preservation record.

### D4E-27 · bounded route inventory

The initial wrapper checked the actual canonical routes and confirmed no
direct Runtime or legacy renderer route. It did not fabricate calls to
nonexistent prompt, preview, retry, or regenerate endpoints. D4-2R must bind
those families to an authoritative runtime/OpenAPI/router/static inventory.

## Scope guard

No product repair, merge, push, tag, Promptfoo run, model call, external
network call, D4-3 implementation, or real-student data was used to preserve
this evidence.
