"""Find the smallest deterministic output budget that completes the exact prompt."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import httpx
from root_cause_diagnostic import (
    CONTEXT,
    DIGEST,
    EVIDENCE,
    EXACT_CHUNK_IDS,
    MAX_OUTPUT,
    MODEL,
    SEED,
    TEMPERATURE,
    TOP_P,
    URL,
    load_actual_schema,
    parse_summary,
    product_prompt,
    request_payload,
    start_ollama,
    wait_ready,
    write_local,
)


def main() -> int:
    schema, schema_identity = load_actual_schema()
    process, owned = start_ollama()
    budgets = [MAX_OUTPUT, 512, 640, 768, 1024]
    rows: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            wait_ready(client)
            for budget in budgets:
                payload = request_payload(product_prompt(EXACT_CHUNK_IDS), schema)
                payload["options"]["num_predict"] = budget
                response = client.post(URL + "/api/generate", json=payload)
                response.raise_for_status()
                native = response.json()
                text = str(native.get("response") or "")
                row = {
                    "num_predict": budget,
                    "http_status": response.status_code,
                    "request_sha256": __import__("hashlib")
                    .sha256(
                        json.dumps(
                            payload,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                    )
                    .hexdigest(),
                    "response_body_sha256": __import__("hashlib")
                    .sha256(response.content)
                    .hexdigest(),
                    "response_sha256": __import__("hashlib")
                    .sha256(text.encode("utf-8"))
                    .hexdigest(),
                    "response_length": len(text),
                    "prompt_eval_count": native.get("prompt_eval_count"),
                    "eval_count": native.get("eval_count"),
                    "done": native.get("done"),
                    "done_reason": native.get("done_reason"),
                    "parse": parse_summary(text, schema),
                }
                artifact_prefix = f"budget_{budget}"
                row["local_artifacts"] = [
                    write_local(
                        artifact_prefix + "_request.json",
                        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode(
                            "utf-8"
                        ),
                    ),
                    write_local(artifact_prefix + "_response.json", response.content),
                ]
                rows.append(row)
            output = {
                "round": "STRUCTURED_OUTPUT_PRODUCT_COMPATIBILITY_CLOSURE_R1_OUTPUT_BUDGET_LADDER",
                "synthetic_only": True,
                "model": MODEL,
                "digest": DIGEST,
                "context": CONTEXT,
                "seed": SEED,
                "temperature": TEMPERATURE,
                "top_p": TOP_P,
                "schema_sha256": schema_identity["schema_sha256"],
                "exact_prompt_sha256": __import__("hashlib")
                .sha256(product_prompt(EXACT_CHUNK_IDS).encode("utf-8"))
                .hexdigest(),
                "budgets": rows,
                "process": {
                    "ollama_process_owned_by_diagnostic": owned,
                    "terminated_by_diagnostic": bool(process),
                },
            }
            (EVIDENCE / "output_budget_ladder.json").write_text(
                json.dumps(output, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                json.dumps(
                    {
                        "budgets": [
                            {
                                "num_predict": row["num_predict"],
                                "parse": row["parse"]["json_parse"],
                                "done_reason": row["done_reason"],
                                "eval_count": row["eval_count"],
                            }
                            for row in rows
                        ]
                    },
                    ensure_ascii=False,
                )
            )
    finally:
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
