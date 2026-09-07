# Open-Source Runtime Reference Audit

Research date: 2026-09-07
Purpose: resolve implementation uncertainty, not copy source or expand product
scope. No third-party source was copied into this repository.

| Project/upstream | Version or revision observed | License | Concept borrowed | Not adopted |
|---|---|---|---|---|
| Ollama REST API | current official docs observed 2026-09-07; local validated service remains `0.21.1` | Ollama project license; API documentation used as interface reference | `/api/version`, `/api/tags`, `/api/ps`, native `format` JSON Schema, `keep_alive`, NDJSON stream shape and generation metrics | no cloud model, no public bind, no new Ollama server, no provider rewrite |
| `ollama-python` | upstream `main` observed 2026-09-07 | MIT (upstream repository) | existence of `Client`/`AsyncClient`, pooled HTTP client lifecycle, typed native API mapping and response/error boundary | not a dependency; existing accepted native adapter remains the compatibility boundary |
| FastAPI lifespan | current official docs observed 2026-09-07 | MIT | one lifespan context for startup resources and shutdown cleanup | legacy event-handler mix, multiple lifecycle owners |
| HTTPX | current official docs/API observed 2026-09-07; project already pins `httpx==0.28.1` | BSD-3-Clause | explicit connect/read/write/pool timeout model, reusable client, `trust_env=False`, stream context closure | no per-request client creation, no unlimited timeout |
| Python `subprocess` | Python 3.14 docs observed 2026-09-07; project runtime uses Python 3.12 | PSF-2.0 | argument sequence, `shell=False`, explicit cwd/env, Windows creation flags and bounded wait | PowerShell wrapper, shell command strings, broad image-name termination |
| psutil | stable docs observed 2026-09-07; dependency added only for owned-tree management | BSD-3-Clause | `Process.create_time`, recursive children, `wait_procs`, bounded terminate/kill and PID reuse guard | process discovery by name, killing arbitrary Ollama processes, watchdog framework |
| LiteLLM | official docs observed 2026-09-07; reference only | MIT (upstream project) | conceptual distinction between routing/fallback/error normalization and explicit deployment policy | no dependency, proxy, cloud routing, load balancing, or gateway |

## Decision

Adopt only the small, directly relevant patterns above. Extend the existing
Provider/Domain implementation rather than replacing it with an orchestration
framework. The only new runtime dependency is `psutil`, justified by the
required process-tree ownership proof.

## Source links

- [Ollama API version](https://docs.ollama.com/api-reference/get-version)
- [Ollama model list](https://docs.ollama.com/api/tags)
- [Ollama running models](https://docs.ollama.com/api/ps)
- [Ollama chat API](https://docs.ollama.com/api/chat)
- [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs)
- [Ollama keep-alive guidance](https://docs.ollama.com/faq)
- [ollama-python](https://github.com/ollama/ollama-python)
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
- [HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/)
- [HTTPX client lifecycle](https://www.python-httpx.org/async/)
- [Python subprocess](https://docs.python.org/3/library/subprocess.html)
- [psutil process management](https://psutil.readthedocs.io/stable/index.html)
- [LiteLLM routing reference](https://docs.litellm.ai/)
