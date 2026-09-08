"""Formal direct-provider and RuntimeService checks after the budget fix."""

from __future__ import annotations

import hashlib
import json
import subprocess
from contextlib import suppress
from dataclasses import replace
from typing import Any

import httpx
from root_cause_diagnostic import (
    CONTEXT,
    DIGEST,
    EVIDENCE,
    EXACT_CHUNK_IDS,
    MODEL,
    OLLAMA_VERSION,
    SEED,
    TEMPERATURE,
    TOP_P,
    build_service,
    load_actual_schema,
    product_prompt,
    start_ollama,
    wait_ready,
)

POST_FIX_BUDGET = 768


def structured_summary(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {"present": False}
    suggestions = value.get("suggestions") if isinstance(value, dict) else None
    return {
        "present": True,
        "keys": sorted(value),
        "observations_count": len(value.get("observations") or []),
        "suggestions_count": len(suggestions or [])
        if isinstance(suggestions, list)
        else None,
        "suggestion_source_chunk_ids": [
            item.get("source_chunk_ids")
            for item in (suggestions or [])
            if isinstance(item, dict)
        ],
        "disclaimer_present": bool(value.get("disclaimer")),
    }


def transport_summary(record: dict[str, Any]) -> dict[str, Any]:
    request = record["request"]
    response = record["response"]
    response_text = str(response.get("response") or "")
    request_bytes = json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    response_bytes = json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "request_length": len(request_bytes),
        "response_sha256": hashlib.sha256(response_bytes).hexdigest(),
        "response_length": len(response_bytes),
        "response_text_sha256": hashlib.sha256(
            response_text.encode("utf-8")
        ).hexdigest(),
        "response_text_length": len(response_text),
        "response_text_prefix": response_text[:160],
        "done": response.get("done"),
        "done_reason": response.get("done_reason"),
        "eval_count": response.get("eval_count"),
        "prompt_eval_count": response.get("prompt_eval_count"),
    }


def main() -> int:
    schema, schema_identity = load_actual_schema()
    process, owned = start_ollama()
    service = None
    provider = None
    try:
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            wait_ready(client)
            service, provider = build_service()
            service.startup()
            transport: list[dict[str, Any]] = []
            original_request_json = provider.http.request_json

            def capture_request(
                method: str, path: str, payload: Any = None, *, timeout: float
            ) -> dict[str, Any]:
                value = original_request_json(method, path, payload, timeout=timeout)
                if path == "/api/generate":
                    transport.append({"request": payload, "response": value})
                return value

            provider.http.request_json = capture_request
            direct: list[dict[str, Any]] = []
            runtime: list[dict[str, Any]] = []
            from root_cause_diagnostic import runtime_request

            prompt = product_prompt(EXACT_CHUNK_IDS)
            for index in range(1, 4):
                direct_request = runtime_request(prompt, schema, index)
                direct_request = replace(
                    direct_request,
                    config=replace(
                        direct_request.config,
                        max_output_tokens=POST_FIX_BUDGET,
                        max_tokens=POST_FIX_BUDGET,
                    ),
                )
                start = len(transport)
                try:
                    response = provider.generate(direct_request)
                    direct.append(
                        {
                            "run": index,
                            "status": "PASS",
                            "provider": response.provider,
                            "provider_model": response.provider_model,
                            "runtime_version": response.runtime_version,
                            "structured_summary": structured_summary(
                                response.structured
                            ),
                            "structured_valid": response.structured is not None,
                            "usage": response.usage.to_dict(),
                            "finish_reason": response.finish_reason,
                            "transport": transport[start:],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    direct.append(
                        {
                            "run": index,
                            "status": "FAIL",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "transport": transport[start:],
                        }
                    )

                runtime_request_value = replace(
                    direct_request,
                    request_id=f"REQ_STRUCTURED_COMPAT_RUNTIME_{index:02d}",
                    trace_id=f"TRACE_STRUCTURED_COMPAT_RUNTIME_{index:02d}",
                )
                start = len(transport)
                try:
                    result = service.generate(runtime_request_value)
                    runtime.append(
                        {
                            "run": index,
                            "status": result.status,
                            "structured_valid": result.response.structured is not None,
                            "fallback_used": result.fallback_used,
                            "provider": result.response.provider,
                            "provider_model": result.response.provider_model,
                            "runtime_version": result.response.runtime_version,
                            "structured_summary": structured_summary(
                                result.response.structured
                            ),
                            "usage": result.response.usage.to_dict(),
                            "finish_reason": result.response.finish_reason,
                            "trace": result.trace.to_dict(),
                            "transport": transport[start:],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    runtime.append(
                        {
                            "run": index,
                            "status": "FAIL",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "transport": transport[start:],
                        }
                    )
            provider.http.request_json = original_request_json
            result = {
                "round": "STRUCTURED_OUTPUT_PRODUCT_COMPATIBILITY_CLOSURE_R1_POST_FIX_COMPATIBILITY",
                "synthetic_only": True,
                "provider_parameters": {
                    "ollama": OLLAMA_VERSION,
                    "model": MODEL,
                    "digest": DIGEST,
                    "context": CONTEXT,
                    "kv": "f16",
                    "parallel": 1,
                    "num_predict": POST_FIX_BUDGET,
                    "temperature": TEMPERATURE,
                    "top_p": TOP_P,
                    "seed": SEED,
                },
                "schema_sha256": schema_identity["schema_sha256"],
                "exact_prompt_sha256": __import__("hashlib")
                .sha256(prompt.encode("utf-8"))
                .hexdigest(),
                "direct_provider": {
                    "passed": sum(
                        item.get("status") == "PASS" and item.get("structured_valid")
                        for item in direct
                    ),
                    "total": 3,
                    "runs": direct,
                },
                "runtime_service": {
                    "passed": sum(
                        item.get("status") == "success"
                        and item.get("structured_valid")
                        and not item.get("fallback_used")
                        for item in runtime
                    ),
                    "total": 3,
                    "runs": runtime,
                },
                "transport_generation_calls": len(transport),
                "process": {
                    "ollama_process_owned_by_diagnostic": owned,
                    "terminated_by_diagnostic": bool(process),
                },
            }
            for item in (
                result["direct_provider"]["runs"] + result["runtime_service"]["runs"]
            ):
                item["transport"] = [
                    transport_summary(record) for record in item.get("transport", [])
                ]
            (EVIDENCE / "post_fix_compatibility.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "provider": result["direct_provider"]["passed"],
                        "runtime": result["runtime_service"]["passed"],
                        "budget": POST_FIX_BUDGET,
                    },
                    ensure_ascii=False,
                )
            )
    finally:
        if provider is not None:
            with suppress(Exception):
                provider.close()
        if service is not None:
            with suppress(Exception):
                service.shutdown()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
