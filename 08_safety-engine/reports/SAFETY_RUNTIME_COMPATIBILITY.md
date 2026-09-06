# SAFETY RUNTIME COMPATIBILITY

| Field | Round 1 result |
|---|---|
| Checked | 2026-09-05 |
| OS | Windows 11 (local host) |
| Python | 3.12.13 at D:\Dev\pythons\cpython-3.12.13-windows-x86_64-none |
| Virtual environment | 08_safety-engine\.venv |
| Cache policy | Hugging Face/Torch/UV caches on D: |
| Physical RAM | 33.75 GB (31.43 GiB reported) |
| GPU | Not accepted as available; CPU path used |
| Safety Local Contract Compatibility | v0.1.0 FROZEN; read-only 7/7 compatibility check |
| Repository-wide official Root Gate | 13 passed, 0 failed; OpenAPI OK; exit code 0; see ROOT_CONTRACT_RECHECK.md |
| Real data | Not used |

## Components

| Component | Version / revision | Integration surface | Status |
|---|---|---|---|
| NeMo Guardrails | 0.24.0 | IORails.check_async() with RailType.INPUT/OUTPUT | PASS after real safe/block/safe checks |
| Qwen3Guard-Gen | 0.6B, revision fada3b2f655b89601929198343c94cd2f64d93cc | Transformers local CPU generation; actual output captured | PASS; see safety_round1_evaluation.json |
| Presidio | analyzer/anonymizer 2.2.364 | real detect/redact; custom synthetic Chinese ID and student-ID recognizers | PASS; smoke false-positive=0, false-negative=0; language recall not established |
| OPA | v1.20.2 Windows amd64 | real loopback process, REST query, CLI fmt/check/test | PASS; binary SHA-256 verified before use |
| Transformers | 5.16.1 | Qwen local text-generation pipeline | PASS in CPU gate |
| PyTorch | 2.14.0 | CPU tensor inference | PASS in CPU gate |
| FastAPI | 0.141.1 | internal loopback service routes | PASS in HTTP boundary test |

## Commands and evidence

- uv sync --extra runtime --extra test
- opa fmt -w policies
- opa check policies
- opa test policies -v -> 6/6
- uv run pytest -m "not qwen" -q -> 20 passed, 0 failed, 1 deselected, 3 warnings (Qwen gate recorded separately)
- SMHAI_RUN_QWEN_TESTS=1 uv run pytest -m qwen -q -> 1 passed, 0 failed, 20 deselected, 2 warnings
- uvx pyright -> 0 errors, 0 warnings, 0 informations
- uv run safety-evaluate -> actual Qwen CPU outputs and end-to-end synthetic cases
- powershell -NoProfile -ExecutionPolicy Bypass -File .\00_architecture\tests\run_contract_checks.ps1
  -> repository-wide 13-test and OpenAPI gate; exact output in ROOT_CONTRACT_RECHECK.md
- OPA SHA-256 matched the official release checksum:
  e2f2e2b735ab98f316171ca47a6b352288cdeb5a616e31aa16335b8934748453

## Honest limitations

The Qwen CPU gate proves that the pinned model can load and classify the
three synthetic probes on this host. It is not a throughput or production SLO.
The NeMo integration is deterministic regex I/O validation, not a complete
semantic safety solution. Presidio's custom Chinese patterns are not evidence
of population-level recall. Retrieval safety remains PARTIAL because the
selected NeMo IORails API does not expose a retrieval surface. Crisis
templates remain pending psychology review.
