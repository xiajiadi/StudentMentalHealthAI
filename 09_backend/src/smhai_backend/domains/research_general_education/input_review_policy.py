"""Versioned engineering workflow policy; never a professional approval token."""

from __future__ import annotations

import hashlib
import json

from .prompt import FIXED_GENERAL_EDUCATION_REQUEST, PROMPT_SHA256

INPUT_REVIEW_CONTINUATION_POLICY_VERSION = "RESEARCH_INPUT_REVIEW_ONCE_V1"

_POLICY = {
    "version": INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
    "purpose": "RESEARCH_SIMULATION",
    "fixed_request_sha256": hashlib.sha256(
        FIXED_GENERAL_EDUCATION_REQUEST.encode("utf-8")
    ).hexdigest(),
    "prompt_sha256": PROMPT_SHA256,
    "operation": "INPUT",
    "action": "REVIEW_REQUIRED",
    "requires_human": True,
    "reason_codes": ["CONTENT_CONTROVERSIAL"],
    "authorization_role": "PSYCHOLOGICAL_SPECIALIST",
    "authorization_scope": "CURRENT_ASSIGNED_TASK",
    "worker_role": "SYSTEM",
    "generation_round": 1,
    "max_jobs_per_review": 1,
    "max_attempts_per_job": 1,
    "maximum_expiry_seconds": 86_400,
    "source_policy_prompt_scope_binding_required": True,
    "original_input_decision_preserved": True,
    "retrieval_safety_required": True,
    "output_safety_required": True,
    "candidate_status": "HELD",
    "professional_approval": False,
    "automatic_adoption": False,
    "automatic_publication": False,
}

INPUT_REVIEW_CONTINUATION_POLICY_SHA256 = hashlib.sha256(
    json.dumps(_POLICY, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
).hexdigest()
