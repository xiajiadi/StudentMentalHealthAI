"""Synthetic root-cause diagnosis for the frozen GPU product prompt.

This file is acceptance/evaluation support only. It does not change product
modules, accepted corpus files, or the frozen contracts. It compares the native
Ollama payload, the accepted OllamaProvider assembly, and RuntimeService's
strict parser input while keeping all raw provider material in the ignored
closure-local evidence directory.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SRC = ROOT / "06_llm-runtime" / "src"
OLLAMA = Path(
    r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\ollama-0.33.3\ollama.exe"
)
MODELS = Path(r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\models")
URL = "http://127.0.0.1:11435"
MODEL = "qwen2.5:7b-instruct-q4_K_M"
DIGEST = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
OLLAMA_VERSION = "0.33.3"
CONTEXT = 8192
MAX_OUTPUT = 384
TEMPERATURE = 0.1
TOP_P = 0.9
SEED = 20260906
MESSAGE = "请给出简短建议。"
TARGET_ROLE = "student"
EXACT_CHUNK_IDS = (
    "CHUNK_67b56abe21fe9860a26d",
    "CHUNK_8f85f2c0472e21acd2fa",
    "CHUNK_c3718c65fcf4151af391",
    "CHUNK_3d2d02ba1c8fbc506665",
    "CHUNK_bcbe71382652340b2249",
)
CONTROL_CHUNK_IDS = ("CHUNK_A", "CHUNK_B", "CHUNK_C", "CHUNK_D", "CHUNK_E")
SCHEMA_SOURCE = (
    ROOT / "09_backend" / "src" / "smhai_backend" / "integrations" / "llm.py"
)
PYDANTIC_SOURCE = (
    ROOT / "09_backend" / "src" / "smhai_backend" / "domains" / "support" / "schemas.py"
)
LOCAL_EVIDENCE = ROOT / "_local-evidence" / "structured-output-compat"
EVIDENCE = ROOT / "12_evaluation" / "structured-output-compat-r1"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def load_actual_schema() -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute only the repository's schema factory, never a hand copy."""

    source_text = SCHEMA_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(SCHEMA_SOURCE))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_generation_content_schema"
    )
    module = ast.Module(body=[ast.fix_missing_locations(function)], type_ignores=[])
    namespace: dict[str, Any] = {"Any": Any}
    exec(compile(module, str(SCHEMA_SOURCE), "exec"), namespace)  # noqa: S102
    schema = namespace["_generation_content_schema"]()
    if not isinstance(schema, dict):
        raise TypeError("repository generation schema factory did not return an object")
    return schema, {
        "schema_source": str(SCHEMA_SOURCE),
        "schema_source_sha256": sha256_bytes(SCHEMA_SOURCE.read_bytes()),
        "schema_factory": "_generation_content_schema",
        "schema_sha256": sha256_json(schema),
        "pydantic_validation_target": "GenerationContent",
        "pydantic_source": str(PYDANTIC_SOURCE),
        "pydantic_source_sha256": sha256_bytes(PYDANTIC_SOURCE.read_bytes()),
    }


def product_prompt(chunk_ids: tuple[str, ...]) -> str:
    """Mirror the exact current SupportService._build_prompt serialization."""

    joined = ",".join(chunk_ids)
    return (
        "Return JSON only, matching the requested generation schema. "
        "Do not diagnose, assign clinical risk, or invent citations. "
        "education_support; target_role="
        f"{TARGET_ROLE}; message={MESSAGE}; source_chunk_ids={joined}"
    )


def request_payload(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": schema,
        "options": {
            "num_predict": MAX_OUTPUT,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
            "seed": SEED,
            "num_ctx": CONTEXT,
        },
        "keep_alive": "5m",
    }


