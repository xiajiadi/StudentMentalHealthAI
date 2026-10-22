# 06 · LLM Runtime

This module provides a provider-neutral LLM control layer. The default Round 1
profile remains CPU-first and uses Ollama as the primary local runtime. An
explicit DeepSeek mode is available for the synthetic Linux school demo; it is
not selected by the local profile. The module does not contain psychological
interpretation, Prompt Engine logic, Safety Engine rules or RAG.

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

## Synthetic school DeepSeek mode

Set `SMHAI_LLM_PROVIDER=deepseek` only for the dedicated synthetic school
service. The mode loads its single hosted model from
`config/models.deepseek.v1.json`; remote entries require the explicit
`allow_remote=True` registry option. There is no local or cloud fallback and
generation retries are disabled to avoid duplicate paid requests. Streaming is
not exposed. The provider sends the Backend-prepared system, user and assistant
messages plus bounded generation settings to the fixed
`https://api.deepseek.com` endpoint; request, assessment, subject, retrieval
and trace identifiers are not forwarded. Structured output uses the API's
JSON mode and is validated locally against the request schema.

The API key and the Backend-to-Runtime bearer token are read from separate
systemd `LoadCredentialEncrypted` files. The API key is resolved from
`CREDENTIALS_DIRECTORY/deepseek-api-key`; the bearer token uses
`SMHAI_LLM_RUNTIME_AUTH_FILE`. Neither secret belongs in environment values,
command arguments, logs or the repository. The provider uses the official
[model list](https://api-docs.deepseek.com/api/list-models/) and
[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)
with thinking disabled, one attempt, a short output cap and no fallback. This
mode is for synthetic education demonstrations only. Safety, RAG and Backend
publication checks remain separate requirements before any public AI flow.

## Contract boundary

The root `generation.v1`, `config.v1`, `logging.v1`, and API contracts remain
unchanged. Runtime-only prompt/config fields are not written back into the
frozen schemas. See:

- [LLM_RUNTIME_TECHNICAL_DECISION_V1.md](LLM_RUNTIME_TECHNICAL_DECISION_V1.md)
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- [TASK.md](TASK.md)
- [Round 1 acceptance](reports/LLM_RUNTIME_ROUND1_ACCEPTANCE.md)

