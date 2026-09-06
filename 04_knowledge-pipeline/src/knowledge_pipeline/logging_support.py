"""Structured events that comply with logging.v1."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def make_log_record(
    *,
    run_id: str,
    document_id: str | None,
    stage: str,
    status: str,
    duration_ms: int | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    outcome = {"started": "started", "success": "success", "warning": "warning", "blocked": "blocked", "failed": "failed"}.get(status, "failed")
    record: dict[str, Any] = {
        "schema_version": "logging.v1",
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "level": "ERROR" if outcome == "failed" else "INFO",
        "event": f"KNOWLEDGE_{stage.upper()}",
        "component": "04_knowledge-pipeline",
        "request_id": f"REQ_{run_id.removeprefix('RUN_')}",
        "trace_id": f"TRACE_{(document_id or run_id).removeprefix('KB_').removeprefix('RUN_')}",
        "outcome": outcome,
        "duration_ms": duration_ms,
        "error_code": error_code,
        "metadata": {"operation": stage, "dependency": "knowledge_pipeline"},
    }
    return record

