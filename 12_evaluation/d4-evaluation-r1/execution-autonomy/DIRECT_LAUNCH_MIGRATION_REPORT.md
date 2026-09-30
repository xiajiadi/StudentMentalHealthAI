# D4 direct-launch migration report

## Changes

- `process_lifecycle.py` now requires absolute executable and working-directory paths, starts with argument arrays and `shell=False`, uses a per-profile child-environment allowlist, captures stdout and stderr separately, and redacts sensitive environment values from captured log lines.
- Lifecycle identities now retain executable, redacted arguments, cwd, PID, parent PID, start/stop timestamps, return code, listener/readiness state, ownership, interpreter version, package-lock identity, log paths, and shutdown method. Stop verification checks that the TCP listener closed; an HTTP 404 is no longer treated as proof that a service stopped.
- Managed profiles verify the supplied interpreter directly. Backend must be an absolute `python.exe` reporting Python 3.12; RAG uses its explicit task-local interpreter. The profile records the installed Backend/Database lock hashes or accepted RAG lock hash when the task-local identity files are present.
- Managed `PYTHONPATH` values contain only resolved evaluation-owned source roots. A caller's parent `PYTHONPATH` is not copied into any service profile.
- The Backend child receives only its declared `SMHAI_*` configuration and present `DATABASE_URL` or `DB_*` values. Those values stay in process memory and are excluded from lifecycle records; exact sensitive values are redacted from child stdout/stderr logs.
- Git identity collection and the deterministic harness resolve Git to an absolute executable. Network inventory resolves Windows `netstat.exe` under `SystemRoot\System32` first and invokes it directly.
- Added a persistent D4 JSONL supervisor. It owns only the RAG process, the two observers, and the Backend process it starts. Requests cannot change a service executable, arguments, environment, port, or path.

## Launch and service verification

The controlled launch probes completed successfully: absolute Python 3.14.6, Backend Python 3.12.13, RAG Python 3.12.13, CAT Python 3.14.6, and Runtime Python 3.12.13 reported their versions. The direct generic lifecycle fixture started and stopped a local Python service, verified its listener closed, captured separate streams, and confirmed test-only sensitive text was redacted. A profile regression test sets a caller-controlled `PYTHONPATH` and verifies it is absent from the RAG, observer, and Backend child configurations.

Actual production service starts/stops were deliberately not attempted where an operator-owned listener was already active. The policy is not to adopt or stop those processes. The persistent supervisor’s profiles and current evidence therefore separate code-path verification from live-service lifecycle proof:

| Target | Result | Boundary |
|---|---|---|
| Direct Python child | PASS | Controlled absolute-executable probe and lifecycle fixture |
| Backend Python 3.12 | PASS | Absolute interpreter reported `3.12.13`; managed-run guard rejects another minor version. Backend service itself was not started because its DB credentials are absent. |
| MySQL on 3307 | NOT RUN | Operator-owned MySQL PID 30904 was already listening; not adopted or stopped. |
| Ollama on 11437 | NOT RUN | Operator-owned Ollama PID 30568 was already listening; not adopted or stopped. |
| CAT on 8180 | NOT RUN | Operator-owned CAT PID 8960 was already listening; not adopted or stopped. |
| Runtime HTTP on 8160 | NOT RUN | Operator-owned Runtime PID 13156 was already listening; exact identity was preserved. |
| RAG | CODE PATH PASS / LIVE SERVICE NOT RUN | Fixed absolute Python profile and direct `Popen` lifecycle are covered by tests; no real index was started in this hardening pass. |
| Observers | CODE PATH PASS / LIVE SERVICE NOT RUN | Fixed absolute Python profiles and direct lifecycle are covered by tests; no observer was started beside the active external dependencies. |
| Safety and OPA | EXTERNAL | Remain operator-managed under the current formal boundary. |

## PowerShell and shell audit

- No `shell=True`, PowerShell executable, `Start-Process`, or `cmd.exe /c` service launcher remains in the D4-3B Python source paths.
- Direct launch call sites in the D4-3B harness now resolve Python, Git, and `netstat.exe` to absolute executable paths. Service creation uses `subprocess.Popen(..., shell=False)`.
- The R4 task-tools artifact `OPERATOR_RUNTIME_ONLY_LAUNCH.ps1` still exists as historical evidence and contains `Start-Process`. It was not executed or edited; the already-running Runtime process was not disturbed. The new supervisor does not call that artifact. If operators continue to use the historical script for a future Runtime restart, that restart remains PowerShell-based until the Runtime lifecycle is separately migrated and its ownership/evidence semantics are reviewed.
- The README retains PowerShell examples for setting process-local values and invoking the normal CLI. These examples are command entry points, not nested service launchers. The supervisor itself starts each owned service directly.

## Protected behavior

The change does not modify product code, Human Gold, Contract/OpenAPI, RAG mappings, D3 policy, Runtime identity, case order, or corpus content. The changed source and test files are under `12_evaluation/**`. Existing MySQL, CAT, OPA, Safety, Runtime, and Ollama processes remain untouched.

## Limits

The historical `blocked by policy` error did not recur, so there is no current rejection to attribute to or fix. The actual external MySQL/CAT/Ollama/Runtime lifecycles were not restarted to prove direct startup because those services were already active and are outside this supervisor’s ownership. Formal execution remains gated by independent C review and the missing local database and synthetic-account credentials.
