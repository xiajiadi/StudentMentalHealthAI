"""Small local CLI for runtime discovery and synthetic generation checks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .domain.models import GenerationConfig, GenerationRequest
from .domain.registry import ModelRegistry
from .hardware.detector import HardwareDetector
from .providers.llama_cpp import LlamaCppProvider
from .providers.mock import MockProvider
from .providers.ollama import OllamaProvider
from .runtime.service import RuntimeService

MODULE_ROOT = Path(__file__).resolve().parents[2]


def build_service() -> RuntimeService:
    registry = ModelRegistry.from_file(MODULE_ROOT / "config" / "models.v1.json")
    runtime = json.loads((MODULE_ROOT / "config" / "runtime.v1.json").read_text(encoding="utf-8"))
    ollama_config = runtime["ollama"]
    llama_config = runtime["llama_cpp"]
    llama_timeout = llama_config.get("timeout_seconds", 60)
    providers = {
        "ollama": OllamaProvider(
            ollama_config["base_url"], timeout_seconds=float(ollama_config["timeout_seconds"])
        ),
        "llama.cpp": LlamaCppProvider(
            llama_config["base_url"],
            timeout_seconds=float(llama_timeout),
        ),
        "mock": MockProvider(("mock-model",)),
    }
    retry = runtime["retry"]
    return RuntimeService(
        registry,
        providers,
        hardware=HardwareDetector().detect(),
        runtime_version=runtime["runtime_version"],
        max_attempts=int(retry["max_attempts"]),
        backoff_seconds=tuple(float(value) for value in retry["backoff_seconds"]),
        default_model_id=str(runtime["default_model_id"]),
    )


def make_request(model_id: str, prompt: str, *, stream: bool = False) -> GenerationRequest:
    schema = {
        "type": "object",
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    return GenerationRequest(
        request_id="REQ_cli_001",
        trace_id="TRACE_cli_001",
        generation_id="GEN_cli_001",
        assessment_id="ASSESS_cli_001",
        subject_id="SUBJ_cli_001",
        target_role="teacher",
        purpose="education_support",
        language="en",
        safety_mode="standard",
        retrieval_id="RETR_cli_001",
        chunk_ids=("CHUNK_cli_001",),
        prompt_id="PROMPT_cli_v1",
        prompt_version="0.1.0",
        contract_model_id="MODEL_local_cpu_test",
        logical_model_id=model_id,
        prompt=prompt,
        stream=stream,
        structured_schema=schema if not stream else None,
        config=GenerationConfig(max_output_tokens=64, timeout_seconds=60),
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="llm-runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hardware")
    sub.add_parser("models")
    sub.add_parser("discover")
    sub.add_parser("health")
    generate = sub.add_parser("generate")
    generate.add_argument("--model", default="qwen2.5-0.5b-engineering")
    generate.add_argument("--prompt", default="Reply with a short synthetic engineering response.")
    generate.add_argument("--stream", action="store_true")
    args = parser.parse_args()
    service = build_service()
    if args.command == "hardware":
        print(json.dumps(service.hardware.to_dict(), ensure_ascii=False, indent=2))
    elif args.command == "models":
        print(json.dumps(service.list_models(), ensure_ascii=False, indent=2))
    elif args.command == "discover":
        print(json.dumps(service.discover(), ensure_ascii=False, indent=2))
    elif args.command == "health":
        print(json.dumps(service.health(), ensure_ascii=False, indent=2))
    elif args.command == "generate":
        request = make_request(args.model, args.prompt, stream=args.stream)
        if args.stream:
            for event in service.stream_generate(request):
                print(json.dumps(event.to_dict(), ensure_ascii=False))
        else:
            result = service.generate(request)
            print(
                json.dumps(
                    {"text": result.text, "trace": result.trace.to_dict()},
                    ensure_ascii=False,
                    indent=2,
                )
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
