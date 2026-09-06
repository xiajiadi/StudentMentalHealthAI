"""Deterministic information-retrieval metrics."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any


def evaluate_ranking(
    retrieved_ids: Sequence[str],
    relevant_ids: Sequence[str],
    *,
    relevance_grades: Mapping[str, float] | None = None,
    latency_ms: float | None = None,
) -> dict[str, float | int | None]:
    relevant = set(str(item) for item in relevant_ids)
    grades = {str(key): float(value) for key, value in (relevance_grades or {}).items()}
    result: dict[str, float | int | None] = {}
    for k in (1, 3, 5):
        result[f"hit_at_{k}"] = float(bool(set(retrieved_ids[:k]).intersection(relevant))) if relevant else 0.0
    for k in (5, 10):
        result[f"recall_at_{k}"] = (len(set(retrieved_ids[:k]).intersection(relevant)) / len(relevant)) if relevant else 0.0
        result[f"ndcg_at_{k}"] = _ndcg(retrieved_ids[:k], relevant, grades)
    result["precision_at_5"] = (len(set(retrieved_ids[:5]).intersection(relevant)) / 5) if relevant else 0.0
    result["mrr"] = _mrr(retrieved_ids, relevant)
    result["latency_ms"] = latency_ms
    return result


def aggregate_metrics(per_query: Iterable[Mapping[str, Any]]) -> dict[str, float | int | None]:
    rows = list(per_query)
    numeric_names = [
        "hit_at_1",
        "hit_at_3",
        "hit_at_5",
        "recall_at_5",
        "recall_at_10",
        "precision_at_5",
        "mrr",
        "ndcg_at_5",
        "ndcg_at_10",
    ]
    result: dict[str, float | int | None] = {name: _mean([float(row[name]) for row in rows]) for name in numeric_names}
    latencies = sorted(float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None)
    result["query_count"] = len(rows)
    result["latency_p50_ms"] = _percentile(latencies, 0.50)
    result["latency_p95_ms"] = _percentile(latencies, 0.95)
    return result


def _mrr(retrieved_ids: Sequence[str], relevant: set[str]) -> float:
    if not relevant:
        return 0.0
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg(retrieved_ids: Sequence[str], relevant: set[str], grades: Mapping[str, float]) -> float:
    if not relevant:
        return 0.0
    gains = [grades.get(chunk_id, 1.0 if chunk_id in relevant else 0.0) for chunk_id in retrieved_ids]
    dcg = sum(((2**gain) - 1) / math.log2(rank + 2) for rank, gain in enumerate(gains))
    ideal = sorted((grades.get(chunk_id, 1.0) for chunk_id in relevant), reverse=True)[: len(retrieved_ids)]
    idcg = sum(((2**gain) - 1) / math.log2(rank + 2) for rank, gain in enumerate(ideal))
    return dcg / idcg if idcg else 0.0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] + weight * (values[upper] - values[lower])
