"""Rank-based fusion component."""

from __future__ import annotations

from collections.abc import Iterable

from ..domain import RetrievalHit


def rrf_fuse(
    ranked_lists: Iterable[Iterable[RetrievalHit]],
    *,
    k: int = 60,
    limit: int | None = None,
) -> list[RetrievalHit]:
    """Fuse ranked lists using Reciprocal Rank Fusion with zero-based ranks."""

    if k < 1:
        raise ValueError("RRF k must be positive")
    merged: dict[str, RetrievalHit] = {}
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, hit in enumerate(ranked):
            chunk_id = hit.chunk_id
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
            existing = merged.get(chunk_id)
            if existing is None:
                merged[chunk_id] = hit.clone(retriever="rrf", rank=0)
            else:
                merged[chunk_id] = existing.clone(
                    dense_score=_max_score(existing.dense_score, hit.dense_score),
                    sparse_score=_max_score(existing.sparse_score, hit.sparse_score),
                )
    ordered = sorted(merged.values(), key=lambda hit: (-scores[hit.chunk_id], hit.chunk_id))
    if limit is not None:
        ordered = ordered[:limit]
    return [hit.clone(rank=rank, fusion_score=scores[hit.chunk_id]) for rank, hit in enumerate(ordered)]


def _max_score(left: float | None, right: float | None) -> float | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)
