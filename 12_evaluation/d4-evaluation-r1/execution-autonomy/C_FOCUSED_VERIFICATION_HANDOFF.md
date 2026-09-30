# C focused verification handoff: D4 execution hardening

## Review request

Independently review the current HEAD of branch `work/d4-3b-formal-run-integration` in `D:\Projects\StudentMentalHealthAI-d4-formal-run`. The change is evaluation-only and limited to `12_evaluation/d4-evaluation-r1/**`. Starting commit before these edits: `35f1ac86fe941aa015cd85163fda50ccddf6a1d7`. Resolve the submitted commit with `git rev-parse HEAD` at review time and inspect the actual diff; this file is not a substitute for source review.

## Required review focus

1. No security-policy bypass, command obfuscation, encoded PowerShell, nested-shell escape, or change to managed/host policy.
2. Every evaluation service launch uses a fixed absolute executable and argv list with `shell=False`; no shell or arbitrary-command endpoint exists.
3. The JSONL supervisor accepts only fixed operations and service names, cannot accept caller-provided executable/argv/env/path/URL/port values, and cannot adopt or stop external listeners.
4. Child environment allowlists, sensitive-log redaction, request validation, audit output, PID ownership, graceful/forced shutdown, and listener-closure verification are sound.
5. Runtime/Ollama identity, manifest integrity, case order, corpus, product semantics, Human Gold, Contract/OpenAPI, RAG mapping, and D3 policy remain unchanged.
6. Changes are confined to `12_evaluation/**`; no secret or credential value appears in code, tests, reports, logs, or JSON artifacts.
7. Direct Git/netstat resolution is absolute and does not create an unexpected external connection.

## Verification already run by Execution Lead

- `pytest -q harness\controlled_product_eval\tests`: 62 passed.
- `pytest -q harness\foundation\test_schema_validation.py`: 24 passed.
- `python -m compileall -q harness`: exit 0.
- Focused supervisor test file: 6 passed.
- Harmless process probes: direct Python, PowerShell, `cmd.exe`, `uv`, Git, and Codex CLI all exited 0; historical `blocked by policy` was not reproduced.
- Current external services were not started, adopted, or stopped. No formal manifest was frozen and no support POST was sent.
- Safe environment-presence checks found DB and synthetic-account variables absent in Process/User/Machine scopes. No secret values were read or emitted.

## Deliverables to inspect

- `harness/controlled_product_eval/process_lifecycle.py`
- `harness/controlled_product_eval/cli.py`
- `harness/controlled_product_eval/supervisor.py`
- `harness/controlled_product_eval/manifest.py`
- `harness/controlled_product_eval/network_integrity.py`
- `harness/deterministic/run_fast_regression.py`
- `harness/controlled_product_eval/tests/test_supervisor.py`
- `execution-autonomy/EXECUTION_POLICY_DIAGNOSIS.md` and `.json`
- `execution-autonomy/DIRECT_LAUNCH_MIGRATION_REPORT.md`
- `execution-autonomy/SUPERVISOR_ARCHITECTURE.md`
- `execution-autonomy/AUTONOMY_REGRESSION_REPORT.md`

## Return contract

Return exactly one of:

- `READY_FOR_D4_3B_AUTONOMOUS_EXECUTION_AFTER_EXECUTOR_HARDENING`
- `CONTROLLER_DECISION_REQUIRED`

For `CONTROLLER_DECISION_REQUIRED`, identify the blocking file/behavior, evidence, root cause, and smallest acceptable correction. Do not run the formal 12 cases, use student credentials, start/stop external services, or declare Controller/project acceptance. If ready, Execution Lead will continue under the already authorized premanifest remediation envelope, while still stopping before login/support POST if required credentials remain absent.