def runtime_request(prompt: str, schema: dict[str, Any], index: int) -> Any:
    from llm_runtime.domain.models import GenerationConfig, GenerationRequest

    return GenerationRequest(
        request_id=f"REQ_STRUCTURED_COMPAT_{index:02d}",
        trace_id=f"TRACE_STRUCTURED_COMPAT_{index:02d}",
        generation_id=f"GEN_STRUCTURED_COMPAT_{index:02d}",
        assessment_id=f"ASSESS_STRUCTURED_COMPAT_{index:02d}",
        subject_id=f"SUBJ_STRUCTURED_COMPAT_{index:02d}",
        target_role=TARGET_ROLE,
        purpose="education_support",
        language="zh-CN",
        safety_mode="standard",
        retrieval_id=f"RETR_STRUCTURED_COMPAT_{index:02d}",
        chunk_ids=EXACT_CHUNK_IDS,
        prompt_id="PROMPT_backend_support_v1",
        prompt_version="1.0",
        contract_model_id="MODEL_local_gpu_acceptance",
        logical_model_id="qwen2.5-7b-instruct-compat",
        prompt=prompt,
        structured_schema=schema,
        config=GenerationConfig(
            max_output_tokens=MAX_OUTPUT,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            context_length=CONTEXT,
            timeout_seconds=180.0,
            keep_alive="5m",
            seed=SEED,
        ),
        provider_model_id=MODEL,
        metadata={"synthetic_fixture": True, "diagnostic_only": True},
    )


def model_snapshot(client: httpx.Client) -> dict[str, Any]:
    result: dict[str, Any] = {
        "endpoint": URL,
        "expected_model": MODEL,
        "expected_digest": DIGEST,
    }
    for name, method, path, body in (
        ("version", "GET", "/api/version", None),
        ("tags", "GET", "/api/tags", None),
        ("show", "POST", "/api/show", {"model": MODEL}),
        ("ps", "GET", "/api/ps", None),
    ):
        response = client.request(method, URL + path, json=body)
        value = response.json()
        if name == "version":
            result["version"] = value
        elif name == "tags":
            result["tags"] = [
                {
                    "name": item.get("name") or item.get("model"),
                    "digest": item.get("digest"),
                    "size": item.get("size"),
                    "quantization": (item.get("details") or {}).get(
                        "quantization_level"
                    ),
                }
                for item in value.get("models", [])
                if isinstance(item, dict)
            ]
        elif name == "show":
            result["show"] = {
                "digest": value.get("digest"),
                "details": value.get("details"),
                "model_info_keys": sorted((value.get("model_info") or {}).keys()),
            }
        else:
            result["ps"] = value
    return result


def wait_ready(client: httpx.Client) -> None:
    deadline = time.monotonic() + 90
    while True:
        try:
            response = client.get(URL + "/api/version")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("formal diagnostic Ollama did not become ready")
        time.sleep(1)


