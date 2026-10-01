# D4 persistent supervisor architecture

## Transport choice

The supervisor is one long-lived Python process using newline-delimited JSON on stdin/stdout. This fits the current Codex process-session interface: launch once, then send individual requests through the existing process handle. It opens no socket, needs no API token, and avoids a localhost HTTP authorization surface. Standard output is reserved for one JSON response per request; startup diagnostics go to standard error.

## Fixed ownership boundary

The evaluation bootstrap owns its fresh isolated MySQL server. The JSONL
supervisor can manage only processes it starts from these fixed profiles:

- `mysql` → `d4-mysql` (created and provisioned by the parent bootstrap; not a JSONL operation)
- `backend` → `d4-backend`
- `rag` → `d4-rag`
- `observers` → `d4-rag-observer` and `d4-llm-observer`

Backend uses the pinned task-local Python 3.12 venv. RAG uses the pinned task-local RAG venv. Observer processes use the Backend interpreter. The profiles fix absolute executables, argv, working directory, loopback listeners, readiness endpoint, stdout/stderr paths, environment allowlist, interpreter version, and lock identity. Python import paths contain only resolved evaluation-owned source roots; the parent process `PYTHONPATH` is not forwarded. The supervisor rejects caller-supplied commands, paths, environment values, URLs, or ports.

The parent bootstrap starts a new MySQL 8.4.8 instance on `127.0.0.1:3307` with a fresh data directory and no option-file inheritance. It creates the evaluation database and restricted application account, migrates to `20260906_0002`, checks drift, and verifies readiness before Backend starts. It never connects to system MySQL port `3306`. CAT, OPA, Safety, Runtime, and Ollama stay external; they are read-only checked at their pinned loopback endpoints and are never adopted, started, or stopped. Runtime and Ollama remain at `8160` and `11437`; the profile does not use `11434`.

## Request protocol

Each line is a JSON object. The only accepted operations are:

| Operation | Effect |
|---|---|
| `health` | Return supervisor PID, protocol version, and owned process count. |
| `services` | Return owned lifecycle identities and listener-only status for external dependencies. |
| `network_inventory` | Read the Windows TCP table using an absolute `netstat.exe`; does not open service connections. |
| `start` with `service=backend` | Start Backend with process-local DB settings, then log in as only `student_a` and `student_b` and verify `SUBJ_demo_a` / `SUBJ_demo_b`. |
| `start` with `service=rag` | Start the fresh RAG index only after the synthetic login gate passes. |
| `start` with `service=observers` | Start both observers only after RAG is ready. |
| `start_stack` | Start Backend → A/B login gate → fresh RAG index → observers. If startup fails, stop only processes started by this request. |
| `stop` with an owned service/group, or `stop_stack` | Stop only handles created by this supervisor. |
| `cleanup` | Stop owned services in reverse order and exit only after listener closure is verified. |

All other operations, unknown service names, extra request fields, duplicate JSON keys, and oversized requests are rejected. There is no `exec`, `shell`, or `powershell` operation. An attempt to manage an external service returns an ownership error.

## Process and evidence controls

- Every `Popen` receives an absolute executable, argv list, `shell=False`, and a child environment built from a small OS runtime allowlist plus the profile’s explicit variables.
- A run-local DB password is generated in parent memory. It enters only the MySQL bootstrap child and Backend child environments; the migration child receives it in its local `DATABASE_URL` environment. Frozen A/B fixture passwords stay in parent memory for the login client and in the Backend log redactor’s private in-memory values; they are not added to Backend environment.
- Credential values never enter argv, process identity, JSONL request/response/audit, evidence, or logs. Child stdout/stderr are redacted before log files are written. Lifecycle identities omit all environment values and log-redaction values.
- Stdout and stderr use separate files. Lifecycle responses record service name, executable, redacted argv, cwd, PID, parent PID, timestamps, return code, listener/readiness, ownership, interpreter version, lock identity, log paths, and shutdown method.
- Shutdown requests CTRL_BREAK on Windows (SIGTERM elsewhere), then fall back to terminate and kill after bounded waits. A service is not reported stopped until its process exits and the listener is closed.
- The JSONL audit file stores only the allowlisted operation, known service name, result, and lifecycle metadata. Unknown request values are never copied into it.

## Start once and operate

Start the process from the D4 evaluation root with the task-local Backend interpreter. `--service-root` must be a new run directory under `D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\supervisor-runs`; `--corpus-manifest` must resolve under the pinned D4 task tools root. The task-tools root and interpreter paths are fixed in the supervisor and cannot be overridden. The Python command is a direct executable launch; it does not invoke a PowerShell service wrapper. Startup creates the DB credential internally before the JSONL protocol begins.

Example requests after startup:

```jsonl
{"op":"health"}
{"op":"start","service":"backend"}
{"op":"start","service":"rag"}
{"op":"start","service":"observers"}
{"op":"services"}
{"op":"cleanup"}
```

The supervisor deliberately has no formal-run operation. It cannot freeze a manifest or submit support requests. Formal execution remains a separate one-shot step after the independent C review is ready. This keeps the process manager’s authority limited to lifecycle operations.

## Previous hardening verification record

The previous executor-hardening review verified direct spawn, process ownership, redaction, separate streams, readiness, listener closure, and cleanup. It did not start production RAG or observer services and did not bootstrap a fresh MySQL instance. Its credential-source stop predates the current Controller standing decision authorizing this fixed self-contained bootstrap. That historical result remains evidence for its original commit and is not the verification result for the credential-bootstrap changes.
