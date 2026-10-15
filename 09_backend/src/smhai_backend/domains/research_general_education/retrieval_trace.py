"""Closed R3 retrieval trace shared by capture and snapshot rebinding."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

R3_RETRIEVAL_TRACE_FIELDS = (
    "package_id",
    "manifest_sha256",
    "study_ref",
    "purpose",
    "target_population",
    "target_role",
    "review_status",
    "rights_status",
    "source_rights_status",
    "consumer_age_min",
    "consumer_age_max",
    "query_transform",
    "matched_layers",
    "missing_layers",
    "required_layers",
    "selection_strategy",
    "reviewer_kind",
    "research_only",
    "professional_approval",
    "human_curated",
    "ethics_approval",
    "clinical_approval",
    "psychometric_approval",
    "publication_eligible",
    "production_use",
)
R3_GENERAL_EDUCATION_REQUIRED_LAYERS = ("policy", "theory", "intervention")
_R3_QUERY_TRANSFORMS = frozenset(
    {"NONE", "LEXICAL_BILINGUAL_KEYWORD_EXPANSION"}
)


def project_r3_retrieval_trace(trace: Mapping[str, object]) -> dict[str, Any]:
    """Copy the exact known 25-field R3 trace without dropping or adding keys."""
    if not isinstance(trace, Mapping) or set(trace) != set(R3_RETRIEVAL_TRACE_FIELDS):
        raise ValueError("R3 retrieval trace fields do not match the closed contract")
    if (
        type(trace["query_transform"]) is not str
        or trace["query_transform"] not in _R3_QUERY_TRANSFORMS
        or type(trace["required_layers"]) is not list
        or tuple(trace["required_layers"]) != R3_GENERAL_EDUCATION_REQUIRED_LAYERS
        or trace["selection_strategy"] != "LAYER_FIRST_BOUNDED_POOL"
        or trace["reviewer_kind"] != "AI_ENGINEERING"
    ):
        raise ValueError("R3 retrieval trace values do not match the closed contract")
    return {name: trace[name] for name in R3_RETRIEVAL_TRACE_FIELDS}


__all__ = [
    "R3_GENERAL_EDUCATION_REQUIRED_LAYERS",
    "R3_RETRIEVAL_TRACE_FIELDS",
    "project_r3_retrieval_trace",
]