def start_ollama() -> tuple[subprocess.Popen[Any] | None, bool]:
    env = os.environ.copy()
    env.update(
        {
            "OLLAMA_HOST": "127.0.0.1:11435",
            "OLLAMA_MODELS": str(MODELS),
            "OLLAMA_CONTEXT_LENGTH": str(CONTEXT),
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_KEEP_ALIVE": "5m",
        }
    )
    with httpx.Client(timeout=5.0, trust_env=False) as client:
        try:
            if client.get(URL + "/api/version").status_code == 200:
                return None, False
        except httpx.HTTPError:
            pass
    process = subprocess.Popen(
        [str(OLLAMA), "serve"],
        cwd=str(OLLAMA.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return process, True


def write_local(name: str, value: str | bytes) -> dict[str, Any]:
    path = LOCAL_EVIDENCE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = value.encode("utf-8") if isinstance(value, str) else value
    path.write_bytes(raw)
    return {"path": str(path), "length": len(raw), "sha256": sha256_bytes(raw)}


def parse_summary(text: str, schema: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "response_length": len(text),
        "response_sha256": sha256_text(text),
        "response_prefix": text[:160],
    }
    try:
        value = json.loads(text)
        result.update(
            {
                "json_parse": "PASS",
                "json_type": type(value).__name__,
                "json_keys": sorted(value) if isinstance(value, dict) else None,
            }
        )
        from jsonschema import Draft202012Validator

        errors = sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda item: list(item.path),
        )
        result["schema_validation"] = "PASS" if not errors else "FAIL"
        if errors:
            result["schema_error"] = errors[0].message[:300]
    except json.JSONDecodeError as exc:
        result.update(
            {
                "json_parse": "FAIL",
                "json_line": exc.lineno,
                "json_column": exc.colno,
                "json_error": exc.msg,
                "schema_validation": "NOT_RUN",
            }
        )
    return result


def raw_termination(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "done": payload.get("done"),
        "done_reason": payload.get("done_reason"),
        "error": payload.get("error"),
        "prompt_eval_count": payload.get("prompt_eval_count"),
        "eval_count": payload.get("eval_count"),
        "total_duration": payload.get("total_duration"),
        "load_duration": payload.get("load_duration"),
        "response_present": isinstance(payload.get("response"), str),
        "response_terminated": payload.get("done") is True and not payload.get("error"),
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
        "method": record["method"],
        "path": record["path"],
        "request_sha256": sha256_bytes(request_bytes),
        "request_length": len(request_bytes),
        "response_sha256": sha256_bytes(response_bytes),
        "response_length": len(response_bytes),
        "response_text_sha256": sha256_text(response_text),
        "response_text_length": len(response_text),
        "response_text_prefix": response_text[:160],
        "termination": raw_termination(response),
    }


def direct_case(
    client: httpx.Client,
    label: str,
    prompt: str,
    schema: dict[str, Any],
    *,
    run_index: int | None = None,
) -> dict[str, Any]:
    payload = request_payload(prompt, schema)
    response = client.post(URL + "/api/generate", json=payload)
    response.raise_for_status()
    native = response.json()
    text = str(native.get("response") or "")
    request_bytes = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    native_bytes = response.content
    local_prefix = (
        f"{label}_direct" if run_index is None else f"{label}_run_{run_index:02d}"
    )
    request_artifact = write_local(local_prefix + "_request.json", request_bytes)
    response_artifact = write_local(local_prefix + "_response.json", native_bytes)
    prompt_artifact = write_local(local_prefix + "_prompt.txt", prompt)
    result: dict[str, Any] = {
        "case": label,
        "run_index": run_index,
        "request_identity": {
            "model": MODEL,
            "seed": SEED,
            "num_ctx": CONTEXT,
            "num_predict": MAX_OUTPUT,
            "temperature": TEMPERATURE,
            "top_p": TOP_P,
        },
        "prompt_sha256": sha256_text(prompt),
        "prompt_length": len(prompt),
        "schema_sha256": sha256_json(schema),
        "provider_request_sha256": sha256_bytes(request_bytes),
        "native_http_status": response.status_code,
        "native_response_body_sha256": sha256_bytes(native_bytes),
        "native_response_text_sha256": sha256_text(text),
        "native_response_text_length": len(text),
        "native": parse_summary(text, schema),
        "termination": raw_termination(native),
        "local_artifacts": [request_artifact, response_artifact, prompt_artifact],
    }
    return result


def runtime_case(
    service: Any,
    provider: Any,
    schema: dict[str, Any],
    prompt: str,
    index: int,
) -> dict[str, Any]:
    from llm_runtime.errors import LLMRuntimeError
    from llm_runtime.providers import ollama as ollama_module
    from llm_runtime.runtime import service as service_module

    transport: list[dict[str, Any]] = []
    provider_parser_inputs: list[str] = []
    runtime_parser_inputs: list[str] = []
    original_request_json = provider.http.request_json
    original_provider_parse = ollama_module.parse_and_validate
    original_runtime_parse = service_module.parse_and_validate

    def capture_request(
        method: str, path: str, payload: Any = None, *, timeout: float
    ) -> dict[str, Any]:
        value = original_request_json(method, path, payload, timeout=timeout)
        if path == "/api/generate" and isinstance(value, dict):
            transport.append(
                {
                    "method": method,
                    "path": path,
                    "request": payload,
                    "response": value,
                    "request_sha256": sha256_json(payload),
                    "response_sha256": sha256_json(value),
                }
            )
        return value

    def capture_provider_parse(text: str, value: Any) -> Any:
        provider_parser_inputs.append(text)
        return original_provider_parse(text, value)

    def capture_runtime_parse(text: str, value: Any) -> Any:
        runtime_parser_inputs.append(text)
        return original_runtime_parse(text, value)

    provider.http.request_json = capture_request
    ollama_module.parse_and_validate = capture_provider_parse
    service_module.parse_and_validate = capture_runtime_parse
    request = runtime_request(prompt, schema, index)
    result: dict[str, Any] = {
        "request_id": request.request_id,
        "trace_id": request.trace_id,
        "prompt_sha256": sha256_text(prompt),
        "runtime_request_contract_sha256": sha256_json(request.to_contract_request()),
    }
    try:
        generated = service.generate(request)
        result.update(
            {
                "status": "UNEXPECTED_SUCCESS",
                "result_summary": {
                    "status": generated.status,
                    "provider": generated.response.provider,
                    "provider_model": generated.response.provider_model,
                    "structured_valid": generated.response.structured is not None,
                },
            }
        )
    except LLMRuntimeError as exc:
        result.update({"status": "FAIL", "error": exc.to_dict()})
    finally:
        provider.http.request_json = original_request_json
        ollama_module.parse_and_validate = original_provider_parse
        service_module.parse_and_validate = original_runtime_parse
    result["transport"] = [transport_summary(record) for record in transport]
    result["parser_inputs"] = [
        {
            "length": len(text),
            "sha256": sha256_text(text),
            "summary": parse_summary(text, schema),
        }
        for text in provider_parser_inputs
    ]
    result["runtime_service_parser_inputs"] = [
        {"length": len(text), "sha256": sha256_text(text)}
        for text in runtime_parser_inputs
    ]
    trace = service.last_trace(request.request_id)
    result["runtime_trace"] = trace.to_dict() if trace is not None else None
    if transport:
        native_payload = transport[-1]["response"]
        native_text = str(native_payload.get("response") or "")
        provider_text = provider._response_text(native_payload)
        result["transport_identity"] = {
            "native_text_sha256": sha256_text(native_text),
            "provider_assembled_text_sha256": sha256_text(provider_text),
            "provider_parser_input_sha256": [
                sha256_text(text) for text in provider_parser_inputs
            ],
            "runtime_service_parser_input_sha256": [
                sha256_text(text) for text in runtime_parser_inputs
            ],
            "native_equals_provider": native_text == provider_text,
            "provider_equals_provider_parser": all(
                provider_text == text for text in provider_parser_inputs
            ),
            "runtime_service_parser_reached": bool(runtime_parser_inputs),
            "native_length": len(native_text),
            "provider_length": len(provider_text),
            "provider_parser_lengths": [len(text) for text in provider_parser_inputs],
            "runtime_service_parser_lengths": [
                len(text) for text in runtime_parser_inputs
            ],
            "termination": raw_termination(native_payload),
        }
        local_prefix = f"runtime_run_{index:02d}"
        result["local_artifacts"] = [
            write_local(
                local_prefix + "_request.json",
                json.dumps(
                    transport[-1]["request"], ensure_ascii=False, sort_keys=True
                ).encode("utf-8"),
            ),
            write_local(
                local_prefix + "_response.json",
                json.dumps(native_payload, ensure_ascii=False, sort_keys=True).encode(
                    "utf-8"
                ),
            ),
        ]
    try:
        text = provider._response_text(transport[-1]["response"])
        from llm_runtime.runtime.service import RuntimeService

        RuntimeService.parse_structured(text, schema)
        result["runtime_static_parser"] = {"status": "PASS"}
    except LLMRuntimeError as exc:
        result["runtime_static_parser"] = {
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": exc.to_dict() if hasattr(exc, "to_dict") else str(exc),
        }
    return result


def make_variants() -> list[tuple[str, str]]:
    exact = product_prompt(EXACT_CHUNK_IDS)
    neutral = product_prompt(CONTROL_CHUNK_IDS)
    evidence_json = json.dumps(
        {"source_chunk_ids": list(EXACT_CHUNK_IDS), "message": MESSAGE},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    delimited = (
        "Return JSON only, matching the requested generation schema. "
        "Do not diagnose, assign clinical risk, or invent citations. "
        "education_support; target_role=student; message=请给出简短建议。; "
        f"<retrieval_evidence>{evidence_json}</retrieval_evidence>"
    )
    return [
        ("A_exact_full", exact),
        ("B_neutral_chunk_ids", neutral),
        ("C_neutral_document_ids_not_present", exact),
        ("D_neutral_source_hashes_not_present", exact),
        (
            "E_strict_json_escaped_evidence",
            exact
            + "; evidence_json="
            + json.dumps(
                {"source_chunk_ids": list(EXACT_CHUNK_IDS), "message": MESSAGE},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        ),
        ("F_delimited_structured_container", delimited),
        (
            "G_remove_citation_instruction",
            exact.replace(
                "Do not diagnose, assign clinical risk, or invent citations. ", ""
            ),
        ),
        (
            "H_minimized_evidence_prose",
            "Return JSON only, matching the requested generation schema. source_chunk_ids="
            + ",".join(EXACT_CHUNK_IDS),
        ),
        (
            "I_reduced_id_lengths",
            product_prompt(("CHUNK_1", "CHUNK_2", "CHUNK_3", "CHUNK_4", "CHUNK_5")),
        ),
        (
            "J_previous_neutral_control",
            "Return JSON only, matching the requested generation schema. Do not diagnose, assign clinical risk, or invent citations. education_support; target_role=student; message=请给出简短建议。; source_chunk_ids="
            + ",".join(CONTROL_CHUNK_IDS),
        ),
        (
            "K_one_exact_id_rest_neutral",
            product_prompt((EXACT_CHUNK_IDS[0], *CONTROL_CHUNK_IDS[1:])),
        ),
        ("L_only_longest_exact_id", product_prompt((EXACT_CHUNK_IDS[0],))),
    ]


def build_service():
    import sys

    if str(RUNTIME_SRC) not in sys.path:
        sys.path.insert(0, str(RUNTIME_SRC))
    from llm_runtime.domain.models import (
        Capabilities,
        Compatibility,
        HardwareProfile,
        ModelEntry,
        ModelStatus,
    )
    from llm_runtime.domain.registry import ModelRegistry
    from llm_runtime.hardware.detector import HardwareDetector
    from llm_runtime.providers.ollama import OllamaProvider
    from llm_runtime.runtime.service import RuntimeService

    entry = ModelEntry(
        logical_model_id="qwen2.5-7b-instruct-compat",
        contract_model_id="MODEL_local_gpu_acceptance",
        display_name="Qwen2.5 7B Instruct Q4_K_M structured-output diagnosis",
        family="Qwen2.5",
        parameters="7.6B",
        provider="ollama",
        provider_model_id=MODEL,
        revision=MODEL,
        digest=DIGEST,
        expected_digest=DIGEST,
        format="gguf",
        quantization="Q4_K_M",
        capabilities=Capabilities(
            chat=True,
            stream=True,
            structured_output=True,
            json_schema=True,
            reasoning=True,
        ),
        hardware_profile=HardwareProfile.CONSUMER_GPU,
        compatibility=Compatibility.SUPPORTED,
        status=ModelStatus.READY,
        provider_version=OLLAMA_VERSION,
        priority=0,
        fallback_eligible=False,
        context_limit=CONTEXT,
        structured_output_supported=True,
        local_only=True,
    )
    provider = OllamaProvider(URL, timeout_seconds=180.0)
    service = RuntimeService(
        ModelRegistry([entry], registry_version="structured-output-compat-r1"),
        {"ollama": provider},
        hardware=HardwareDetector().detect(),
        runtime_version="0.1.0-structured-output-compat-r1",
        max_attempts=1,
        backoff_seconds=(),
        default_model_id=entry.logical_model_id,
        max_generation_concurrency=1,
        preload_primary=False,
    )
    return service, provider


def main() -> int:
    schema, schema_identity = load_actual_schema()
    process, owned = start_ollama()
    service = None
    provider = None
    try:
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            wait_ready(client)
            snapshot = model_snapshot(client)
            exact_runs: list[dict[str, Any]] = []
            service, provider = build_service()
            service.startup()
            for index in range(1, 4):
                prompt = product_prompt(EXACT_CHUNK_IDS)
                native = direct_case(
                    client,
                    f"exact_product_prompt_{index:02d}",
                    prompt,
                    schema,
                    run_index=index,
                )
                runtime = runtime_case(service, provider, schema, prompt, index)
                exact_runs.append({"native": native, "runtime": runtime})
            matrix: list[dict[str, Any]] = []
            for variant_id, prompt in make_variants():
                result = direct_case(client, variant_id, prompt, schema)
                result["description"] = {
                    "A_exact_full": "exact current product prompt with accepted chunk identities",
                    "B_neutral_chunk_ids": "same product message with neutral chunk identities",
                    "C_neutral_document_ids_not_present": "document IDs are not serialized by current product prompt",
                    "D_neutral_source_hashes_not_present": "source hashes are not serialized by current product prompt",
                    "E_strict_json_escaped_evidence": "exact identities represented in a JSON-escaped evidence suffix",
                    "F_delimited_structured_container": "exact identities in a clearly delimited JSON evidence container",
                    "G_remove_citation_instruction": "exact identities with citation-invention instruction removed",
                    "H_minimized_evidence_prose": "exact identities with only minimal instruction prose",
                    "I_reduced_id_lengths": "same shape with reduced chunk ID lengths",
                    "J_previous_neutral_control": "previous closure neutral-control shape",
                    "K_one_exact_id_rest_neutral": "one exact ID plus neutral IDs",
                    "L_only_longest_exact_id": "only the first exact ID",
                }.get(variant_id, "diagnostic variant")
                matrix.append(result)
            output = {
                "round": "STRUCTURED_OUTPUT_PRODUCT_COMPATIBILITY_CLOSURE_R1_ROOT_CAUSE",
                "synthetic_only": True,
                "accepted_publication": {
                    "path": str(
                        ROOT
                        / "04_knowledge-pipeline"
                        / "data"
                        / "published"
                        / "round1"
                        / "embedding_ready.jsonl"
                    ),
                    "sha256": "2d5736ae741d675ca5856b8004665ea3043aeccea34e2b007498ff04c2b501a2",
                    "chunk_ids": list(EXACT_CHUNK_IDS),
                    "d2_candidate_used": False,
                },
                "prompt_source": {
                    "path": str(
                        ROOT
                        / "09_backend"
                        / "src"
                        / "smhai_backend"
                        / "domains"
                        / "support"
                        / "service.py"
                    ),
                    "symbol": "SupportService._build_prompt",
                    "serialization": "source_chunk_ids=comma_joined_chunk_ids",
                    "message": MESSAGE,
                    "target_role": TARGET_ROLE,
                },
                "schema": schema_identity,
                "provider": {
                    "endpoint": URL,
                    "version": OLLAMA_VERSION,
                    "model": MODEL,
                    "digest": DIGEST,
                    "context": CONTEXT,
                    "kv": "f16",
                    "parallel": 1,
                    "max_output_tokens": MAX_OUTPUT,
                    "temperature": TEMPERATURE,
                    "top_p": TOP_P,
                    "seed": SEED,
                    "snapshot": snapshot,
                },
                "exact_product_prompt_runs": exact_runs,
                "deterministic_failure_count": sum(
                    1 for item in exact_runs if item["runtime"].get("status") == "FAIL"
                ),
                "prompt_bisection_matrix": matrix,
                "truncation_analysis": {
                    "required_fields": [
                        "num_ctx",
                        "prompt_eval_count",
                        "eval_count",
                        "num_predict",
                        "done_reason",
                        "response_terminated",
                    ],
                    "conclusion": "RECORDED_PER_CASE",
                },
                "transport_analysis": {
                    "conclusion": "RECORDED_PER_RUNTIME_CASE",
                    "layers": [
                        "native Ollama response",
                        "OllamaProvider._response_text",
                        "provider parser input",
                        "RuntimeService.parse_structured replay",
                    ],
                },
                "process": {
                    "ollama_process_owned_by_diagnostic": owned,
                    "terminated_by_diagnostic": bool(process),
                },
            }
            (EVIDENCE / "root_cause_reproduction.json").write_text(
                json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (EVIDENCE / "prompt_bisection_matrix.jsonl").write_text(
                "".join(
                    json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                    for item in matrix
                ),
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "exact_runtime_failures": output["deterministic_failure_count"],
                        "exact_runs": len(exact_runs),
                        "matrix_cases": len(matrix),
                        "schema_sha256": schema_identity["schema_sha256"],
                        "provider": MODEL,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
    finally:
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
