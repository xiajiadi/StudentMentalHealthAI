# D4 Slice 3A Citation / Utility Foundation Evidence

**Disposition: PARTIAL**

The evaluation foundation and draft human-review packet are technically ready for Controller / designated human review. Human Gold is not approved. The strict no-network execution condition was violated by a Worker tool download, so this handoff does not claim full compliance with the frozen HANDOFF.

## Baseline and scope

- D4-3A baseline commit: `cac95b9a4012d8aa13bd648d278dea92c1034c95`
- D4-2 accepted tag target: `d4-slice2-r1-accepted` → `2ead2fd6a131f34c2cc7cb71274aed04ce935053`
- Branch: `exp/d4-citation-utility-foundation-v1`
- Worktree: `D:\Projects\StudentMentalHealthAI-d4-citation-utility`
- Product source changed: no.
- D3, Root/OpenAPI contracts, and D2 publication state changed: no.
- D4-3B started: no. Real pilot remains BLOCKED.

## Evaluation assets

The synthetic citation-support dataset is `12_evaluation/d4-evaluation-r1/datasets/citation_utility/dev/citation_support/cases.v1.json`. It contains 7 cases and 7 claims; its dataset identity is `D4SUP_DEV_SYNTHETIC_V1`, with canonical dataset hash `sha256:4ff97838c8ea641651898b2d8ed01616bbcc1a37064511cd1caad9d624771d42`. The draft label distribution is SUPPORTS 1, PARTIALLY_SUPPORTS 1, UNSUPPORTED 1, CONTRADICTS 1, and OUT_OF_SCOPE 3. All 7 cases remain under human review.

The synthetic answerability dataset is `12_evaluation/d4-evaluation-r1/datasets/citation_utility/dev/answerability/cases.v1.json`. It contains 12 draft cases: MUST_ANSWER 5, SHOULD_ABSTAIN 4, SHOULD_ANSWER 1, MUST_ROUTE 1, and MUST_DENY 1. Six paired controls cover evidence availability, population applicability, role applicability, purpose applicability, qualifier/route, and authorization. Its file SHA-256 is `c522f016646ff420a8973c652d610e505e8215b69560a1a5827c0a8a03c3af27`.

The review packet is:

- `12_evaluation/d4-evaluation-r1/D4_3A_HUMAN_GOLD_REVIEW_PACKET.json`
- `12_evaluation/d4-evaluation-r1/D4_3A_HUMAN_GOLD_REVIEW_PACKET.md`

Packet ID: `D4-PACKET-SLICE3A-CITATION-UTILITY-R1`. Packet hash: `sha256:8b2e83469888fc195dbf9baea1389f97ab5dcaa0c48e83c9c5ae1efcf25cbe67`. It binds both source datasets and contains all 7 citation cases and 12 answerability controls. The Markdown version includes claim text and spans, evidence text and identity, textual entailment, final support label, applicability dimensions, traceability, target scope, evidence bindings, and blank reviewer decision/notes fields.

All evaluation content carries the fixed boundaries: `SYNTHETIC_EVALUATION_ONLY`, `NOT_D2_PUBLICATION`, `NOT_PRODUCTION_KNOWLEDGE`, `NOT_REAL_STUDENT_DATA`, and `NOT_PSYCHOLOGY_VALIDATION`. Pending D2 intake was not used.

## Evaluation and review controls

Claim segmentation is deterministic sentence-boundary splitting with preserved original text, half-open Python-codepoint offsets, stable hashes, and ORIGIN/SPLIT/MERGE/EDIT/EXCLUDE trace support. Segmentation does not infer support. Citation identity is derived separately from textual entailment; a valid source ID can accompany an UNSUPPORTED claim. Population, role, and purpose applicability remain separate fields. Source-dependent scope limitations require an explicit citation-policy override.

Review states are DRAFT, HUMAN_REVIEW_REQUIRED, HUMAN_APPROVED, HUMAN_REJECTED, and DISPUTED. A real approval requires reviewer identity, time, and review evidence reference. A simulated approval must carry `TEST_FIXTURE_SIMULATED_APPROVAL` and is not Human Gold. The packet has no approved items; 19 cases/claims await human review.

Metric formula version is `d4-citation-utility-formulas.v1`. Reports retain formulas, numerators, denominators, included/excluded case IDs, pending-review counts, limitations, and null reasons. Full support and partial-or-better support are reported separately. Unsupported and contradicted claims remain separate; contradiction uses textual entailment even when the final label is OUT_OF_SCOPE. Population, role, and purpose are separately represented. False refusal is limited to complete HUMAN_APPROVED MUST_ANSWER records; MUST_ANSWER routing/safety-stop/abstention/denial is treated as refusal, while SHOULD_ANSWER human-safe routing is not. Rejected annotations are excluded. No product-output utility metrics were computed because D4-3A makes no model or product calls.

## Verification

| Gate | Result |
| --- | --- |
| Citation / utility harness | 56 passed |
| D4-1 full foundation suite | 37 passed |
| D4-2 deterministic regression | 16 passed |
| Ruff check | PASS |
| Ruff format check | PASS, 10 files already formatted |
| Python compile/import | PASS |
| Root contract tests | 13/13 passed |
| OpenAPI validator | PASS, run from the existing local Backend regression environment |
| Frozen Root | 8/8 unchanged; `00_architecture` has no candidate diff |
| Pyright | N/A; no D4 evaluation Pyright configuration |
| Product source diff | EMPTY |

The standard Root wrapper itself returned nonzero after its 13 contract tests passed because its newly created `09_backend/.venv` lacked the optional `openapi_spec_validator` test dependency. The wrapper created the environment and reported installing 34 packages; whether those packages came exclusively from local cache was not captured. The OpenAPI validator was then run directly from the existing local Backend regression environment and passed. No Root/OpenAPI file was changed.

Worker A completed Claim/Citation/Applicability implementation and focused tests. Worker B completed answerability, metric, and packet implementation and focused tests. Worker C completed an independent read-only review with no remaining findings after the fixes. The Execution Lead reran the full D4-3A harness, D4-1, D4-2, Root tests, OpenAPI, Ruff, format, compile, and scope checks.

## Execution deviation

Worker A installed Ruff 0.16.6 with `python -m pip install --target D:\Dev\tools\ruff-0.16.6 ruff==0.16.6`, downloading a 10.6 MB wheel and making an external network request. No project source, synthetic evaluation data, credentials, or student data were sent. The download violates the HANDOFF's explicit no-external-network condition. The Ruff installation is outside the repository. Subsequent direct test and validator commands used existing local tools and environments; the Root wrapper's package source was not independently audited. Because the no-network condition cannot be restored retroactively, the overall disposition remains PARTIAL even though the technical gates are green.

No Promptfoo, Ragas, or ARES was installed or used. No model calls, real-student data, D2 pending intake, merge, push, tag, or D4-3B work occurred.

## Controller review focus

Please review the technical foundation and the draft claim/answerability judgments in the packet. Do not interpret them as approved Human Gold, psychology approval, clinical validation, real-pilot authorization, or production enablement. A separate decision is also required on whether the documented Ruff download deviation is acceptable for this slice.
