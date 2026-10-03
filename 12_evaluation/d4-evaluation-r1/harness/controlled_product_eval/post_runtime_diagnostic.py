"""Bounded diagnostics for the authorized non-formal post-Runtime smoke."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


BACKEND_DETAIL_CODE_BY_EXACT_VALUE = {
    "LLM Runtime returned an invalid generation projection": "LLM_RUNTIME_PROJECTION_INVALID",
    "Safety returned an invalid decision": "OUTPUT_SAFETY_DECISION_INVALID",
    "LLM Runtime returned invalid structured content": "GENERATION_CONTENT_INVALID",
    "LLM Runtime returned content outside the approved generation boundary": "GENERATED_CLAIM_BOUNDARY_VIOLATION",
    "LLM Runtime returned an unbound citation": "CITATION_BINDING_FAILED",
}
KNOWN_DIAGNOSTIC_CODES = frozenset(BACKEND_DETAIL_CODE_BY_EXACT_VALUE.values())
UNMAPPED_SAFE_DETAIL = "UNMAPPED_SAFE_DETAIL"
INDETERMINATE = "INDETERMINATE"
OTHER_CONFIRMED_POST_RUNTIME_PRODUCT_DEFECT = "OTHER_CONFIRMED_POST_RUNTIME_PRODUCT_DEFECT"
REPORTABLE_CLASSIFICATIONS = frozenset(
    {*KNOWN_DIAGNOSTIC_CODES, OTHER_CONFIRMED_POST_RUNTIME_PRODUCT_DEFECT, INDETERMINATE}
)

_CHUNK_ID = re.compile(r"^CHUNK_[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_CANDIDATE_BYTES_FOR_PARSE = 2_000_000
_MAX_SOURCE_CHUNK_IDS = 100
_CANDIDATE_PARSE_STATUSES = frozenset(
    {
        "NOT_OBSERVED",
        "RUNTIME_RESPONSE_INVALID",
        "TEXT_NOT_PRESENT",
        "INVALID_UNICODE",
        "CANDIDATE_TOO_LARGE",
        "INVALID_JSON",
        "INVALID_GENERATION_CONTENT_SHAPE",
        "VALID_GENERATION_CONTENT",
    }
)
_SAFETY_ACTIONS = frozenset(
    {"PROCEED", "PROCEED_WITH_BOUNDARY", "BLOCK", "REVIEW_REQUIRED", "CRISIS_ROUTE"}
)
_SAFETY_REASON_CODES = frozenset(
    {
        "NO_BLOCKING_SIGNAL",
        "EXPLICIT_CRISIS_SIGNAL",
        "CONTENT_UNSAFE",
        "PROMPT_INJECTION",
        "JAILBREAK",
        "CLINICAL_OVERREACH",
        "CONTENT_CONTROVERSIAL",
        "PII_DETECTED",
        "DISCLOSURE_RESTRICTED",
        "ASSESSMENT_SIGNAL_RECEIVED",
        "RETRIEVAL_SOURCE_INELIGIBLE",
        "COMPONENT_UNAVAILABLE",
        "SAFETY_SERVICE_UNAVAILABLE",
        "POLICY_ENGINE_UNAVAILABLE",
        "POLICY_EVALUATION_FAILED",
        "GUARD_MODEL_UNAVAILABLE",
        "PRIVACY_ENGINE_UNAVAILABLE",
        "GUARDRAIL_CHECK_FAILED",
        "INVALID_SAFETY_CONTEXT",
        "REVIEW_QUEUE_FAILED",
        "CRISIS_TEMPLATE_UNAVAILABLE",
        "RETRIEVAL_SAFETY_CHECK_FAILED",
    }
)


def project_runtime_candidate(value: Any) -> dict[str, Any]:
    """Return only bounded candidate length/hash and safe structured references."""

    response = value if isinstance(value, Mapping) else None
    nested_data = response.get("data") if response is not None else None
    data = nested_data if isinstance(nested_data, Mapping) else response
    if not isinstance(data, Mapping):
        return {
            "candidate_text_length_chars": None,
            "candidate_text_sha256": None,
            "candidate_parse_status": "RUNTIME_RESPONSE_INVALID",
            "source_chunk_ids": [],
        }

    text = data.get("text")
    if not isinstance(text, str):
        return {
            "candidate_text_length_chars": None,
            "candidate_text_sha256": None,
            "candidate_parse_status": "TEXT_NOT_PRESENT",
            "source_chunk_ids": [],
        }

    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        return {
            "candidate_text_length_chars": len(text),
            "candidate_text_sha256": None,
            "candidate_parse_status": "INVALID_UNICODE",
            "source_chunk_ids": [],
        }

    candidate_hash = "sha256:" + hashlib.sha256(encoded).hexdigest()
    summary = {
        "candidate_text_length_chars": len(text),
        "candidate_text_sha256": candidate_hash,
        "source_chunk_ids": [],
    }
    if len(encoded) > _MAX_CANDIDATE_BYTES_FOR_PARSE:
        return {**summary, "candidate_parse_status": "CANDIDATE_TOO_LARGE"}

    try:
        content = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {**summary, "candidate_parse_status": "INVALID_JSON"}

    source_chunk_ids = _validated_source_chunk_ids(content)
    if source_chunk_ids is None:
        return {**summary, "candidate_parse_status": "INVALID_GENERATION_CONTENT_SHAPE"}
    return {
        **summary,
        "candidate_parse_status": "VALID_GENERATION_CONTENT",
        "source_chunk_ids": source_chunk_ids,
    }


def _validated_source_chunk_ids(value: Any) -> list[str] | None:
    if not isinstance(value, Mapping) or set(value) != {
        "summary",
        "observations",
        "suggestions",
        "disclaimer",
    }:
        return None
    if not isinstance(value.get("summary"), str) or not value["summary"]:
        return None
    if not isinstance(value.get("disclaimer"), str) or not value["disclaimer"]:
        return None
    observations = value.get("observations")
    if not isinstance(observations, list) or any(not isinstance(item, str) for item in observations):
        return None
    suggestions = value.get("suggestions")
    if not isinstance(suggestions, list):
        return None

    source_chunk_ids: list[str] = []
    for suggestion in suggestions:
        if not isinstance(suggestion, Mapping) or set(suggestion) != {"text", "source_chunk_ids"}:
            return None
        if not isinstance(suggestion.get("text"), str) or not suggestion["text"]:
            return None
        item_ids = suggestion.get("source_chunk_ids")
        if not isinstance(item_ids, list) or not item_ids:
            return None
        if any(not isinstance(item, str) or not _CHUNK_ID.fullmatch(item) for item in item_ids):
            return None
        source_chunk_ids.extend(item_ids)
        if len(source_chunk_ids) > _MAX_SOURCE_CHUNK_IDS:
            return None
    return source_chunk_ids


def project_post_runtime_diagnostic(
    *,
    http_status: int,
    response_body: Mapping[str, Any],
    request_id: str,
    trace_id: str,
    runtime_events: Any,
    safety_events: Any,
) -> dict[str, Any]:
    """Project only exact allowlisted details and correlated observer metadata."""

    correlated_runtime = _correlated_events(runtime_events, request_id, trace_id)
    runtime_event = correlated_runtime[0] if len(correlated_runtime) == 1 else {}
    runtime_http_status = _http_status(runtime_event.get("status_code"))
    response_summary = runtime_event.get("response_summary")
    response_summary = response_summary if isinstance(response_summary, Mapping) else {}

    detail_code = _project_exact_backend_detail(response_body) if http_status == 502 else None
    if http_status == 502 and runtime_http_status == 200 and detail_code in KNOWN_DIAGNOSTIC_CODES:
        classification = detail_code
    else:
        classification = INDETERMINATE

    correlated_safety = _correlated_events(safety_events, request_id, trace_id)
    output_events = [event for event in correlated_safety if event.get("stage") == "OUTPUT"]
    output_event = output_events[0] if len(output_events) == 1 else {}
    if output_events:
        output_request_issued: bool | None = True
    elif classification == "LLM_RUNTIME_PROJECTION_INVALID" and runtime_http_status == 200:
        output_request_issued = False
    else:
        output_request_issued = None

    raw_reasons = output_event.get("reason_codes")
    output_reasons = (
        list(dict.fromkeys(code for code in raw_reasons if isinstance(code, str) and code in _SAFETY_REASON_CODES))
        if isinstance(raw_reasons, list)
        else []
    )
    candidate_parse_status = response_summary.get("candidate_parse_status")
    if candidate_parse_status not in _CANDIDATE_PARSE_STATUSES:
        candidate_parse_status = "NOT_OBSERVED"
    candidate_length = response_summary.get("candidate_text_length_chars")
    if type(candidate_length) is not int or candidate_length < 0:
        candidate_length = None
    candidate_hash = response_summary.get("candidate_text_sha256")
    if not isinstance(candidate_hash, str) or not _SHA256.fullmatch(candidate_hash):
        candidate_hash = None
    raw_chunk_ids = response_summary.get("source_chunk_ids")
    source_chunk_ids = (
        [item for item in raw_chunk_ids if isinstance(item, str) and _CHUNK_ID.fullmatch(item)]
        if isinstance(raw_chunk_ids, list)
        and candidate_parse_status == "VALID_GENERATION_CONTENT"
        else []
    )
    if isinstance(raw_chunk_ids, list) and len(source_chunk_ids) != len(raw_chunk_ids):
        source_chunk_ids = []

    return {
        "schema_version": "d4-post-runtime-502-diagnostic-record.v1",
        "request_id": request_id,
        "trace_id": trace_id,
        "http_status": http_status,
        "runtime_http_status": runtime_http_status,
        "output_safety_request_issued": output_request_issued,
        "output_safety_http_status": _http_status(output_event.get("status_code")),
        "output_safety_action": (
            output_event.get("action") if output_event.get("action") in _SAFETY_ACTIONS else None
        ),
        "output_safety_reason_codes": output_reasons,
        "candidate_text_length_chars": candidate_length,
        "candidate_text_sha256": candidate_hash,
        "candidate_parse_status": candidate_parse_status,
        "source_chunk_ids": source_chunk_ids,
        "detail_projection_code": detail_code,
        "primary_classification": classification,
    }


def _project_exact_backend_detail(value: Mapping[str, Any]) -> str:
    details: list[str] = []
    top_level_detail = value.get("detail")
    if isinstance(top_level_detail, str):
        details.append(top_level_detail)
    error = value.get("error")
    if isinstance(error, Mapping):
        for field in ("detail", "message"):
            detail = error.get(field)
            if isinstance(detail, str):
                details.append(detail)
    unique_details = set(details)
    if len(unique_details) != 1:
        return UNMAPPED_SAFE_DETAIL
    return BACKEND_DETAIL_CODE_BY_EXACT_VALUE.get(next(iter(unique_details)), UNMAPPED_SAFE_DETAIL)


def _correlated_events(value: Any, request_id: str, trace_id: str) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        events = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        events = value
    else:
        return []
    return [
        event
        for event in events
        if isinstance(event, Mapping)
        and event.get("request_id") == request_id
        and event.get("trace_id") == trace_id
    ]


def _http_status(value: Any) -> int | None:
    return value if type(value) is int and 100 <= value <= 599 else None
