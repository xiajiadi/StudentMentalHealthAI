# LLM Runtime Round 1 Closure Evidence

Evidence date: 2026-09-05  
Decision scope: CPU Engineering Round 1 only

This is the supporting evidence index for the acceptance closure. The
historical result in `LLM_RUNTIME_ROUND1_ACCEPTANCE.md` section 1 remains
unchanged; the current closure result is recorded in its appended section 33.

## 1. Root Contract Gate

Formal command:

```powershell
.\00_architecture\tests\run_contract_checks.ps1
```

Run at `2026-09-05T01:48:25+08:00`:

```text
Ran 13 tests in 0.116s
OK
openapi.v1.json: OK
A-phase contract, Schema, and OpenAPI checks passed.
```

Result: `13 passed, 0 failed`, including the `05-rag-engine` governance
subtest. The previous failure is no longer present in the current checkout;
the current RAG TASK already contains the seven required headings. No RAG
file was changed by this closure.

See [`ROOT_CONTRACT_RECHECK.md`](ROOT_CONTRACT_RECHECK.md).

## 2. External OpenAPI Validation

The formal root script executed the external validator against
`00_architecture/openapi.v1.json` and returned `OK` with exit code 0.
Independent version output:

```text
openapi-spec-validator 0.9.0
```

See [`OPENAPI_EXTERNAL_VALIDATION.md`](OPENAPI_EXTERNAL_VALIDATION.md).

## 3. Second Real Model and Switching

The real model download command was:

```powershell
$env:OLLAMA_MODELS = 'D:\Dev\caches\ollama-models'
$env:OLLAMA_HOST = '127.0.0.1:11434'
& 'C:\Users\15848\AppData\Local\Programs\Ollama\ollama.exe' pull 'qwen2.5:1.5b'
```

The CLI output completed with SHA-256 verification, manifest write and
`success`.

Real command:

```powershell
$env:SMHAI_RUN_OLLAMA_INTEGRATION = '1'
.venv\Scripts\python.exe -X utf8 -m pytest -q
```

The real `ollama pull qwen2.5:1.5b` completed with manifest write, SHA-256
verification and `success`. `GET /api/tags` then discovered both real models.
The second model is:

| Field | Value |
| --- | --- |
| Provider model ID | `qwen2.5:1.5b` |
| Digest | `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b` |
| Size | 986061892 bytes |
| Format / quantization | GGUF / Q4_K_M |
| License | Apache-2.0 |
| Provider version | 0.21.1 |
| Cache | `D:\Dev\caches\ollama-models` |

The switching artifact records two successful real generations:
`TRACE_ollama_switch_1` for `qwen2.5:0.5b` and
`TRACE_ollama_switch_2` for `qwen2.5:1.5b`.

See [`REAL_MODEL_SWITCHING_EVIDENCE.md`](REAL_MODEL_SWITCHING_EVIDENCE.md).

## 4. Real Local Fallback

The controlled primary model ID was not installed, so the live Ollama
Provider returned HTTP 404 normalized as `MODEL_NOT_FOUND`. RuntimeService
then generated a non-empty response through the real `qwen2.5:1.5b` fallback.
The resulting `TRACE_ollama_real_fallback` contains the requested/provider
model IDs, primary error, normalized code, fallback fields, success flag,
retry count and fallback count.

See [`REAL_FALLBACK_EVIDENCE.md`](REAL_FALLBACK_EVIDENCE.md).

## 5. Regression Tests

| Command | Result |
| --- | --- |
| `.venv\Scripts\python.exe -X utf8 -m pytest -q` | 23 passed, 1 existing opt-in integration skip |
| `$env:SMHAI_RUN_OLLAMA_INTEGRATION='1'; .venv\Scripts\python.exe -X utf8 -m pytest -q` | 26 passed, 0 failed, 0 skipped |
| `.venv\Scripts\python.exe -X utf8 -m compileall -q src tests evaluation` | exit 0 |

The full real run covered the existing discovery, provider health, model
health, lifecycle, generation, streaming, structured output and cancellation
checks, plus model switching and real fallback. No new skip, xfail, test
filter or test deletion was introduced.

## 6. Dependency and static checks

| Check | Result |
| --- | --- |
| `uv sync --extra test` | exit 0; resolved 13, checked 12 packages |
| `uv lock --check` | exit 0 |
| `uv pip check` | exit 0; all installed packages compatible |
| `uv tree --depth 2` | jsonschema 4.26.0; pytest 9.1.1; no optional cloud/runtime frameworks |
| `uvx ruff check src tests evaluation` | blocked; PyPI wheel metadata request timed out after 3 retries |

Ruff is not reported as passed. mypy and pyright remain unconfigured, as in
the historical report.

## 7. Safety, privacy and boundary checks

- `cloud_fallback=false` remains explicit in both production runtime/model
  configuration and the controlled fallback registry.
- Only local `ollama` was registered in the real switch/fallback tests. No
  cloud request was executed.
- Prompts were synthetic engineering text only; no real student data,
  assessment result, counseling record or psychological report was used.
- Frozen root schemas, OpenAPI, Contract documents and versioned Contract
  fields were not modified.
- Ollama remains pinned for this validation at installed version `0.21.1`;
  no upgrade was performed.
- The project root has no `.git` directory; the read-only Git check reported
  that it is not a repository, and no Git mutation was attempted.

## 8. Remaining deferred items

- `llama.cpp`: provider PoC, execution remains `PENDING`.
- GPU acceptance: `DEFERRED_BY_HARDWARE_AVAILABILITY`; the RTX 3060 eGPU was
  not connected and no GPU claim is made.
- Ruff remains externally blocked; this is recorded and is not a core Round 1
  acceptance condition under the supplied closure gate.

## Closure gate

The supplied Full PASS conditions are satisfied by current evidence: unit and
real integration tests pass, real switching and fallback pass, the full root
gate passes, the external OpenAPI validator exits 0, no root test was skipped
or altered, frozen Contracts are unchanged, cloud fallback is disabled, and
the privacy boundary passes. Therefore the CPU Engineering Round 1 closure
status is `PASS`. llama.cpp and GPU remain separately deferred as explicitly
allowed.
