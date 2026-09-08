"""Acceptance-only local Ollama structured-output comparison.

This diagnostic intentionally reports no generated text. It compares the
accepted RAG chunk identities with a neutral control while keeping the exact
Ollama model, schema, seed, and generation options used by the product flow.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx


OLLAMA = Path(r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\ollama-0.33.3\ollama.exe")
MODELS = Path(r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\models")
URL = "http://127.0.0.1:11435"
MODEL = "qwen2.5:7b-instruct-q4_K_M"
EVIDENCE_FILE = Path(__file__).with_name("ollama_structured_output_diagnosis.jsonl")


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "observations", "suggestions", "disclaimer"],
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "observations": {"type": "array", "items": {"type": "string"}},
            "suggestions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "source_chunk_ids"],
                    "properties": {
                        "text": {"type": "string", "minLength": 1},
                        "source_chunk_ids": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                    },
                },
            },
            "disclaimer": {"type": "string", "minLength": 1},
        },
    }


def main() -> int:
    exact_ids = ",".join(
        [
            "CHUNK_67b56abe21fe9860a26d",
            "CHUNK_8f85f2c0472e21acd2fa",
            "CHUNK_c3718c65fcf4151af391",
            "CHUNK_3d2d02ba1c8fbc506665",
            "CHUNK_bcbe71382652340b2249",
        ]
    )
    control_ids = "CHUNK_A,CHUNK_B,CHUNK_C,CHUNK_D,CHUNK_E"
    env = os.environ.copy()
    env.update(
        {
            "OLLAMA_HOST": "127.0.0.1:11435",
            "OLLAMA_MODELS": str(MODELS),
            "OLLAMA_CONTEXT_LENGTH": "8192",
            "OLLAMA_NUM_PARALLEL": "1",
            "OLLAMA_KEEP_ALIVE": "5m",
        }
    )
    process = subprocess.Popen(
        [str(OLLAMA), "serve"],
        cwd=str(OLLAMA.parent),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        with httpx.Client(timeout=180.0) as client:
            deadline = time.monotonic() + 60
            while True:
                try:
                    if client.get(f"{URL}/api/version").status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError("diagnostic Ollama did not become ready")
                time.sleep(1)

            results: list[dict[str, Any]] = []
            for label, chunk_ids in (("exact", exact_ids), ("control", control_ids)):
                prompt = (
                    "Return JSON only, matching the requested generation schema. "
                    "Do not diagnose, assign clinical risk, or invent citations. "
                    f"education_support; target_role=student; message=请给出简短建议。; "
                    f"source_chunk_ids={chunk_ids}"
                )
                response = client.post(
                    f"{URL}/api/generate",
                    json={
                        "model": MODEL,
                        "prompt": prompt,
                        "stream": False,
                        "format": schema(),
                        "options": {
                            "num_predict": 384,
                            "temperature": 0.1,
                            "top_p": 0.9,
                            "seed": 20260906,
                            "num_ctx": 8192,
                        },
                        "keep_alive": "5m",
                    },
                )
                payload = response.json()
                generated = str(payload.get("response") or "")
                result: dict[str, Any] = {
                    "case": label,
                    "http_status": response.status_code,
                    "response_length": len(generated),
                    "response_sha256": hashlib.sha256(generated.encode("utf-8")).hexdigest(),
                }
                try:
                    value = json.loads(generated)
                    result.update(
                        {
                            "json_parse": "PASS",
                            "json_type": type(value).__name__,
                            "json_keys": sorted(value) if isinstance(value, dict) else None,
                        }
                    )
                except json.JSONDecodeError as exc:
                    result.update(
                        {
                            "json_parse": "FAIL",
                            "json_line": exc.lineno,
                            "json_column": exc.colno,
                        }
                    )
                results.append(result)
            EVIDENCE_FILE.write_text(
                "".join(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n" for result in results),
                encoding="utf-8",
            )
            for result in results:
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
