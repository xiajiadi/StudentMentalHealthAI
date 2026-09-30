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
| Supervisor-focused tests | PASS | `8 passed in 3.09s` |
| Managed-profile import-path regression | PASS | `1 passed, 39 deselected`; a parent-controlled `PYTHONPATH` was excluded |
| Full `controlled_product_eval/tests` suite | PASS | `64 passed in 40.45s`; includes runner-integrity, observer/profile, and supervisor coverage |
| Schema validation tests | PASS | `24 passed in 0.30s` |
| Evaluation harness compileall | PASS | `python -m compileall -q harness`, exit 0 |
| Backend interpreter | PASS | Direct task-local Python reports `3.12.13`; managed Backend rejects non-3.12 versions |
| RAG interpreter and lock identity | PASS | Absolute task-local interpreter reports `3.12.13`; accepted task-local lock hash is included when identity files match |
| Process environment allowlist | PASS | Parent-only test variable is excluded; unapproved profile variable is rejected |
| Import path isolation | PASS | A parent-controlled `PYTHONPATH` is set in the profile test and does not appear in RAG, observer, or Backend child paths |
| Secret redaction and stream separation | PASS | Test-only sentinel is absent from both log files; `<redacted>` appears in stdout and stderr logs |
| PID ownership and cleanup | PASS | Harmless loopback fixture starts through absolute Python, records PID/parent PID, then verifies process exit and listener closure |
| Static shell-launcher scan | PASS | No `shell=True`, `powershell.exe`, `pwsh.exe`, `Start-Process`, or `cmd.exe /c` service launch in D4-3B Python source |
| Policy probe matrix | PASS | Python, PowerShell, `cmd.exe`, `uv`, Git, and Codex CLI probes all exited 0; no current rejection reproduced |
| `git diff --check` | PASS | No whitespace errors |
| Scope scan | PASS | Changed paths remain under `12_evaluation/**` |

The source tests validate the process manager with an isolated harmless HTTP fixture. They do not claim that a live MySQL, Ollama, CAT, Runtime, RAG index, observer, or Backend service was restarted. Live external services were left untouched, and Backend startup is blocked by missing DB environment values.

One quiet supervisor-only invocation returned exit code 1 with no output. The immediate verbose rerun passed all six tests, and the full 62-test suite passed. The transient empty result was not reproduced; its cause is unknown.

## Network and formal-run boundaries

- D4 endpoints remain pinned to Runtime HTTP `127.0.0.1:8160`, Ollama `127.0.0.1:11437`, and MySQL `127.0.0.1:3307`.
- No code path adds a connection to `11434` or `3306`; the database validator rejects port 3306 before Backend startup. Network inventory reads the Windows TCP table rather than opening these endpoints.
- The changed tests use local fixtures and mock transports. No student data or real pilot data was used.
- Safe environment-presence checks found `DATABASE_URL`, all `DB_*` variables, and both synthetic-account password variables absent from Process, User, and Machine scopes. The check emitted only presence booleans. No password value was inspected, changed, or substituted.
- Formal login, support POSTs, manifest freeze, evidence freeze, and C post-run remain unperformed. Required DB and synthetic-account credential variables and exact target names are absent; one unclassified target name was not used.

## C review and post-review attempt

The focused C review of commit `7d66cfdaf3c8e57f824668db3fdf4e895807c338` returned `READY_FOR_D4_3B_AUTONOMOUS_EXECUTION_AFTER_EXECUTOR_HARDENING`. It confirmed the parent `PYTHONPATH`, caller-selected interpreter, and managed-spec path findings were cleared. The source HEAD reviewed by C is unchanged; the later edits record the post-review attempt and status only. The ready result authorized premanifest continuation only and did not represent project acceptance.

A fresh attempt record was created at `D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\formal-run-r5-20260930T161228Z\preflight\root-state.json`. The current process/user/machine environment has no DB or synthetic-account credential variables. Credential Manager had one unclassified target name matching a coarse D4/SMHAI filter, but no exact A/B or DB target. Its value was not fetched or used. The attempt stopped before Backend startup, login, manifest freeze, RAG indexing, or support POST.

## Review disposition

The first C review of commit `c14f403c98f7b7d443ebf05f1c6bc3c01354ce63` found a P1: the profile builder appended the parent process `PYTHONPATH`. The next review confirmed that fix and found a second P1: the managed CLI accepted caller-selected interpreters. The follow-up pins Backend and RAG paths in one module, enforces them in the managed CLI and spec builder, checks accepted environment lock identities, and adds rejection tests. C re-reviewed commit `7d66cfdaf3c8e57f824668db3fdf4e895807c338` and returned `READY_FOR_D4_3B_AUTONOMOUS_EXECUTION_AFTER_EXECUTOR_HARDENING`. The later edits are report updates only and do not change the reviewed source. This is not project acceptance.
