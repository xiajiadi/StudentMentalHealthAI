"""Real Ollama integration checks.

Run explicitly with ``SMHAI_RUN_OLLAMA_INTEGRATION=1`` after the configured
engineering model has been pulled. These tests never use student data.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from llm_runtime.domain.models import (
    Capabilities,
    Compatibility,
    GenerationConfig,
    GenerationRequest,
    HardwareProfile,
    ModelEntry,
    ModelStatus,
    StreamEventType,
)
from llm_runtime.domain.registry import ModelRegistry
from llm_runtime.hardware.detector import HardwareDetector
from llm_runtime.providers.ollama import OllamaProvider
from llm_runtime.runtime.service import RuntimeService


if os.environ.get("SMHAI_RUN_OLLAMA_INTEGRATION") != "1":
    pytest.skip("set SMHAI_RUN_OLLAMA_INTEGRATION=1 to run real Ollama checks", allow_module_level=True)


MODULE_ROOT = Path(__file__).resolve().parents[2]
MODEL = os.environ.get("SMHAI_OLLAMA_TEST_MODEL", "qwen2.5:0.5b")
SECOND_MODEL = "qwen2.5:1.5b"
SECOND_LOGICAL_MODEL = "qwen2.5-1.5b-engineering-fallback"
CONTROLLED_MISSING_LOGICAL_MODEL = "qwen2.5-controlled-missing-primary"
CONTROLLED_MISSING_PROVIDER_MODEL = "smhai-acceptance-missing-model:round1"


def _request(
    *,
    request_id: str,
    prompt: str,
    schema=None,
    max_tokens: int = 64,
    logical_model_id: str = "qwen2.5-0.5b-engineering",
    contract_model_id: str = "MODEL_local_cpu_test",
    provider_model_id: str | None = MODEL,
) -> GenerationRequest:
    return GenerationRequest(
        request_id=request_id,
        trace_id=f"TRACE_{request_id.removeprefix('REQ_')}",
        generation_id="GEN_ollama_integration",
        assessment_id="ASSESS_ollama_integration",
        subject_id="SUBJ_ollama_synthetic",
        target_role="teacher",
        purpose="education_support",
        language="en",
        safety_mode="standard",
        retrieval_id="RETR_ollama_integration",
        chunk_ids=("CHUNK_ollama_synthetic",),
        prompt_id="PROMPT_ollama_engineering_v1",
        prompt_version="0.1.0",
        contract_model_id=contract_model_id,
        logical_model_id=logical_model_id,
        provider_model_id=provider_model_id,
        prompt=prompt,
        structured_schema=schema,
        config=GenerationConfig(max_output_tokens=max_tokens, timeout_seconds=180, temperature=0),
    )


def _run_real_cancellation(provider: OllamaProvider) -> dict[str, object]:
    request = _request(
        request_id="REQ_ollama_cancel",
        prompt="Repeat the word engineering 256 times, separated by spaces.",
        max_tokens=256,
    )
    events = []
    errors: list[str] = []

    def consume() -> None:
        try:
            events.extend(provider.stream_generate(request))
        except Exception as exc:  # pragma: no cover - diagnostic guard for the live service
            errors.append(f"{type(exc).__name__}: {exc}")

    thread = threading.Thread(target=consume, name="ollama-cancellation-check", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15.0
    cancelled = False
    while thread.is_alive() and time.monotonic() < deadline:
        if request.request_id in provider.http._active:
            cancelled = provider.cancel(request.request_id)
            break
        time.sleep(0.05)
    thread.join(timeout=30.0)
    assert cancelled, "the real stream did not expose an active request for cancellation"
    assert not thread.is_alive(), "the real stream did not terminate after cancellation"
    assert not errors, errors
    types = [event.event_type.value for event in events]
    assert types[0] == StreamEventType.START.value
    assert types[-1] == StreamEventType.CANCELLED.value
    assert StreamEventType.DONE.value not in types
    return {"types": types, "terminated": True}


def test_ollama_round1_real_local_chain():
    provider = OllamaProvider(timeout_seconds=180)
    evidence = {
        "model": MODEL,
        "provider": "ollama",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    health = provider.health_check()
    assert health.readiness == "pass", health.to_dict()
    evidence["version"] = health.version
    evidence["health"] = health.to_dict()

    discovered = provider.discover_models()
    model = next((item for item in discovered if item.get("provider_model_id") == MODEL), None)
    assert model is not None, {"discovered": discovered}
    evidence["discovery"] = model
    info = provider.get_model_info(MODEL)
    evidence["model_info"] = {
        "digest": info.get("digest"),
        "format": info.get("format"),
        "quantization": info.get("quantization"),
        "license": "Apache-2.0" if "Apache License" in str(info.get("license")) else None,
    }

    model_health = provider.model_health_check(MODEL)
    evidence["model_health_before_load"] = model_health.to_dict()
    assert model_health.availability == "available"

    load_started = time.perf_counter()
    provider.load_model(MODEL)
    evidence["load_time_ms"] = (time.perf_counter() - load_started) * 1000
    assert provider.model_health_check(MODEL).loaded is True

    plain = provider.generate(
        _request(request_id="REQ_ollama_plain", prompt="Reply exactly with a short synthetic engineering response.")
    )
    assert plain.text.strip()
    evidence["generate"] = {
        "status": "success",
        "response_non_empty": bool(plain.text.strip()),
        "usage": plain.usage.to_dict(),
        "finish_reason": plain.finish_reason,
    }

    stream_events = list(
        provider.stream_generate(
            _request(request_id="REQ_ollama_stream", prompt="Reply with three short words.", max_tokens=32)
        )
    )
    stream_types = [event.event_type.value for event in stream_events]
    assert stream_types[0] == StreamEventType.START.value
    assert stream_types[-1] == StreamEventType.DONE.value
    assert StreamEventType.DELTA.value in stream_types
    evidence["stream"] = {"types": stream_types, "text": "".join(event.delta for event in stream_events)}

    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "string", "minLength": 1}},
    }
    structured = provider.generate(
        _request(
            request_id="REQ_ollama_structured",
            prompt='Return JSON only with this shape: {"answer":"OK"}. Do not add markdown.',
            schema=schema,
        )
    )
    assert structured.structured["answer"]
    evidence["structured_output"] = {"status": "success", "value": structured.structured}
    evidence["cancellation"] = _run_real_cancellation(provider)

    registry = ModelRegistry.from_file(MODULE_ROOT / "config" / "models.v1.json")
    service = RuntimeService(
        registry,
        {"ollama": provider},
        hardware=HardwareDetector().detect(),
        backoff_seconds=(0,),
    )
    service_discovery = service.discover()
    service_health = service.health()
    service_load = service.load_model("qwen2.5-0.5b-engineering")
    assert registry.resolve("qwen2.5-0.5b-engineering").status.value == "LOADED"
    service_result = service.generate(
        _request(
            request_id="REQ_ollama_runtime_service",
            prompt="Reply with one short synthetic service response.",
        )
    )
    assert service_result.trace.actual_model == "qwen2.5-0.5b-engineering"
    evidence["runtime_service"] = {
        "discovery_count": len(service_discovery["ollama"]),
        "health_provider": service_health["providers"]["ollama"],
        "load_done_reason": service_load["result"].get("done_reason"),
        "response_non_empty": bool(service_result.text.strip()),
        "trace": service_result.trace.to_dict(),
    }

    service_unload = service.unload_model("qwen2.5-0.5b-engineering")
    evidence["runtime_service"]["unload_done_reason"] = service_unload["result"].get("done_reason")
    unloaded = provider.model_health_check(MODEL)
    evidence["unload"] = unloaded.to_dict()
    assert unloaded.loaded is False

    evidence["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (MODULE_ROOT / "artifacts" / "ollama_integration.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def test_ollama_real_model_switching():
    """Resolve two logical IDs to two real Ollama models without code branches."""

    provider = OllamaProvider(timeout_seconds=180)
    health = provider.health_check()
    assert health.readiness == "pass", health.to_dict()
    discovered = {
        item["provider_model_id"]: item
        for item in provider.discover_models()
        if item.get("provider_model_id")
    }
    assert MODEL in discovered, discovered
    assert SECOND_MODEL in discovered, discovered
    assert provider.model_health_check(MODEL).availability == "available"
    assert provider.model_health_check(SECOND_MODEL).availability == "available"

    registry = ModelRegistry.from_file(MODULE_ROOT / "config" / "models.v1.json")
    service = RuntimeService(
        registry,
        {"ollama": provider},
        hardware=HardwareDetector().detect(),
        max_attempts=1,
        backoff_seconds=(0,),
    )
    service.discover()
    prompt = "Reply with one short synthetic engineering status sentence."
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    checks: list[dict[str, object]] = []
    for index, (logical_model_id, contract_model_id, provider_model_id) in enumerate(
        (
            ("qwen2.5-0.5b-engineering", "MODEL_local_cpu_test", MODEL),
            (SECOND_LOGICAL_MODEL, "MODEL_local_cpu_fallback", SECOND_MODEL),
        ),
        start=1,
    ):
        request = _request(
            request_id=f"REQ_ollama_switch_{index}",
            prompt=prompt,
            logical_model_id=logical_model_id,
            contract_model_id=contract_model_id,
            provider_model_id=None,
        )
        started = time.perf_counter()
        result = service.generate(request)
        latency_ms = (time.perf_counter() - started) * 1000
        assert result.text.strip()
        assert result.actual_model_id == logical_model_id
        assert result.response.provider_model == provider_model_id
        checks.append(
            {
                "logical_model_id": logical_model_id,
                "provider_model_id": provider_model_id,
                "result_status": "success",
                "latency_ms": latency_ms,
                "trace_id": result.trace.trace_id,
                "trace": result.trace.to_dict(),
            }
        )
        unloaded = service.unload_model(logical_model_id)
        assert unloaded["result"].get("done_reason") is not None

    (MODULE_ROOT / "artifacts" / "real_model_switching.json").write_text(
        json.dumps(
            {
                "status": "success",
                "started_at": started_at,
                "runtime_version": health.version,
                "provider": "ollama",
                "provider_endpoint": provider.base_url,
                "prompt_policy": "synthetic engineering prompt only; no student data",
                "discovery": {
                    model_id: discovered[model_id]
                    for model_id in (MODEL, SECOND_MODEL)
                },
                "models": checks,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def test_ollama_real_model_failover_and_trace():
    """Use a real missing-model HTTP failure, then infer with the real fallback."""

    provider = OllamaProvider(timeout_seconds=180)
    health = provider.health_check()
    assert health.readiness == "pass", health.to_dict()
    discovered = {
        item["provider_model_id"]: item
        for item in provider.discover_models()
        if item.get("provider_model_id")
    }
    fallback_discovery = discovered.get(SECOND_MODEL)
    assert fallback_discovery is not None, discovered

    fallback = ModelEntry(
        logical_model_id=SECOND_LOGICAL_MODEL,
        contract_model_id="MODEL_local_cpu_fallback",
        display_name="Qwen2.5 1.5B real fallback",
        family="Qwen2.5",
        parameters=fallback_discovery.get("parameters") or "1.5B",
        provider="ollama",
        provider_model_id=SECOND_MODEL,
        source="Ollama Library",
        source_repository="https://ollama.com/library/qwen2.5",
        revision=SECOND_MODEL,
        digest=fallback_discovery.get("digest"),
        format=fallback_discovery.get("format"),
        quantization=fallback_discovery.get("quantization"),
        license="Apache-2.0",
        size_bytes=fallback_discovery.get("size_bytes"),
        capabilities=Capabilities(chat=True, stream=True, structured_output=True, json_schema=True),
        hardware_profile=HardwareProfile.CPU_ONLY,
        compatibility=Compatibility.SUPPORTED,
        status=ModelStatus.READY,
        validation_status="REAL_FALLBACK_TEST",
        provider_version=health.version,
    )
    primary = ModelEntry(
        logical_model_id=CONTROLLED_MISSING_LOGICAL_MODEL,
        contract_model_id="MODEL_local_controlled_primary",
        display_name="Controlled missing Ollama primary",
        family="Qwen2.5",
        parameters="1.5B candidate",
        provider="ollama",
        provider_model_id=CONTROLLED_MISSING_PROVIDER_MODEL,
        source="Acceptance test registry",
        source_repository="https://ollama.com/library/qwen2.5",
        revision=CONTROLLED_MISSING_PROVIDER_MODEL,
        format="gguf",
        quantization="Q4_K_M",
        license="Apache-2.0",
        capabilities=Capabilities(chat=True, stream=True, structured_output=True, json_schema=True),
        hardware_profile=HardwareProfile.CPU_ONLY,
        compatibility=Compatibility.SUPPORTED,
        status=ModelStatus.READY,
        validation_status="CONTROLLED_MODEL_LEVEL_FAILURE",
        fallback_model_id=SECOND_LOGICAL_MODEL,
        provider_version=health.version,
    )
    registry = ModelRegistry([primary, fallback])
    service = RuntimeService(
        registry,
        {"ollama": provider},
        hardware=HardwareDetector().detect(),
        max_attempts=1,
        backoff_seconds=(0,),
    )
    request = _request(
        request_id="REQ_ollama_real_fallback",
        prompt="Reply with one short synthetic engineering fallback status sentence.",
        logical_model_id=CONTROLLED_MISSING_LOGICAL_MODEL,
        contract_model_id="MODEL_local_controlled_primary",
        provider_model_id=None,
        max_tokens=48,
    )

    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = time.perf_counter()
    result = service.generate(request)
    latency_ms = (time.perf_counter() - started) * 1000
    trace = result.trace
    assert result.text.strip()
    assert result.actual_model_id == SECOND_LOGICAL_MODEL
    assert result.response.provider_model == SECOND_MODEL
    assert trace.requested_model == CONTROLLED_MISSING_LOGICAL_MODEL
    assert trace.requested_provider_model == CONTROLLED_MISSING_PROVIDER_MODEL
    assert trace.primary_error_normalized_code == "MODEL_NOT_FOUND"
    assert trace.primary_error["code"] == "MODEL_NOT_FOUND"
    assert trace.primary_error["status_code"] == 404
    assert trace.fallback_attempted is True
    assert trace.fallback_model == SECOND_LOGICAL_MODEL
    assert trace.fallback_provider_model == SECOND_MODEL
    assert trace.fallback_reason == "MODEL_NOT_FOUND"
    assert trace.actual_model == SECOND_LOGICAL_MODEL
    assert trace.fallback_generation_success is True
    assert trace.retry_count == 0
    assert trace.fallback_count == 1

    (MODULE_ROOT / "artifacts" / "real_fallback.json").write_text(
        json.dumps(
            {
                "status": "success",
                "started_at": started_at,
                "runtime_version": health.version,
                "provider": "ollama",
                "provider_endpoint": provider.base_url,
                "test_registry": {
                    "cloud_fallback": False,
                    "primary_logical_model": CONTROLLED_MISSING_LOGICAL_MODEL,
                    "primary_provider_model": CONTROLLED_MISSING_PROVIDER_MODEL,
                    "fallback_logical_model": SECOND_LOGICAL_MODEL,
                    "fallback_provider_model": SECOND_MODEL,
                },
                "result_status": "fallback_generation_success",
                "latency_ms": latency_ms,
                "trace": trace.to_dict(),
                "prompt_policy": "synthetic engineering prompt only; no student data",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    unloaded = service.unload_model(SECOND_LOGICAL_MODEL)
    assert unloaded["result"].get("done_reason") is not None
