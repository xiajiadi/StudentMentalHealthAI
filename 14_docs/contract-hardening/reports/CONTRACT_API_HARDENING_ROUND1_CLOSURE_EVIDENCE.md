# Contract/API Hardening Round 1 Closure Evidence

Closure date: 2026-09-07 (Asia/Shanghai)
Repository: `D:\Projects\StudentMentalHealthAI`
Candidate: `00_architecture/contracts/candidates/openapi.hardened.candidate.json`
Candidate SHA-256: `556ED7A3F777D83C0DE828DF08B7AC51A730ACEDCBE42B9153D4B4414C5F1940`

## 1 Previous Controller Verdict

The previous controller verdict was `PARTIAL PASS` on 2026-09-06. It left four
material gaps: unclassified oasdiff findings, normal/crisis Respect workflows
blocked by opaque-cookie handoff, unavailable live MySQL persistence evidence,
and no fresh browser run counted for this hardening round.

## 2 Closure Scope

This closure covers the candidate-only API hardening round, its frontend
consumer, the three Arazzo workflows, the isolated real MySQL environment,
fresh browser evidence, and local Git reconciliation. The frozen v0.1.0 root
contract remains read-only. No real student data, clinical claim, notification,
remote operation, release, or root-contract promotion was performed.

## 3 Git State

The reconstructed chain is:

| Role | Commit |
|---|---|
| Accepted baseline | `65c3df2c28f955a3cbadfc3e01c466d6d89f81a6` (`integration-r1-accepted`) |
| Runtime cleanup | `dfbf1bd61845b31b5d1c1bd28ddf1325669d7969` |
| Hardening implementation | `a65ac71897a2a26fb157d04b4f253eb01af65f58` |
| Hardening evidence | `160db3cb5452cdf1cef17b2e9334f3ddd3314c58` |
| Pre-closure evidence head | `1ca4248384b0c8b63383515ceeebbf80509455f4` |
| Closure candidate | `455960fbb0b56433df513d5a255573900559f67e` |

There is no configured remote. The accepted baseline tag remains unchanged;
`contract-hardening-r1-accepted` was not created. Push, merge, release, and
promotion were not performed.

## 4 Frozen Root Integrity

The following hashes were computed before and after the closure work and were
identical in both snapshots:

| Frozen artifact | SHA-256 |
|---|---|
| `00_architecture/openapi.v1.json` | `235C8FDB0B35F2DE870127A18D4CD8C72A1C7795AF02656B2A6C7274AB071897` |
| `00_architecture/schemas/assessment.v1.schema.json` | `56B9FC990261D0B826EEEA0E84417754798EF3A980F50A414CCB565168375A52` |
| `00_architecture/schemas/knowledge.v1.schema.json` | `5334533DB35B30840F57E8012208037A6809BFED7CE08094BDA1517C801D8BCF` |
| `00_architecture/schemas/generation.v1.schema.json` | `8365D7EA825A30D9429361107750E87E8C6446D0A6576C47F3A8ECE564DCA62C` |
| `00_architecture/schemas/config.v1.schema.json` | `65F378B8D0C0080E484F3947D6A11A48B14186F43B23A6EDA7B5DC321B395D16` |
| `00_architecture/schemas/logging.v1.schema.json` | `88A95532F42C2077959D6360844DF4EB0490342AF78492BC0D81C8AE9190256D` |
| `CONTRACTS.md` | `2AE5320C5B12EFE57DD90D7352AE192D1BEE8387B595E36DDD3919B90C486CBB` |

Result: `modified=false` and the official root gate remains `13/13`.

## 5 oasdiff Reclassification

Pinned tool: `D:\Dev\tools\oasdiff\1.28.0\oasdiff.exe`. The raw commands were
run with `breaking --format text --fail-on ERR --color never` and retained their
non-zero detector exit because genuine candidate findings remain visible.

| Comparison | Raw result | Intentional pre-promotion | Expected surface | False positive with evidence | Unintentional | Unclassified | Pending owner |
|---|---:|---:|---:|---:|---:|---:|---:|
| Integration → hardened | `76 ERR / 7 WARN` | 15 | 0 | 61 | 0 | 0 | 0 |
| Frozen root → hardened | `15 ERR / 7 WARN` | 0 | 15 | 0 | 0 | 0 | 0 |

