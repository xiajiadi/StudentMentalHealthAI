# D4 persistent supervisor architecture

## Transport choice

The supervisor is one long-lived Python process using newline-delimited JSON on stdin/stdout. This fits the current Codex process-session interface: launch once, then send individual requests through the existing process handle. It opens no socket, needs no API token, and avoids a localhost HTTP authorization surface. Standard output is reserved for one JSON response per request; startup diagnostics go to standard error.

## Fixed ownership boundary

The supervisor owns only processes it starts from these fixed evaluation profiles:

- `rag` → `d4-rag`
- `observers` → `d4-rag-observer` and `d4-llm-observer`
- `backend` → `d4-backend`

Backend uses the pinned task-local Python 3.12 venv. RAG uses the pinned task-local RAG venv. Observer processes use the Backend interpreter. The profiles fix absolute executables, argv, working directory, loopback listeners, readiness endpoint, stdout/stderr paths, environment allowlist, interpreter version, and lock identity. Python import paths contain only resolved evaluation-owned source roots; the parent process `PYTHONPATH` is not forwarded. The supervisor rejects caller-supplied commands, paths, environment values, URLs, or ports.

MySQL, CAT, OPA, Safety, Runtime, and Ollama are reported as external dependencies. The supervisor inventories their configured loopback listener ports but does not adopt, start, or stop them. Safety/OPA ownership remains with the operator. Runtime and Ollama remain at the accepted `8160` and `11437` service/provider endpoints; the profile does not use `11434`. The inventory uses the formal port set and does not connect to MySQL port `3306`.

## Request protocol

Each line is a JSON object. The only accepted operations are:

| Operation | Effect |
|---|---|
| `health` | Return supervisor PID, protocol version, and owned process count. |
| `services` | Return owned lifecycle identities and listener-only status for external dependencies. |
| `network_inventory` | Read the Windows TCP table using an absolute `netstat.exe`; does not open service connections. |
| `start` with `service=rag`, `observers`, or `backend` | Start only the selected fixed profile/group. Starting Backend also checks that the configured MySQL host is loopback, the port is not 3306, and database credentials are present. |
| `start_stack` | Start RAG, observers, and Backend in fixed order after the database endpoint check. If startup fails, stop only processes started by this request. |
| `stop` with an owned service/group, or `stop_stack` | Stop only handles created by this supervisor. |
| `cleanup` | Stop owned services in reverse order and exit only after listener closure is verified. |

All other operations, unknown service names, extra request fields, duplicate JSON keys, and oversized requests are rejected. There is no `exec`, `shell`, or `powershell` operation. An attempt to manage an external service returns an ownership error.

## Process and evidence controls

- Every `Popen` receives an absolute executable, argv list, `shell=False`, and a child environment built from a small OS runtime allowlist plus the profile’s explicit variables.
- DB values are copied only into the Backend child environment when supplied by the supervisor’s parent process. They are not written to request/event JSON. Sensitive values are redacted from child stdout/stderr before log files are written.
- Stdout and stderr use separate files. Lifecycle responses record service name, executable, redacted argv, cwd, PID, parent PID, timestamps, return code, listener/readiness, ownership, interpreter version, lock identity, log paths, and shutdown method.
- Shutdown requests CTRL_BREAK on Windows (SIGTERM elsewhere), then fall back to terminate and kill after bounded waits. A service is not reported stopped until its process exits and the listener is closed.
- The JSONL audit file stores only the allowlisted operation, known service name, result, and lifecycle metadata. Unknown request values are never copied into it.

## Start once and operate

Start the process from the D4 evaluation root with the task-local Backend interpreter. `--service-root` must be a new or empty run directory under `D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\supervisor-runs`; `--corpus-manifest` must resolve under the pinned D4 task tools root. The task-tools root and interpreter paths are fixed in the supervisor and cannot be overridden. The Python command is a direct executable launch; it does not invoke a PowerShell service wrapper.

Example requests after startup:

```jsonl
{"op":"health"}
{"op":"start","service":"rag"}
{"op":"start","service":"observers"}
{"op":"services"}
{"op":"cleanup"}
```

The supervisor deliberately has no formal-run operation. It cannot freeze a manifest or submit support requests. Formal execution remains a separate one-shot step after the independent C review is ready. This keeps the process manager’s authority limited to lifecycle operations.

## Verification limits

The unit lifecycle fixture verifies direct spawn, process ownership, redaction, separate streams, readiness, listener closure, and cleanup. The 62-test D4-3B harness suite passed. Production RAG and observer services were not started during this hardening pass. Active MySQL, CAT, OPA, Safety, Runtime, and Ollama listeners were not adopted or stopped. Database and synthetic-account environment variables were absent, so Backend service startup and formal execution remain unavailable in the current state.
