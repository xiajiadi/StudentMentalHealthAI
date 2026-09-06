"""Golden-query evaluation harness shared by benchmark scripts and tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

from .metrics import aggregate_metrics, evaluate_ranking


@dataclass(frozen=True)
class GoldenQuery:
    query_id: str
    query: str
    relevant_chunk_ids: tuple[str, ...]
    query_type: str
    role: str = "teacher"
    layer: str | None = None
    intent: str | None = None
    target_population: str = "K12学生"
    relevance_grades: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "GoldenQuery":
        required = {"query_id", "query", "relevant_chunk_ids", "query_type"}
        missing = required - set(value)
        if missing:
            raise ValueError(f"Golden query missing fields: {sorted(missing)}")
        ids = tuple(str(item) for item in value["relevant_chunk_ids"])
        grades_value = value.get("relevance_grades") or {}
        if not isinstance(grades_value, Mapping):
            raise ValueError("relevance_grades must be an object")
        return cls(
            query_id=str(value["query_id"]),
            query=str(value["query"]),
            relevant_chunk_ids=ids,
            query_type=str(value["query_type"]),
            role=str(value.get("role") or "teacher"),
            layer=str(value["layer"]) if value.get("layer") else None,
            intent=str(value["intent"]) if value.get("intent") else None,
            target_population=str(value.get("target_population") or "K12学生"),
            relevance_grades={str(key): float(val) for key, val in grades_value.items()},
        )


def load_golden_queries(path: str | Path) -> list[GoldenQuery]:
    queries: list[GoldenQuery] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError("Golden query line must be an object")
            queries.append(GoldenQuery.from_mapping(value))
    if not queries:
        raise ValueError("Golden dataset is empty")
    return queries


class EvaluationHarness:
    def __init__(self, queries: Sequence[GoldenQuery]) -> None:
        self.queries = list(queries)

    def evaluate(
        self,
        configuration: str,
        runner: Callable[[GoldenQuery], Sequence[str]],
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        per_query: list[dict[str, Any]] = []
        for query in self.queries:
            started = perf_counter()
            retrieved = [str(item) for item in runner(query)]
            latency_ms = (perf_counter() - started) * 1000
            metrics = evaluate_ranking(
                retrieved,
                query.relevant_chunk_ids,
                relevance_grades=query.relevance_grades,
                latency_ms=latency_ms,
            )
            per_query.append(
                {
                    "query_id": query.query_id,
                    "query": query.query,
                    "query_type": query.query_type,
                    "role": query.role,
                    "layer": query.layer,
                    "intent": query.intent,
                    "target_population": query.target_population,
                    "relevant_chunk_ids": list(query.relevant_chunk_ids),
                    "retrieved_chunk_ids": retrieved,
                    "metrics": metrics,
                }
            )
        metric_rows = [row["metrics"] for row in per_query]
        return {
            "configuration": configuration,
            "metadata": dict(metadata or {}),
            "dataset": {
                "query_count": len(self.queries),
                "query_type_distribution": _distribution(self.queries),
            },
            "metrics": aggregate_metrics(metric_rows),
            "per_query": per_query,
        }


def _distribution(queries: Sequence[GoldenQuery]) -> dict[str, int]:
    result: dict[str, int] = {}
    for query in queries:
        result[query.query_type] = result.get(query.query_type, 0) + 1
    return dict(sorted(result.items()))
