# D4-3B evaluation harness

This directory contains the evaluation-only consumer, manifests, schemas, result evaluator, observer, isolated RAG loader, and one-shot runner for the 12 approved answerability cases.

The approved packet remains byte-for-byte unchanged. Its packet hash is `sha256:cfbe640300c2cbfbfe9616bb20b10b6ed80e7ee1e15169aadf2052ac8de107c6`. The consumer rejects duplicate JSON keys, checks the approval record and canonical hash, and records both the raw file hash and bound source hashes.

## Formal Runtime identity

D4-3B formal preflight requires the exact Runtime identity in `manifest.py`, including `http://127.0.0.1:11437`, Ollama `0.33.3`, and the approved Qwen model digest. Every identity field is checked by strict equality; alternate ports, including `11434`, are rejected. There is no environment override or endpoint allow-list.

The preflight `endpoint` is the Ollama provider endpoint and remains `http://127.0.0.1:11437`. The Runtime HTTP service is a separate loopback service at `http://127.0.0.1:8160`; the LLM observer must target that Runtime service for readiness and observation. Do not route the observer to the provider endpoint.

The separate Runtime Reconstruction R1 evidence records a historical Ollama `0.21.1` integration at `http://127.0.0.1:11434`. That evidence remains historical and is not the D4-3B formal Runtime target.

## Prepare deterministic inputs

Run from the project root. Keep generated manifests and run outputs outside the checkout.

```powershell
$repoRoot = (Get-Location).Path
$evalPath = Join-Path $repoRoot '12_evaluation\d4-evaluation-r1'
$env:PYTHONPATH = "$evalPath;$repoRoot\09_backend\src"
& 'D:\Projects\StudentMentalHealthAI\09_backend\.venv\Scripts\python.exe' `
  -m harness.controlled_product_eval.cli prepare-assets `
  --manifest-dir 'D:\Dev\cache\d4-3b-input-manifests'
```

The command verifies the packet and writes an immutable 12-case manifest and a temporary corpus manifest. Case IDs come from the packet. Citation cards that reuse a source chunk ID receive deterministic evaluation-only RAG IDs; each record retains the original ID, content hash, citation case ID, and source annotations. The mapping does not rewrite or normalize Human Gold.

## Managed formal run

The managed runner starts a fresh isolated MySQL instance, provisions a run-local database credential, migrates and checks the accepted schema, starts Backend, then verifies the frozen synthetic A/B identities before building the fresh RAG index. It verifies CAT, Safety, OPA, Runtime, Ollama, observers, network integrity, and credential-artifact integrity before freezing the formal manifest. After C returns `READY_FOR_FORMAL_D4_3B_RUN_AFTER_CREDENTIAL_BOOTSTRAP`, the authorized run continues without another Controller wait. Formal requests go through `POST /api/v1/support/requests` exactly once in the frozen order; the runner stops only processes it owns.

The credential provider resolves Student A/B only from the exact accepted Backend fixture blob and never reads environment variables or Credential Manager entries. The managed launch uses the pinned Backend and RAG task-local Python environments:

```powershell
$repoRoot = (Get-Location).Path
$evalPath = Join-Path $repoRoot '12_evaluation\d4-evaluation-r1'
$env:PYTHONPATH = "$evalPath;$repoRoot\09_backend\src"
$backendPython = 'D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs\backend-formal-r2\Scripts\python.exe'
$ragPython = 'D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs\rag-env-lock-r1\Scripts\python.exe'
& $backendPython -m harness.controlled_product_eval.cli run `
  --repo-root $repoRoot `
  --runtime-preflight 'D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\runtime-preflight-current.json' `
  --output-root 'D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\formal-run-r6-<new-id>' `
  --backend-python $backendPython `
  --rag-python $ragPython
```

Each managed attempt creates a fresh MySQL 8.4.8 data directory on `127.0.0.1:3307`, generates a run-local application password in memory, creates only the D4 evaluation schema/account, migrates and checks Alembic revision `20260906_0002`, then starts Backend with process-local `DB_*` settings. The credential provider does not read ambient database variables, `.env`, or Credential Manager. Student A/B credentials are resolved only after exact Git blob verification of the frozen Backend fixture source; only the two approved accounts are returned.

The fixed startup order is source gate → Safety/OPA → exact Ollama → Runtime → CAT → fresh MySQL server → ephemeral database credential → schema/user, migration, drift and readiness → Backend and synthetic fixture bootstrap → Student A/B login and exact subject checks → fresh RAG index → observers → full REAL_HTTP/network/evidence gates → immutable formal manifest → the frozen 12 cases exactly once. A failed login stops before RAG or manifest creation and never resets an account. Product P0/P1 findings are recorded and do not stop the frozen cases. The summary reports product P0/P1 counts separately from `execution_integrity_status` and `execution_abort_reason`.

The isolated RAG index uses the accepted BGE-M3 embedding model in offline mode. If the pinned model is absent from the configured local cache, startup stops without downloading it. The run manifest records all four Backend dependency identities, and formal manifest validation rejects any dependency that is not `REAL_HTTP`.

`--use-existing-services` is rejected for a formal attempt because it cannot prove a fresh isolated database and fixture bootstrap.

## Persistent local supervisor

`supervisor.py` provides a long-lived JSONL process interface over stdin/stdout. It starts children with absolute executable paths and argument arrays, `shell=False`, and per-profile environment allowlists. The request protocol accepts only `health`, `services`, `network_inventory`, `start`, `stop`, `start_stack`, `stop_stack`, and `cleanup`; it has no shell or arbitrary-command operation.

The supervisor parent creates and owns its fresh isolated MySQL server and credential. JSONL can only manage Backend, RAG, and observers; it cannot provide credential values. Backend start runs the in-memory A/B login gate; RAG start is rejected until that gate passes; observers follow RAG. The exact Backend and RAG task-local Python executables remain pinned, and existing listeners are never adopted. CAT, OPA, Safety, Runtime, and Ollama remain external dependencies.

Start the supervisor once with the task-local Python 3.12 executable, from the evaluation root. Supply a new service directory under `D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\supervisor-runs` and the approved corpus manifest under the D4 task tools root. Keep the process session open and send one JSON object per line, for example `{"op":"health"}`, `{"op":"start","service":"backend"}`, `{"op":"start","service":"rag"}`, `{"op":"start","service":"observers"}`, `{"op":"services"}`, and `{"op":"cleanup"}`. Responses and lifecycle evidence omit environment values; the append-only event file is written under the selected service directory. The supervisor does not run formal cases.

## Harness-only validation

`run_mock_validation()` exercises all 12 case/result paths without opening a socket or starting a product service. Every returned case and summary is marked `NOT_FORMAL_PRODUCT_EVIDENCE`. Textual support and population, role, and purpose applicability remain `PENDING_HUMAN_REVIEW`; the harness does not produce an overall utility score.
