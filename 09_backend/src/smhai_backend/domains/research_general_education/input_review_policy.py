"""Versioned engineering workflow policy; never a professional approval token."""

from __future__ import annotations

import hashlib
import json

from .prompt import (
    FIXED_GENERAL_EDUCATION_REQUEST,
    PROMPT_ID,
    PROMPT_SHA256,
    PROMPT_VERSION,
    get_prompt_definition,
)

INPUT_REVIEW_CONTINUATION_POLICY_VERSION = "RESEARCH_INPUT_REVIEW_ONCE_V1"

def continuation_policy_sha256_for_prompt(
    prompt_id: object, prompt_version: object, prompt_sha256: object
) -> str | None:
    """Return the closed policy fingerprint for an exact registered prompt."""
    prompt = get_prompt_definition(prompt_id, prompt_version, prompt_sha256)
    if prompt is None:
        return None
    policy = {
        "version": INPUT_REVIEW_CONTINUATION_POLICY_VERSION,
        "purpose": "RESEARCH_SIMULATION",
        "fixed_request_sha256": hashlib.sha256(
            FIXED_GENERAL_EDUCATION_REQUEST.encode("utf-8")
        ).hexdigest(),
        "prompt_sha256": prompt.sha256,
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
    return hashlib.sha256(
        json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


INPUT_REVIEW_CONTINUATION_POLICY_SHA256 = continuation_policy_sha256_for_prompt(
    PROMPT_ID, PROMPT_VERSION, PROMPT_SHA256
)
