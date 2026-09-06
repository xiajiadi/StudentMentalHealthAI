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
