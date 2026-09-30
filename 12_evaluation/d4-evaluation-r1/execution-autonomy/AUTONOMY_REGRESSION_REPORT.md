# D4 autonomy and regression report

## Source and scope

- Starting commit: `35f1ac86fe941aa015cd85163fda50ccddf6a1d7`.
- Working branch: `work/d4-3b-formal-run-integration`.
- All edits are confined to `12_evaluation/d4-evaluation-r1/**`.
- Product code, Human Gold, Contract/OpenAPI, RAG mappings, D3 policy, Runtime identity, case order, and corpus files have no changes.
- No formal manifest was frozen and no formal support POST was sent.
- Existing external service processes were not started, adopted, or stopped.

## Verification results

| Check | Result | Evidence |
|---|---|---|
| Supervisor-focused tests | PASS | `6 passed in 3.14s` |
| Full `controlled_product_eval/tests` suite | PASS | `62 passed in 39.38s`; includes runner-integrity, observer/profile, and supervisor coverage |
| Schema validation tests | PASS | `24 passed in 0.32s` |
| Evaluation harness compileall | PASS | `python -m compileall -q harness`, exit 0 |
| Backend interpreter | PASS | Direct task-local Python reports `3.12.13`; managed Backend rejects non-3.12 versions |
| RAG interpreter and lock identity | PASS | Absolute task-local interpreter reports `3.12.13`; accepted task-local lock hash is included when identity files match |
| Process environment allowlist | PASS | Parent-only test variable is excluded; unapproved profile variable is rejected |
| Secret redaction and stream separation | PASS | Test-only sentinel is absent from both log files; `<redacted>` appears in stdout and stderr logs |
| PID ownership and cleanup | PASS | Harmless loopback fixture starts through absolute Python, records PID/parent PID, then verifies process exit and listener closure |
| Static shell-launcher scan | PASS | No `shell=True`, `powershell.exe`, `pwsh.exe`, `Start-Process`, or `cmd.exe /c` service launch in D4-3B Python source |
| Policy probe matrix | PASS | Python, PowerShell, `cmd.exe`, `uv`, Git, and Codex CLI probes all exited 0; no current rejection reproduced |
| `git diff --check` | PASS | No whitespace errors |
| Scope scan | PASS | Changed paths remain under `12_evaluation/**` |

The source tests validate the process manager with an isolated harmless HTTP fixture. They do not claim that a live MySQL, Ollama, CAT, Runtime, RAG index, observer, or Backend service was restarted. Live external services were left untouched, and Backend startup is blocked by missing DB environment values.

## Network and formal-run boundaries

- D4 endpoints remain pinned to Runtime HTTP `127.0.0.1:8160`, Ollama `127.0.0.1:11437`, and MySQL `127.0.0.1:3307`.
- No code path adds a connection to `11434` or `3306`; the database validator rejects port 3306 before Backend startup. Network inventory reads the Windows TCP table rather than opening these endpoints.
- The changed tests use local fixtures and mock transports. No student data or real pilot data was used.
- Safe environment-presence checks found `DATABASE_URL`, all `DB_*` variables, and both synthetic-account password variables absent from Process, User, and Machine scopes. The check emitted only presence booleans. No password value was inspected, changed, or substituted.
- Formal login, support POSTs, manifest freeze, evidence freeze, and C post-run remain unperformed pending focused independent C review and the required credentials.

## Review disposition

Engineering tests pass for the changed evaluation harness. This is a handoff for focused C review, not project acceptance. C should inspect the actual diff and confirm the absence of policy bypasses, shell escapes, arbitrary command execution, evidence-semantic changes, Runtime identity drift, manifest weakening, sensitive-value serialization, and changes outside the authorized scope.
