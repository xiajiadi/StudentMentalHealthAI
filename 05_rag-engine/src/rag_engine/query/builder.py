"""Deterministic, non-LLM retrieval planning from structured inputs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..config import RAGConfig
from ..domain import KNOWLEDGE_LAYERS, ROLES, RISK_LEVELS, LayerBudget, MetadataFilter, RetrievalPlan
from ..exceptions import ContractValidationError, UnsafeQueryError


def validate_assessment_shape(assessment: Mapping[str, Any]) -> None:
    """Validate the fields this module consumes without redefining the root schema."""

    required = {
        "schema_version",
        "assessment_id",
        "subject_id",
        "population_scope",
        "status",
        "dimensions",
        "risk",
    }
    missing = sorted(required - set(assessment))
    if missing:
        raise ContractValidationError(f"Assessment is missing required fields: {missing}")
    if assessment.get("schema_version") != "assessment.v1":
        raise ContractValidationError("Assessment schema_version must be assessment.v1")
    if not re.fullmatch(r"ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*", str(assessment.get("assessment_id"))):
        raise ContractValidationError("Assessment assessment_id does not match the frozen ID rule")
    if not re.fullmatch(r"SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*", str(assessment.get("subject_id"))):
        raise ContractValidationError("Assessment subject_id does not match the frozen ID rule")
    risk = assessment.get("risk")
    if not isinstance(risk, Mapping) or risk.get("level") not in RISK_LEVELS:
        raise ContractValidationError("Assessment risk.level is invalid")
    dimensions = assessment.get("dimensions")
    if not isinstance(dimensions, Mapping) or not dimensions:
        raise ContractValidationError("Assessment dimensions must be a non-empty object")


class DeterministicQueryBuilder:
    """Build a structured plan without clinical interpretation or query rewriting."""

    def __init__(self, config: RAGConfig) -> None:
        self.config = config

    def build(
        self,
        assessment: Mapping[str, Any],
        *,
        role: str,
        target_population: str | None = None,
        dimension: str | None = None,
        topic: str | None = None,
        intent: str | None = None,
        user_query: str | None = None,
        layers: tuple[str, ...] | list[str] | None = None,
        query_type: str = "unknown",
    ) -> RetrievalPlan:
        validate_assessment_shape(assessment)
        if role not in ROLES:
            raise ContractValidationError(f"target role is invalid: {role}")
        risk = str(assessment["risk"]["level"])
        population = str(target_population or assessment.get("population_scope") or "").strip()
        if not population:
            raise ContractValidationError("Assessment population_scope is empty")
        dimensions = assessment["dimensions"]
        selected_dimension = dimension or sorted(str(key) for key in dimensions)[0]
        if selected_dimension not in dimensions:
            raise ContractValidationError(f"Requested dimension is not present in Assessment: {selected_dimension}")

        supplied_query = (user_query or "").strip()
        self._assert_safe_query(supplied_query)
        topic_text = (topic or "").strip()
        intent_text = (intent or "").strip()
        self._assert_safe_query(topic_text)
        self._assert_safe_query(intent_text)

        components = [item for item in (supplied_query, topic_text, selected_dimension, intent_text) if item]
        if not components:
            components = [selected_dimension]
        built = "；".join(dict.fromkeys(components))
        # Query variants are deterministic field compositions, not LLM-generated
        # paraphrases. They make the provenance of each query explicit.
        queries = [built]
        if supplied_query and supplied_query != selected_dimension:
            queries.append(f"{selected_dimension} {supplied_query}")
        queries = list(dict.fromkeys(query.strip() for query in queries if query.strip()))

        chosen_layers = self._choose_layers(intent_text, layers)
        quota = max(1, (self.config.final_k + len(chosen_layers) - 1) // len(chosen_layers))
        layer_budgets = tuple(LayerBudget(layer=layer, quota=quota) for layer in chosen_layers)
        metadata_filter = MetadataFilter(
            role_scope=(role,),
            target_population=(population,),
            risk_scope=(risk,),
        )
        return RetrievalPlan(
            queries=tuple(queries),
            filters=metadata_filter,
            layers=layer_budgets,
            retrieval_mode=self.config.retrieval_mode,
            dense_candidate_k=self.config.dense_candidate_k,
            sparse_candidate_k=self.config.sparse_candidate_k,
            fusion_candidate_k=self.config.fusion_candidate_k,
            rerank_candidate_k=self.config.rerank_candidate_k,
            final_k=self.config.final_k,
            rerank_enabled=self.config.reranker.provider != "noop" and bool(self.config.reranker.model_name),
            context_max_chars=self.config.context_max_chars,
            assessment_id=str(assessment["assessment_id"]),
            role=role,
            target_population=population,
            dimension=selected_dimension,
            topic=topic_text or None,
            intent=intent_text or None,
            risk_level=risk,
            query_type=query_type,
        )

    @staticmethod
    def _choose_layers(intent: str, layers: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
        if layers:
            chosen = tuple(dict.fromkeys(str(layer) for layer in layers))
            invalid = set(chosen) - set(KNOWLEDGE_LAYERS)
            if invalid:
                raise ContractValidationError(f"Invalid knowledge layer(s): {sorted(invalid)}")
            return chosen
        lowered = intent.lower()
        if any(token in lowered for token in ("policy", "规则", "流程", "制度", "governance")):
            return ("policy",)
        if any(token in lowered for token in ("theory", "概念", "理论", "explain", "understand")):
            return ("theory",)
        if any(token in lowered for token in ("intervention", "support", "支持", "行动", "建议", "步骤")):
            return ("intervention",)
        return KNOWLEDGE_LAYERS

    @staticmethod
    def _assert_safe_query(value: str) -> None:
        if not value:
            return
        patterns = (
            r"\bSUBJ_[A-Za-z0-9_.-]+\b",
            r"\b[A-Z]{2,}\d{3,}\b",
            r"[\w.+-]+@[\w-]+\.[\w.-]+",
            r"(?<!\d)\d{7,}(?!\d)",
        )
        for pattern in patterns:
            if re.search(pattern, value, re.IGNORECASE):
                raise UnsafeQueryError("Query contains a direct identity or identifier token")
