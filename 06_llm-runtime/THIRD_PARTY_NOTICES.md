# Third-Party Notices and Research Record

Research/evidence date: 2026-09-05.  
Technical decision date: 2026-09-04.  
No third-party repository source code was copied into this module.

The versions below are the latest public release tags observed from each
project's official GitHub repository during this run. A release tag is research
context, not an instruction to install the project as a dependency.

| Project | Repository / official documentation | Version or revision observed | License | Role | Integration type | Code copied? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Ollama | [ollama/ollama](https://github.com/ollama/ollama), [API docs](https://docs.ollama.com/api) | `v0.33.3` | MIT | Primary local runtime | Integrated through native HTTP API; installed host version recorded separately | No | Studied `/api/version`, `/api/tags`, `/api/show`, `/api/ps`, `/api/generate`, `/api/pull`, `stream`, `format`, `keep_alive`, and `think`. |
| llama.cpp | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp), [llama-server docs](https://github.com/ggml-org/llama.cpp/tree/master/tools/server) | `v0.3.0`, release commit `c1d0e7a004015f23bc0233470b747b596f29b264` | MIT | Low-level secondary runtime | Provider PoC for `llama-server`; no server binary installed for Round 1 | No | Studied Windows binaries, CPU backend, GGUF, `/health`, `/v1/models`, completion/streaming and response-format behavior. |
| vLLM | [vllm-project/vllm](https://github.com/vllm-project/vllm), [structured outputs](https://docs.vllm.ai/en/latest/features/structured_outputs.html) | `v0.28.0` | Apache-2.0 | Future server runtime | Reference only | No | Studied OpenAI-compatible serving, continuous batching, quantization and structured output. Not installed; Windows/CPU is not a Round 1 target. |
| SGLang | [sgl-project/sglang](https://github.com/sgl-project/sglang), [structured outputs](https://github.com/sgl-project/sglang/blob/main/docs_new/docs/advanced_features/structured_outputs.mdx) | `v0.5.18`, release commit `71de97b` | Apache-2.0 | High-performance reference | Reference only | No | Studied server architecture, streaming and grammar backends. Not installed; GPU server work is future scope. |
| LocalAI | [mudler/LocalAI](https://github.com/mudler/LocalAI), [backend configuration](https://github.com/mudler/LocalAI/blob/master/docs/content/advanced/advanced-usage.md) | `v4.9.0` | MIT | Runtime architecture reference | Reference only | No | Studied pluggable backend/model abstraction and hardware-neutral API. Not installed. |
| Olla | [thushan/olla](https://github.com/thushan/olla) | `v0.0.29` | Apache-2.0 | Health/routing/recovery reference | Reference only | No | Studied endpoint health, circuit breakers, discovery refresh, retry boundaries and streaming-first routing. Not deployed as an extra proxy. |
| GPUStack | [gpustack/gpustack](https://github.com/gpustack/gpustack) | `v2.2.3` | Apache-2.0 | Future deployment reference | Reference only | No | Studied GPU discovery, model health, scheduling and pluggable inference engines. Not installed. |
| LiteLLM | [BerriAI/litellm](https://github.com/BerriAI/litellm) | `v1.99.1` | MIT | Future gateway reference | Reference only | No | Official repository license file states MIT for content outside `enterprise/`; studied provider normalization, routing and fallback/error ideas. Not installed; cloud fallback is disabled. |
| Qwen2.5 0.5B | [Ollama model page](https://ollama.com/library/qwen2.5), [Qwen2.5](https://github.com/QwenLM/Qwen2.5) | Ollama tag `qwen2.5:0.5b`; local digest `a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67` | Apache-2.0 | CPU engineering test model | Downloaded and verified locally; weights are outside Git | No | Official model page lists the `0.5b` tag and approximate 398 MB size. Local discovery recorded 397,821,319 bytes, GGUF and Q4_K_M. |
| Qwen2.5 7B GGUF | [Qwen official GGUF repository](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF) | Proposal baseline; Q4_K_M first candidate | Apache-2.0 | Future GPU baseline | Registered only; GPU validation deferred | No | No acceptance claim is made until the RTX 3060 is connected and measured locally. |

## License handling

Only provider HTTP integration code owned by this module is committed. No
third-party source files are vendored. Model licenses apply to the downloaded
model artifacts and must be rechecked against the exact model revision before a
future distribution.