The 61 integration false positives are the OpenAPI 3.0 list-of-types versus
OpenAPI 3.1 nullable representation of RFC 9457 `instance`. Runtime evidence
shows `instance: null`. The `createGeneration` corrections are candidate-only
typed provenance changes; the frozen root was not edited. Full raw JSON and
per-finding classification are in `evidence/oasdiff-closure-*`.

## 6 Compatibility Remediation

The source changes add a typed legacy error projection, explicitly nullable
`instance`, stable uppercase error codes, and literal contract versions. RAG
chunks and assessment projections now carry required schema versions. The
candidate was regenerated from the FastAPI/Pydantic source; no broad oasdiff
ignore, frozen-root edit, or security weakening was used.

## 7 Respect Cookie/Session Decision

Pinned Redocly Respect: `2.51.2`. Native `x-security` forwarding sent the full
`Set-Cookie` attribute string as a cookie value, which the actual Backend
correctly rejected. The closure uses a loopback-only, in-memory cookie-pair
bridge for the engineering workflow: it captures `Set-Cookie`, forwards only
the legal `name=value` pair, preserves server-side HttpOnly handling, and does
not change production authentication or CSRF validation. The installed tool's
official references are [Respect command documentation](https://redocly.com/docs/respect/commands/respect),
[x-security](https://redocly.com/docs/respect/extensions/x-security), and
[Arazzo testing guidance](https://redocly.com/docs/respect/guides/test-api-sequences).

## 8 Respect Normal Workflow

`normal_support.arazzo.yaml`: 1 workflow, 4 steps, 16 checks, exit 0. Login,
assessment start, assessment completion, and support creation returned the
expected successful contract results. The normal route produced
`PROCEED_WITH_BOUNDARY`, `normal_generation=true`, citations, retrieval
identity, and executed model provenance. Sanitized evidence:
`evidence/respect-normal-closure.json`.

## 9 Respect Reviewer Workflow

`review_queue.arazzo.yaml`: 1 workflow, 2 steps, 8 checks, exit 0. The reviewer
session authenticated and read the queue through the actual Backend. Sanitized
evidence: `evidence/respect-reviewer-closure.json`.

## 10 Respect Crisis Workflow

`crisis_route.arazzo.yaml`: 1 workflow, 4 steps, 17 checks, exit 0. The route
returned `CRISIS_ROUTE`, no content, zero citations, `RETR_not_run`,
`generation_status=NOT_RUN`, `candidate_source=NOT_RUN`, and null model
identity. Sanitized evidence: `evidence/respect-crisis-closure.json`.

## 11 Real MySQL Environment

The closure used the isolated loopback MySQL environment
`smhai_contract_hardening_closure_20260907_005908`, MySQL `8.4.8 Community`,
`utf8mb4`, and UTC session time zone. All records were synthetic/deidentified.
The sanitized captures are `evidence/mysql-closure-capture.json` and
`evidence/mysql-closure-post-restart.json`.

## 12 Migration Stairway

Migration results were: initial upgrade to head `PASS`; downgrade to
`20260905_0001` `PASS`; provenance-column checkpoint `3`; re-upgrade to head
`20260906_0002` `PASS`; final migration check `PASS`; final provenance-column
count `7`. The machine stairway record is retained in the external closure run
directory and the final database state is represented in the sanitized MySQL
evidence.

## 13 Real MySQL Provenance Round Trip

The real HTTP composition returned five citations and persisted five evidence
rows for the same report. API and database citation identity matched exactly.
The report run was `COMPLETED` with `PROCEED_WITH_BOUNDARY`, retrieval identity
`RETR_eda418856f55e81cc1ec`, and generation identity
`GEN_67ef5a6846064c0789dcb67445ed2b84`. Two message payloads remained encrypted
with byte lengths `[332, 2104]`; plaintext probe matches were `0`,
`silent_truncation=false`, and `plaintext_not_persisted=true`.

## 14 Process-Restart / New-Session Readback

After Backend restart, a new session read back the same report through the API.
The post-restart capture retained five citations and the same canonical
identity set, with `identity_match=true`. The fresh integration smoke state
also recorded session rehydration and the reviewer approval path.

## 15 Database Regression

Command: `11_database/.venv/Scripts/pytest.exe -q` with the isolated MySQL
`DATABASE_URL` and `DATABASE_KEY_FILE`. Result: `16 passed in 0.22s`,
`0 failed`, `0 skipped`, `0 deselected`. Ruff and Pyright both passed with zero
reported errors, warnings, or informations.

## 16 Fresh Playwright Login

Command executed from `10_frontend` with
`PLAYWRIGHT_BROWSERS_PATH=D:\Dev\caches\ms-playwright`,
`VITE_API_MODE=real`, and `VITE_API_BASE_URL=http://127.0.0.1:8080`. The login
flow passed. The browser context contained the server session cookie with
HttpOnly and SameSite=Lax; `document.cookie` and local storage did not expose a
session token.

## 17 Fresh Playwright Normal

The normal student flow passed against the real Backend and real module HTTP
adapters. It completed the CAT interaction, displayed real module labels,
multiple citations, generation provenance, and report readback. No browser
console or page error was recorded.

## 18 Fresh Playwright Crisis

The direct browser crisis flow passed. It verified `CRISIS_ROUTE`, no content,
no citations, `RETR_not_run`, `NOT_RUN`, null model identity, and no normal
retrieval or generation call. No browser console or page error was recorded.

## 19 Fresh Playwright Reviewer

The reviewer flow passed. It created a fresh crisis case, loaded the reviewer
queue and detail, approved the case, and verified the resulting approved
status. No browser console or page error was recorded.

## 20 Redocly

Pinned Redocly CLI `2.51.2` linted the candidate with the repository config:
`0 errors`, `0 warnings`, `0 ignored`. The JSON output is the current command
result, not a health-endpoint proxy.

## 21 Schemathesis

Pinned Schemathesis `4.25.2` ran against the real Backend at
`http://127.0.0.1:8080` using the candidate. Coverage/fuzzing tested `21/21`
operations with `665 generated / 665 passed`; stateful testing ran `5`
scenarios with `30 generated / 30 passed`. The two expected auth/schema
warnings were retained and no failures occurred. NDJSON output was retained in
the external closure run directory.

## 22 SDK Generation

Pinned `@hey-api/openapi-ts` `0.99.0` with `@hey-api/client-fetch` generated
separate output directories twice. Both had 16 files, were byte-identical, and
both matched all 16 canonical files in `10_frontend/src/api/generated`. No
generated file was manually edited. Machine evidence:
`evidence/sdk-generation-closure.json`.

## 23 Root Contract

Command: `00_architecture/tests/run_contract_checks.ps1`. Result: `Ran 13
tests ... OK` and `A-phase contract, Schema, and OpenAPI checks passed.` The
seven frozen artifacts in section 4 are byte-identical before and after the
closure.

## 24 Gitleaks

Pinned Gitleaks `8.30.1` was run against the final working tree, Git history,
and the final staged tree with redacted JSON output. The closure evidence records
`0` findings in each scan and `0` confirmed secrets. Raw scan output is kept
outside the repository; the committed summary is
`evidence/gitleaks-closure-summary.json`.

## 25 Remaining Limitations

- The candidate remains a proposal for a future v0.2 contract. The
  `createGeneration` compatibility corrections still require contract-owner
  approval, explicit versioning, and migration planning.
- Respect closure workflows use a contract-fake Arazzo fixture to validate the
  workflow/tool/session boundary; they do not claim that Respect itself ran the
  real CAT/RAG/LLM/Safety composition. Real module composition is evidenced
  separately by the MySQL round trip and fresh real-mode Playwright flow.
- The project remains synthetic/deidentified and non-clinical. No release or
  production deployment was attempted.

## 26 Closure Recommendation

Recommendation: **FULL PASS for Contract/API Hardening Round 1 acceptance
closure**. All P0 closure gates and Git reconciliation passed. Keep the root
v0.1.0 contract frozen, keep the v0.2 candidate proposal-only, and defer any
promotion or remote action until the contract owner approves the classified
compatibility/migration decision.
