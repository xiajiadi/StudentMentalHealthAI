# LLM Runtime GPU Acceptance Template

Status: `DEFERRED`  
Hardware target: External RTX 3060 12GB  
Current connection at Round 1: `NOT AVAILABLE`

This template is intentionally not an acceptance result. Fill it only after the
GPU is physically connected and the commands below produce local evidence.

## 1. Hardware proof

```text
nvidia-smi --query-gpu=name,memory.total,driver_version,cuda_version --format=csv
```

- GPU recognized:
- GPU name:
- VRAM:
- Driver:
- CUDA:
- Timestamp:

## 2. Baseline

- Model: Qwen2.5-7B-Instruct
- Source: `Qwen/Qwen2.5-7B-Instruct-GGUF`
- Candidate quantization: `Q4_K_M`
- Actual Ollama tag/digest:
- Actual llama.cpp GGUF filename/checksum:
- Context:
- Prompt: synthetic and identical across providers

## 3. Ollama measurements

| Metric | Value | Evidence |
| --- | --- | --- |
| model load time | PENDING | |
| VRAM | PENDING | |
| RAM | PENDING | |
| TTFT | PENDING | |
| prompt processing speed | PENDING | |
| decode speed | PENDING | |
| total latency | PENDING | |
| stream success | PENDING | |
| structured output validation | PENDING | |
| stability/repeated runs | PENDING | |

## 4. llama.cpp measurements

Repeat the same table and record the `llama-server` release, command line,
GGUF checksum and backend flags. Do not compare different quantizations,
contexts or prompts without labeling the comparison.

## 5. Decision

Do not mark PASS from theoretical VRAM fit or internet benchmarks. Mark each
provider `PASS`, `PARTIAL PASS` or `FAIL` only from this machine's evidence.

