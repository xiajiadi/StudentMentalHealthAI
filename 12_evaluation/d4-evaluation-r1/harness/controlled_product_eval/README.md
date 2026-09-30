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

## Run only after C and Controller authorize the formal run

The managed runner validates the supplied Runtime preflight before it starts local services. It starts a fresh isolated RAG service, RAG and LLM observers, and a Backend on loopback. The Backend is forced to MySQL persistence and `REAL_HTTP` CAT, RAG, LLM Runtime, and Safety clients. CAT, Safety, Runtime, Ollama, and MySQL remain externally managed; each must already be healthy and loopback-only. MySQL must use the isolated evaluation instance on a loopback port other than 3306. The runner routes the 12 requests through `POST /api/v1/support/requests`, then stops only processes it started and verifies their readiness endpoints are down. Runtime remains externally owned and is never started or stopped here.

Set `SMHAI_D4_STUDENT_A_PASSWORD` and `SMHAI_D4_STUDENT_B_PASSWORD` in the current shell to the credentials for the two synthetic accounts. Do not put them in files or command arguments. Supply Python environments that contain the accepted Backend and RAG dependencies:

```powershell
$repoRoot = (Get-Location).Path
$evalPath = Join-Path $repoRoot '12_evaluation\d4-evaluation-r1'
$env:PYTHONPATH = "$evalPath;$repoRoot\09_backend\src"
$backendPython = 'D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs\backend-formal-r2\Scripts\python.exe'
$ragPython = 'D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs\rag-env-lock-r1\Scripts\python.exe'
& $backendPython -m harness.controlled_product_eval.cli run `
  --repo-root $repoRoot `
  --runtime-preflight 'D:\Dev\cache\d4-runtime-preflight.json' `
  --output-root 'D:\Dev\cache\d4-3b-formal-output' `
  --backend-python $backendPython `
  --rag-python $ragPython
```

The Backend process inherits the current shell's `DATABASE_URL`, or `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, and `DB_NAME` variables. Supply credentials from the local evaluation secret source. The runner rejects a non-loopback MySQL host and port 3306 before starting the Backend. Its Backend Python environment must include the locked Database module dependencies, and the repository's `11_database` package is added to `PYTHONPATH`.

The run writes its canonical run manifest before the first support request, one result per case, a summary, observer events, and a service-lifecycle record. Product P0/P1 findings are recorded and do not stop the frozen 12-case evaluation. The run stops only when execution or evidence integrity is no longer trustworthy, including an uncertain support-request outcome, changed frozen inputs or protected source, Runtime identity drift, fallback, external established data-plane activity, missing observer evidence, or unhealthy required dependencies. Every Backend dependency must report `REAL_HTTP`; any other mode blocks formal manifest validation before a support request. The summary reports product P0/P1 counts separately from `execution_integrity_status` and `execution_abort_reason`.

The isolated RAG index uses the accepted BGE-M3 embedding model in offline mode. If the pinned model is absent from the configured local cache, startup stops without downloading it. The run manifest records all four Backend dependency identities, and formal manifest validation rejects any dependency that is not `REAL_HTTP`.

`--use-existing-services` is available for diagnostics when services were started elsewhere. That mode leaves process cleanup to its caller and must not be reported as cleanup-verified by this harness.

## Persistent local supervisor

`supervisor.py` provides a long-lived JSONL process interface over stdin/stdout. It starts children with absolute executable paths and argument arrays, `shell=False`, and per-profile environment allowlists. The request protocol accepts only `health`, `services`, `network_inventory`, `start`, `stop`, `start_stack`, `stop_stack`, and `cleanup`; it has no shell or arbitrary-command operation.

The supervisor can own only the D4 RAG service, the two evaluation observers, and the Backend process it starts. The managed CLI and supervisor both require the exact Backend and RAG task-local Python executables in `D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs`; caller-selected Python paths are rejected. It never adopts a listener that already exists. MySQL, CAT, OPA, Safety, Runtime, and Ollama remain external dependencies in this version; their listener presence is inventoried, and start/stop requests are rejected. This preserves the existing Runtime/Ollama identity and the operator ownership boundary for Safety/OPA.

Start the supervisor once with the task-local Python 3.12 executable, from the evaluation root. Supply a new service directory under `D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\supervisor-runs` and the approved corpus manifest under the D4 task tools root. Keep the process session open and send one JSON object per line, for example `{"op":"health"}`, `{"op":"start","service":"rag"}`, `{"op":"start","service":"observers"}`, `{"op":"start","service":"backend"}`, `{"op":"services"}`, and `{"op":"cleanup"}`. Responses and lifecycle evidence omit environment values; the append-only event file is written under the selected service directory. The supervisor does not run formal cases.

## Harness-only validation

`run_mock_validation()` exercises all 12 case/result paths without opening a socket or starting a product service. Every returned case and summary is marked `NOT_FORMAL_PRODUCT_EVIDENCE`. Textual support and population, role, and purpose applicability remain `PENDING_HUMAN_REVIEW`; the harness does not produce an overall utility score.
