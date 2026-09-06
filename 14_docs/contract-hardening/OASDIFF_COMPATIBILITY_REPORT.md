# oasdiff Compatibility Report

Date: 2026-09-06
Tool: oasdiff 1.28.0
Evidence: `evidence/oasdiff-run.json`, `evidence/oasdiff-integration-to-hardened.txt`, and `evidence/oasdiff-frozen-root-to-hardened.txt`

## Executed comparisons

| Base | Revision | Result | Summary |
|---|---|---|---|
| `15_demo/integration/contracts/openapi.integration.candidate.json` | `00_architecture/contracts/candidates/openapi.hardened.candidate.json` | exit 1 | 233 changes: 226 errors, 7 warnings |
| `00_architecture/openapi.v1.json` | `00_architecture/contracts/candidates/openapi.hardened.candidate.json` | exit 1 | 50 changes: 43 errors, 7 warnings |

The command used `breaking --format text --fail-on ERR --color never`. Findings
were retained; no ignore file or severity suppression was used.

## Main findings

- The source-generated candidate removes legacy `error` response properties
  from several 400/422 shapes and makes some Problem Details fields nullable or
  optional relative to the manually patched integration candidate.
- The hardened candidate removes some legacy response `schema_version` const
  constraints where the new response DTO is a projection rather than a frozen
  root payload.
- Comparing with the frozen root also detects newly required structured
  generation request fields and tightened request enums/length constraints.
- oasdiff reports seven warnings for request max lengths and additive response
  enum values.

These are public compatibility findings, not a reason to edit the frozen root
document or to hide the detector output. The old integration candidate was
manually patched and is not the source of truth, but it is still the last
accepted browser-facing candidate and therefore the relevant migration base.

## Decision

Compatibility is **not clean**. The hardened document remains a valid
candidate for review, but it is not ready for root v0.2 promotion. A future
promotion must either preserve the affected fields, publish an explicitly
versioned/migrated contract with owner approval, or document an approved
 breaking-change plan. This round has no authority to make that decision.

# Acceptance Closure Reclassification

Closure date: 2026-09-07

The historical result above is preserved. The closure reran the same pinned
oasdiff version (`1.28.0`) with the following commands, without an ignore file
or severity suppression:

```text
D:\Dev\tools\oasdiff\1.28.0\oasdiff.exe breaking 15_demo\integration\contracts\openapi.integration.candidate.json 00_architecture\contracts\candidates\openapi.hardened.candidate.json --format text --fail-on ERR --color never
D:\Dev\tools\oasdiff\1.28.0\oasdiff.exe breaking 00_architecture\openapi.v1.json 00_architecture\contracts\candidates\openapi.hardened.candidate.json --format text --fail-on ERR --color never
```

Fresh raw results are recorded in
`evidence/oasdiff-closure-raw-integration-to-hardened.txt` and
`evidence/oasdiff-closure-raw-frozen-root-to-hardened.txt`. The machine-readable
per-finding classification is
`evidence/oasdiff-closure-classification.json`.

## Previous state

The historical machine evaluation recorded 226 integration errors and 43
frozen-root errors as unintentional breaks. That conclusion was not carried
forward automatically. The closure reran the comparison after the source DTO
and typed-error corrections and classified every current finding individually.

## Closure state

| Comparison | Raw errors | Raw warnings | Intentional pre-promotion | Expected surface difference | False positive with evidence | Unintentional | Unclassified | Pending owner decisions |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Integration → hardened | 76 | 7 | 15 | 0 | 61 | 0 | 0 | 0 |
| Frozen root → hardened | 15 | 7 | 0 | 15 | 0 | 0 | 0 | 0 |

The 61 integration false positives are the OpenAPI 3.0 type-array versus
OpenAPI 3.1 `anyOf` representation of the nullable RFC 9457 `instance` field.
The live unauthorized response evidence records the typed `instance: null`
value and redacts request and trace identifiers.

The 15 integration intentional corrections and 15 frozen-root surface
differences are all on `createGeneration`. They correspond to the candidate's
typed generation/provenance DTO: stable IDs, schema version, retrieval/prompt
references, model policy, bounded enums, and identifier patterns. The frozen
root remains byte-identical and is not promoted by this closure. The seven
warnings in each comparison remain visible and are classified as
`NON_BREAKING / WARNING`.

## Source fixes and compatibility decision

- Problem Details now has a typed legacy error projection and an explicitly
  nullable `instance`; the runtime response is validated in
  `evidence/oasdiff-closure-runtime-problem-details.json`.
- Generation provenance is expressed in source DTOs and tested through the
  backend contract tests; generated OpenAPI remains source-derived.
- No broad oasdiff ignore, frozen-root edit, security weakening, or owner
  decision was used.

Closure gates are therefore: `unintentional_breaks = 0`,
`unclassified_findings = 0`, and `pending_owner_decisions = 0`. The raw
detector exit status remains non-zero because genuine candidate warnings and
pre-promotion/surface-difference findings are intentionally retained for the
future v0.2 promotion decision.
