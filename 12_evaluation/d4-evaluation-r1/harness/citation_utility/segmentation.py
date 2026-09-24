"""Deterministic, review-friendly answer segmentation for D4.

The segmenter does no model inference and makes no support judgement.  It
returns answer spans with the original text intact; a later annotation step
can turn each span into a :class:`~harness.citation_utility.claims.ClaimRecord`.
Sentence and clause boundaries are intentionally conservative so a reviewer
can adjust them with an explicit SPLIT, MERGE, EDIT, or EXCLUDE trace.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .claims import (
    CLAIM_TYPES,
    DATA_CLASSIFICATION,
    ClaimRecord,
    ClaimType,
    TransformationTrace,
    _claim_id_for_answer,
    _span_dict,
    build_claim_record,
    citation_requirement_for,
)

try:
    from harness.foundation.hashing import canonical_sha256_tag
except ModuleNotFoundError:  # pragma: no cover - package-relative fallback
    from ..foundation.hashing import canonical_sha256_tag


# Keep punctuation in the preceding span.  Commas are deliberately excluded:
# splitting every comma makes Chinese explanatory sentences hard to review.
BOUNDARY_CHARACTERS = frozenset("。！？!?；;\r\n")
SCOPE_MARKERS = (
    "不构成",
    "不能据此",
    "仅供",
    "不等于",
    "不代表",
    "无法判断",
    "适用范围",
)
ACTION_MARKERS = (
    "建议",
    "可以",
    "不妨",
    "鼓励",
    "尝试",
    "保持",
    "联系",
    "安排",
)
GLUE_MARKERS = (
    "你好",
    "谢谢",
    "好的",
    "下面",
    "首先",
    "总的来说",
)


def infer_claim_type(text: str, *, default: str = "FACTUAL_VERIFIABLE") -> ClaimType:
    """Apply a small deterministic heuristic, leaving final review to people."""

    if default not in CLAIM_TYPES:
        raise ValueError(f"unsupported default claim type: {default!r}")
    if any(marker in text for marker in SCOPE_MARKERS):
        return "SCOPE_LIMITATION"
    if any(marker in text for marker in ACTION_MARKERS):
        return "EVIDENCE_GROUNDED_ACTION"
    if any(marker in text for marker in GLUE_MARKERS):
        return "CONVERSATIONAL_GLUE"
    return default  # type: ignore[return-value]


def _iter_spans(answer: str) -> Iterable[tuple[int, int]]:
    start = 0
    index = 0
    while index < len(answer):
        if answer[index] in BOUNDARY_CHARACTERS:
            end = index + 1
            while end < len(answer) and answer[end] in BOUNDARY_CHARACTERS:
                end += 1
            yield start, end
            start = end
            index = end
            continue
        index += 1
    if start < len(answer):
        yield start, len(answer)


def _trim_span(answer: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and answer[start].isspace():
        start += 1
    while end > start and answer[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    return start, end


def _answer_source_id(case_id: str) -> str:
    safe = "".join(char if char.isalnum() else "_" for char in case_id).strip("_")
    return f"ANSWER_{safe or 'CASE'}"


@dataclass(frozen=True)
class ClaimSegment:
    """An unjudged claim candidate with a stable answer span."""

    claim_id: str
    case_id: str
    original_answer: str
    span_start: int
    span_end: int
    text: str
    claim_type: str
    citation_required: bool
    citation_reason: str
    citation_policy_id: str
    ordinal: int
    traceability: tuple[TransformationTrace | Mapping[str, Any], ...] = ()
    data_classification: tuple[str, ...] = DATA_CLASSIFICATION
    content_hash: str | None = None

    def __post_init__(self) -> None:
        if not self.claim_id or not self.case_id:
            raise ValueError("claim_id and case_id are required")
        if not isinstance(self.original_answer, str) or not self.original_answer:
            raise ValueError("original_answer must be a non-empty string")
        if not isinstance(self.span_start, int) or not isinstance(self.span_end, int):
            raise TypeError("segment offsets must be integers")
        if self.span_start < 0 or self.span_end <= self.span_start:
            raise ValueError("segment must use a non-empty half-open span")
        if self.span_end > len(self.original_answer):
            raise ValueError("segment span exceeds original answer")
        if self.text != self.original_answer[self.span_start : self.span_end]:
            raise ValueError("segment text must equal its original answer span")
        if self.claim_type not in CLAIM_TYPES:
            raise ValueError(f"unsupported claim type: {self.claim_type!r}")
        policy = citation_requirement_for(
            self.claim_type,
            required=self.citation_required,
            policy_id=self.citation_policy_id,
            reason=self.citation_reason,
        )
        if self.citation_required != policy["required"]:
            raise ValueError("citation policy required value is not stable")
        if self.citation_reason != policy["reason"]:
            raise ValueError("citation policy reason is not stable")
        if self.citation_policy_id != policy["policy_id"]:
            raise ValueError("citation policy ID is not stable")
        if not isinstance(self.ordinal, int) or self.ordinal < 0:
            raise ValueError("ordinal must be a non-negative integer")
        if tuple(self.data_classification) != DATA_CLASSIFICATION:
            raise ValueError(
                "segment classification markers are fixed synthetic-only values"
            )
        object.__setattr__(self, "data_classification", DATA_CLASSIFICATION)
        traces = tuple(
            item
            if isinstance(item, TransformationTrace)
            else TransformationTrace(
                operation=item.get("operation"),
                source_claim_ids=item.get("source_claim_ids", ()),
                source_spans=item.get("source_spans", ()),
                result_span=item.get("result_span"),
                reason=item.get("reason"),
            )
            for item in self.traceability
        )
        if not traces:
            traces = (
                TransformationTrace(
                    operation="ORIGIN",
                    source_claim_ids=(),
                    source_spans=(_span_dict(self.span_start, self.span_end),),
                    result_span=_span_dict(self.span_start, self.span_end),
                    reason="Segment originates from the preserved answer span.",
                ),
            )
        object.__setattr__(self, "traceability", traces)
        expected_hash = canonical_sha256_tag(
            self._payload_dict(), self_field="content_hash"
        )
        if self.content_hash is not None and self.content_hash != expected_hash:
            raise ValueError("segment content_hash mismatch")
        object.__setattr__(self, "content_hash", expected_hash)

    def _payload_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "citation-support.v1",
            "record_type": "claim_segment",
            "claim_id": self.claim_id,
            "case_id": self.case_id,
            "original_answer": self.original_answer,
            "answer_span": _span_dict(self.span_start, self.span_end),
            "text": self.text,
            "claim_type": self.claim_type,
            "citation_required": self.citation_required,
            "citation_reason": self.citation_reason,
            "citation_policy_id": self.citation_policy_id,
            "ordinal": self.ordinal,
            "traceability": [trace.to_dict() for trace in self.traceability],
            "data_classification": list(self.data_classification),
        }

    def to_dict(self) -> dict[str, Any]:
        value = self._payload_dict()
        value["content_hash"] = self.content_hash
        return value

    def to_claim_record(self, **annotations: Any) -> ClaimRecord:
        """Promote this unjudged span to a separately annotated claim."""

        return build_claim_record(
            claim_id=self.claim_id,
            case_id=self.case_id,
            original_answer=self.original_answer,
            span_start=self.span_start,
            span_end=self.span_end,
            text=self.text,
            claim_type=self.claim_type,
            citation_required=self.citation_required,
            citation_reason=self.citation_reason,
            citation_policy_id=self.citation_policy_id,
            traceability=self.traceability,
            **annotations,
        )


def segment_answer(
    answer: str,
    *,
    case_id: str,
    claim_type_resolver: Callable[[str, int], str] | None = None,
    default_claim_type: str = "FACTUAL_VERIFIABLE",
    scope_citation_policy: Mapping[str, Any] | None = None,
) -> tuple[ClaimSegment, ...]:
    """Split an answer on conservative Chinese sentence boundaries.

    Offsets are measured against the exact input string.  Whitespace around a
    segment is left out of the span, while all substantive punctuation and
    characters remain unchanged.  No evidence or support label is inferred.
    Scope-limit claims require ``scope_citation_policy`` so source-dependent
    and ordinary nonsourced boundaries cannot be silently conflated.
    """

    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("answer must be a non-empty string")
    if not case_id or not isinstance(case_id, str):
        raise ValueError("case_id must be a non-empty string")
    if default_claim_type not in CLAIM_TYPES:
        raise ValueError(f"unsupported default claim type: {default_claim_type!r}")

    raw_spans = []
    for raw_start, raw_end in _iter_spans(answer):
        span = _trim_span(answer, raw_start, raw_end)
        if span is not None:
            raw_spans.append(span)
    if not raw_spans:
        return ()

    answer_source_id = _answer_source_id(case_id)
    segments: list[ClaimSegment] = []
    answer_span = _span_dict(0, len(answer))
    split_required = len(raw_spans) > 1
    for ordinal, (start, end) in enumerate(raw_spans):
        text = answer[start:end]
        claim_type = (
            claim_type_resolver(text, ordinal)
            if claim_type_resolver is not None
            else infer_claim_type(text, default=default_claim_type)
        )
        if claim_type not in CLAIM_TYPES:
            raise ValueError(
                f"claim_type_resolver returned unsupported type: {claim_type!r}"
            )
        if claim_type == "SCOPE_LIMITATION":
            if scope_citation_policy is None:
                raise ValueError(
                    "SCOPE_LIMITATION requires an explicit scope_citation_policy"
                )
            policy = citation_requirement_for(
                claim_type,
                policy_override=scope_citation_policy,
            )
        else:
            policy = citation_requirement_for(claim_type)
        traces: list[TransformationTrace] = [
            TransformationTrace(
                operation="ORIGIN",
                source_claim_ids=(),
                source_spans=(answer_span,),
                result_span=_span_dict(start, end),
                reason="The original answer is preserved for manual review.",
            )
        ]
        if split_required:
            traces.append(
                TransformationTrace(
                    operation="SPLIT",
                    source_claim_ids=(answer_source_id,),
                    source_spans=(answer_span,),
                    result_span=_span_dict(start, end),
                    reason="Deterministic sentence boundary split; reviewer may merge or edit.",
                )
            )
        segments.append(
            ClaimSegment(
                claim_id=_claim_id_for_answer(case_id, ordinal),
                case_id=case_id,
                original_answer=answer,
                span_start=start,
                span_end=end,
                text=text,
                claim_type=claim_type,
                citation_required=policy["required"],
                citation_reason=policy["reason"],
                citation_policy_id=policy["policy_id"],
                ordinal=ordinal,
                traceability=tuple(traces),
            )
        )
    return tuple(segments)


def segment_claims(
    answer: str,
    *,
    case_id: str,
    claim_type_resolver: Callable[[str, int], str] | None = None,
    default_claim_type: str = "FACTUAL_VERIFIABLE",
    scope_citation_policy: Mapping[str, Any] | None = None,
) -> tuple[ClaimSegment, ...]:
    """Compatibility alias for callers that name the stage "claim segmentation"."""

    return segment_answer(
        answer,
        case_id=case_id,
        claim_type_resolver=claim_type_resolver,
        default_claim_type=default_claim_type,
        scope_citation_policy=scope_citation_policy,
    )


def validate_segments(segments: Iterable[ClaimSegment]) -> tuple[ClaimSegment, ...]:
    """Check deterministic order, non-overlap, and exact text round-tripping."""

    materialized = tuple(segments)
    previous_end = -1
    seen_ids: set[str] = set()
    for index, segment in enumerate(materialized):
        if segment.ordinal != index:
            raise ValueError("segment ordinals must be contiguous and ordered")
        if segment.claim_id in seen_ids:
            raise ValueError(f"duplicate segment claim_id: {segment.claim_id}")
        seen_ids.add(segment.claim_id)
        if segment.span_start < previous_end:
            raise ValueError("segments must not overlap")
        previous_end = segment.span_end
    return materialized


__all__ = [
    "ACTION_MARKERS",
    "BOUNDARY_CHARACTERS",
    "GLUE_MARKERS",
    "SCOPE_MARKERS",
    "ClaimSegment",
    "infer_claim_type",
    "segment_answer",
    "segment_claims",
    "validate_segments",
]
