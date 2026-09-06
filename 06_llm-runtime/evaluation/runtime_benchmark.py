"""Measure real local runtime timings without inventing token counts or SLAs."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from llm_runtime.domain.models import GenerationConfig, GenerationRequest, StreamEventType
from llm_runtime.hardware.detector import HardwareDetector
from llm_runtime.providers.ollama import OllamaProvider


MODULE_ROOT = Path(__file__).resolve().parents[1]


def _request(model: str, request_id: str) -> GenerationRequest:
    return GenerationRequest(
        request_id=request_id,
        trace_id=f"TRACE_{request_id.removeprefix('REQ_')}",
        generation_id="GEN_runtime_benchmark",
        assessment_id="ASSESS_runtime_benchmark",
        subject_id="SUBJ_runtime_synthetic",
        target_role="teacher",
        purpose="education_support",
        language="en",
        safety_mode="standard",
        retrieval_id="RETR_runtime_benchmark",
        chunk_ids=("CHUNK_runtime_synthetic",),
        prompt_id="PROMPT_runtime_benchmark_v1",
        prompt_version="0.1.0",
        contract_model_id="MODEL_local_cpu_test",
        logical_model_id="qwen2.5-0.5b-engineering",
        provider_model_id=model,
        prompt="Reply with one short synthetic engineering sentence.",
        config=GenerationConfig(max_output_tokens=48, timeout_seconds=180, temperature=0),
    )


def run(model: str, repeats: int) -> dict[str, Any]:
    provider = OllamaProvider(timeout_seconds=180)
    result: dict[str, Any] = {
        "status": "started",
        "model": model,
        "provider": "ollama",
        "hardware": HardwareDetector().detect().to_dict(),
        "cloud_fallback": False,
        "measurements": [],
    }
    health = provider.health_check()
    result["ollama_version"] = health.version
    if health.readiness != "pass":
        result.update({"status": "blocked", "error": health.to_dict()})
        return result
    load_start = time.perf_counter()
    provider.load_model(model)
    result["load_time_ms"] = (time.perf_counter() - load_start) * 1000
    for index in range(repeats):
        request = _request(model, f"REQ_benchmark_{index + 1}")
        started = time.perf_counter()
        response = provider.generate(request)
        finished = time.perf_counter()
        completion_tokens = response.usage.completion_tokens
        generation_seconds = finished - started
        result["measurements"].append(
            {
                "kind": "warm_non_stream",
                "index": index + 1,
                "total_latency_ms": generation_seconds * 1000,
                "generation_duration_ms": generation_seconds * 1000,
                "ttft_ms": None,
                "completion_tokens": completion_tokens,
                "tokens_per_second": (
                    completion_tokens / generation_seconds if completion_tokens is not None and generation_seconds else None
                ),
                "response_non_empty": bool(response.text.strip()),
            }
        )

    request = _request(model, "REQ_benchmark_stream")
    stream_start = time.perf_counter()
    first_delta: float | None = None
    usage = None
    events = []
    for event in provider.stream_generate(request):
        events.append(event.event_type.value)
        if event.event_type is StreamEventType.DELTA and first_delta is None:
            first_delta = time.perf_counter()
        if event.event_type is StreamEventType.USAGE:
            usage = event.usage
    stream_finished = time.perf_counter()
    stream_seconds = stream_finished - stream_start
    completion_tokens = usage.completion_tokens if usage else None
    result["stream_measurement"] = {
        "events": events,
        "total_latency_ms": stream_seconds * 1000,
        "generation_duration_ms": stream_seconds * 1000,
        "ttft_ms": (first_delta - stream_start) * 1000 if first_delta else None,
        "completion_tokens": completion_tokens,
        "tokens_per_second": (
            completion_tokens / stream_seconds if completion_tokens is not None and stream_seconds else None
        ),
    }
    provider.unload_model(model)
    result["status"] = "success"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("SMHAI_OLLAMA_TEST_MODEL", "qwen2.5:0.5b"))
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--output", type=Path, default=MODULE_ROOT / "artifacts" / "runtime_benchmark.json")
    args = parser.parse_args()
    value = run(args.model, max(1, args.repeats))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(value, ensure_ascii=False, indent=2))
    return 0 if value["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

