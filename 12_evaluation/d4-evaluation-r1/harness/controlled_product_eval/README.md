# D4-3B evaluation harness

This directory contains the evaluation-only consumer, manifests, schemas, observer, isolated RAG loader, and fixed local-service supervisor for the 12 approved synthetic answerability cases.

The approved Human Gold packet remains byte-for-byte unchanged. Its packet hash is `sha256:cfbe640300c2cbfbfe9616bb20b10b6ed80e7ee1e15169aadf2052ac8de107c6`.

## Fixed Runtime identity

The provider endpoint is `http://127.0.0.1:11437`; the Runtime HTTP service is `http://127.0.0.1:8160`. The accepted identity is Ollama `0.33.3`, model `qwen2.5:7b-instruct-q4_K_M`, digest `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`, context 8192, KV cache `f16`, parallel 1, maximum loaded models 1, output budget 768, and cloud fallback disabled. Port `11434` is never used.

The preflight and current pointer are generated from live supervisor-owned process identities and health checks. The pointer is atomically published only after exact checks pass and invalidated when that attempt's services stop.

## Prepare deterministic inputs

Run the fixed Python executable from the evaluation root. Store generated manifests outside the checkout.

```text
D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs\backend-formal-r2\Scripts\python.exe -m harness.controlled_product_eval.cli prepare-assets --manifest-dir D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\input-manifests
```

The command verifies the packet and writes the immutable 12-case and approved-corpus manifests. The RAG mapping is evaluation-only and does not rewrite Human Gold.

## Cold-start smoke

Run this after each lifecycle code change. It starts the full fixed stack, verifies the synthetic login, Backend dependency and observer gates, prepares the fresh RAG index, then cleans up. It does not create a formal manifest or send a formal support request.

```text
D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs\backend-formal-r2\Scripts\python.exe -m harness.controlled_product_eval.cli smoke-lifecycle --output-root D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\service-lifecycle-smoke-<unique-id>
```

Run the command twice with separate fresh output roots. Each result must report all ten managed profiles ready, loopback-only network integrity, zero connections to `3306` and `11434`, zero formal support requests, and verified cleanup.

## Formal run

The runner owns isolated MySQL, OPA, Safety, Ollama, Runtime, CAT, Backend, RAG, and both observers. The startup order is MySQL → OPA → Safety → Ollama → Runtime → CAT → Backend → synthetic A/B login → fresh RAG index → observers → full premanifest gates. It uses fixed executable paths, arguments, working directories, endpoints, and process-local environment allowlists; there is no shell, PowerShell, or caller-supplied command operation.

After independent C review returns exactly `READY_FOR_D4_3B_AUTONOMOUS_EXECUTION_AFTER_FULL_LIFECYCLE_MIGRATION`, start one fresh formal attempt under the D4 task-tools root:

```text
D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\venvs\backend-formal-r2\Scripts\python.exe -m harness.controlled_product_eval.cli run --output-root D:\Dev\tools\StudentMentalHealthAI\d4-3b-formal-run\formal-run-<unique-id>
```

The runner creates a new MySQL data directory and in-memory application credential, migrates and checks Alembic revision `20260906_0002`, resolves the frozen synthetic account credentials, then builds the fresh RAG index. It freezes the manifest only after the live Runtime attestation, source, login, REAL_HTTP, network, and evidence gates pass. The 12 approved cases run once each, in frozen order, with no retries. Product P0/P1 findings are recorded while the case loop continues; execution-integrity failures stop it.

## Persistent JSONL supervisor

`supervisor.py` exposes only fixed operations: `health`, `services`, `network_inventory`, per-service `start` / `stop`, `start_external_stack`, `stop_external_stack`, `start_stack`, `stop_stack`, and `cleanup`. It has no `exec`, shell, PowerShell, arbitrary URL, path, environment, port, or executable operation. Each owned child is launched directly with `shell=False` inside its own Windows Job Object; cleanup verifies the full child process tree and listener closure.

The supervisor creates the fresh isolated MySQL instance and keeps its application credential in memory. Its database user has privileges only on the evaluation schema and is limited to `127.0.0.1`. The Backend receives its connection URL through the allowlisted process environment; the password is not placed in argv or lifecycle logs. RAG receives the fixed D-drive Hugging Face cache and an attempt-local user profile with hub and Transformers offline flags set. `start_external_stack` starts OPA, Safety, Ollama, Runtime, and CAT in order. Safety uses the unchanged frozen service source and preloads its exact local Qwen3Guard model before binding; its readiness gate still requires OPA and every mandatory component. Runtime attestation records the Supervisor-owned venv launcher and the exact CPython child that owns port 8160. It checks the child's fixed `argv[0]` interpreter path separately from its process-image path and hash; the launcher may report the inherited absolute `TEMP` or `TMP` directory as its CWD after spawning, while the listener must keep the attempt-local Runtime source CWD. `start_stack` then starts Backend, checks the frozen A/B login, starts RAG, and starts observers. The append-only JSONL event record and lifecycle evidence omit environment values and passwords.

## Harness-only validation

`run_mock_validation()` exercises all 12 case/result paths without opening a socket or starting a product service. Its results are marked `NOT_FORMAL_PRODUCT_EVIDENCE`; the harness does not assign human or psychology judgments.
