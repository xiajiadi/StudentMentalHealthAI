# 06 · LLM Runtime

This module provides a provider-neutral local LLM control layer. Round 1 is
CPU-first and uses Ollama as the primary local runtime. It does not contain
psychological interpretation, Prompt Engine logic, Safety Engine rules or RAG.

## Local setup

```powershell
uv sync --extra test
```

The module uses standard-library HTTP and a small JSON Schema dependency. Model
weights are not committed. Keep Ollama model data under the configured D-drive
cache, for example `D:\Dev\caches\ollama-models`.

## Useful checks

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m compileall -q src tests evaluation
.venv\Scripts\python.exe -m llm_runtime.cli hardware
.venv\Scripts\python.exe -m llm_runtime.cli models
.venv\Scripts\python.exe -m llm_runtime.cli discover
.venv\Scripts\python.exe -m llm_runtime.cli health
```

Real Ollama checks are opt-in because they require a running local service and
downloaded model:

```powershell
$env:SMHAI_RUN_OLLAMA_INTEGRATION = "1"
.venv\Scripts\python.exe -m pytest -q tests/integration
.venv\Scripts\python.exe evaluation/runtime_benchmark.py --repeats 2
```

The model used for engineering checks is `qwen2.5:0.5b`; it is not the final
psychological model. The proposal baseline `qwen2.5-7b-instruct` remains
registered with GPU validation deferred.

## Contract boundary

The root `generation.v1`, `config.v1`, `logging.v1`, and API contracts remain
unchanged. Runtime-only prompt/config fields are not written back into the
frozen schemas. See:

- [LLM_RUNTIME_TECHNICAL_DECISION_V1.md](LLM_RUNTIME_TECHNICAL_DECISION_V1.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TASK.md](TASK.md)
- [Round 1 acceptance](reports/LLM_RUNTIME_ROUND1_ACCEPTANCE.md)

