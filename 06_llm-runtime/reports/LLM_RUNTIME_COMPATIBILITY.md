# LLM Runtime Compatibility Report

Evidence date: 2026-09-05  
Scope: CPU Engineering Round 1  
GPU Acceptance: `DEFERRED`

## Host

| Field | Observed value |
| --- | --- |
| OS | Windows 11 Professional, build 10.0.26200, 64-bit |
| Python | 3.14.6 (`C:\Python314\python.exe`) |
| CPU | Intel(R) Core(TM) Ultra 9 185H |
| CPU cores / threads | 16 / 22 |
| RAM | 33,752,997,888 bytes (31.4349 GiB; 32,961,912 KB) |
| GPU | No usable NVIDIA GPU detected in this run |
| CUDA | Not available / not accepted |
| NVIDIA driver | Not available; `nvidia-smi` failed with a permissions error and returned no usable GPU row |

`HardwareDetector` reports `gpu_present=false` and `profile=CPU_ONLY`. It does
not infer a GPU name, VRAM, driver or CUDA version from a failed probe.

## Runtime availability

| Runtime | Research version | Local status | Notes |
| --- | --- | --- | --- |
| Ollama | `v0.33.3` latest public release observed | Installed client/service `v0.21.1`; `/api/version` passed; endpoint `http://127.0.0.1:11434` | Native provider integration and real model chain passed |
| llama.cpp | `v0.3.0` latest public release observed | `llama-server.exe` not installed/verified | Provider PoC and managed-process seam present; execution remains pending |
| vLLM | `v0.28.0` latest public release observed | Not installed | Future/reference only |
| SGLang | `v0.5.18` latest public release observed | Not installed | Future/reference only |
| LocalAI | `v4.9.0` latest public release observed | Not installed | Architecture reference only |
| Olla | `v0.0.29` latest public release observed | Not deployed | Health/routing/recovery reference only |
| GPUStack | `v2.2.3` latest public release observed | Not installed | Future deployment reference only |
| LiteLLM | `v1.99.1` latest public release observed | Not installed | Future gateway reference only; no cloud route |

## Model paths

- Ollama model bytes: `D:\Dev\caches\ollama-models`
- For the installed older Windows Ollama service, `C:\Users\15848\.ollama\models`
  is a directory junction to that D-drive cache; no model bytes remain in the
  C-drive target.
- GGUF/llama.cpp model directory: not populated in Round 1.
- Repository model files: none.
- Cloud fallback: disabled.

## Models

| Model | Provider ID | Local evidence |
| --- | --- | --- |
| Qwen2.5 0.5B engineering test | `qwen2.5:0.5b` | `READY`; digest `a8b0c51577010a279d933d14c2a8ab4b268079d44c5c8830c0a93900f1827c67`; 397,821,319 bytes; GGUF; Q4_K_M; Apache-2.0 |
| Qwen2.5 1.5B local fallback | `qwen2.5:1.5b` | `READY`; digest `65ec06548149b04c096a120e4a6da9d4017ea809c91734ea5631e89f96ddc57b`; 986,061,892 bytes; GGUF; Q4_K_M; Apache-2.0 |
| Qwen2.5-7B-Instruct proposal baseline | `qwen2.5:7b` / official Qwen GGUF source | Registered; Q4_K_M is the first GPU candidate; validation deferred because the RTX 3060 12GB eGPU is not connected |

## Real evidence

- [`ollama_integration.json`](../artifacts/ollama_integration.json) records
  health, discovery, model info, load/unload, generate, stream, structured
  output and RuntimeService evidence.
- [`runtime_benchmark.json`](../artifacts/runtime_benchmark.json) records the
  CPU load, warm non-streaming and streaming measurements.

No real student data was used.

## Round 1 closure update

The second real Ollama model was pulled and discovered through the installed
`0.21.1` API on 2026-09-05. RuntimeService model switching and a controlled
model-level failure to the real `qwen2.5:1.5b` fallback passed. See the closure
evidence reports for exact trace IDs and latency measurements.
