"""Evaluation-only human-review packet export for D4-3A.

The exporter consumes Claim Worker's serialized case records through their
public mapping shape (or an object exposing ``to_dict``).  It does not mutate
those records, call a model, or contact a network.  The packet is deliberately
review-pending: ``DRAFT``, ``HUMAN_REVIEW_REQUIRED``, and ``DISPUTED`` are
preserved, while an approval is never emitted as a packet status.

The packet includes the fixed five support labels, claim and evidence identity,
the independent population/role/purpose scope dimensions, draft rationales,
and blank reviewer decision fields.  Test approvals are retained only as an
explicit ``TEST_FIXTURE_SIMULATED_APPROVAL`` provenance marker and are never
represented as human gold.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

PACKET_SCHEMA_VERSION = "d4-human-review-packet.v1"
PACKET_VERSION = "d4-human-review-v1"
SIMULATED_APPROVAL_PROVENANCE = "TEST_FIXTURE_SIMULATED_APPROVAL"
DATA_CLASSIFICATION: tuple[str, ...] = (
    "SYNTHETIC_EVALUATION_ONLY",
    "NOT_D2_PUBLICATION",
    "NOT_PRODUCTION_KNOWLEDGE",
    "NOT_REAL_STUDENT_DATA",
    "NOT_PSYCHOLOGY_VALIDATION",
)
REVIEW_PENDING_STATES = frozenset({"DRAFT", "HUMAN_REVIEW_REQUIRED", "DISPUTED"})
SUPPORT_LABELS: tuple[str, ...] = (
    "SUPPORTS",
    "PARTIALLY_SUPPORTS",
    "UNSUPPORTED",
    "CONTRADICTS",
    "OUT_OF_SCOPE",
)
PROVENANCE_FIELDS: tuple[str, ...] = (
    "chunk_id",
    "document_id",
    "citation_id",
    "source_title",
    "source_organization",
    "locator",
    "content_hash",
)

LABEL_RUBRIC: dict[str, str] = {
    "SUPPORTS": "证据直接支持主张，且人口、角色和用途范围均适用。",
    "PARTIALLY_SUPPORTS": "证据只支持主张的一部分，或支持强度/范围需要收窄。",
    "UNSUPPORTED": "现有证据不能支持该主张，不能用引用身份代替支持判断。",
    "CONTRADICTS": "证据与主张存在明确冲突，需要保留冲突理由。",
    "OUT_OF_SCOPE": "文字可能相关，但人口、角色或用途适用范围不匹配。",
}


class ReviewPacketError(ValueError):
    """Raised when a source record cannot be safely represented as pending review."""


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _plain(to_dict())
    return value


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _as_records(value: Any) -> list[dict[str, Any]]:
    plain = _plain(value)
    if isinstance(plain, Mapping):
        cases = plain.get("cases")
        if isinstance(cases, Sequence) and not isinstance(
            cases, (str, bytes, bytearray)
        ):
            records = [item for item in cases if isinstance(item, Mapping)]
        elif plain.get("record_type") == "case" or "case_id" in plain:
            records = [plain]
        else:
            records = []
    elif isinstance(plain, Sequence) and not isinstance(plain, (str, bytes, bytearray)):
        records = [item for item in plain if isinstance(item, Mapping)]
    else:
        raise ReviewPacketError(
            "review packet input must be a case mapping or sequence"
        )
    if not records:
        raise ReviewPacketError("review packet requires at least one case")
    return [dict(record) for record in records]


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _review(value: Mapping[str, Any]) -> dict[str, Any]:
    raw = value.get("review")
    raw = dict(raw) if isinstance(raw, Mapping) else {}
    status = _text(raw.get("state", raw.get("status", value.get("review_status"))), "")
    status = status.strip().upper()
    source = (
        _text(raw.get("decision_source", value.get("review_provenance")), "")
        .strip()
        .upper()
    )
    simulated = (
        _text(raw.get("simulated_outcome", value.get("approval_provenance")), "")
        .strip()
        .upper()
    )
    if status in {"HUMAN_APPROVED", "APPROVED"}:
        if source == "TEST_SIMULATION" or simulated == SIMULATED_APPROVAL_PROVENANCE:
            status = "HUMAN_REVIEW_REQUIRED"
            test_fixture = {
                "simulated_approval": True,
                "provenance": SIMULATED_APPROVAL_PROVENANCE,
                "excluded_from_human_gold": True,
            }
        else:
            raise ReviewPacketError(
                "a human-approved source record cannot be emitted as a pending review packet"
            )
    else:
        test_fixture = None
        if simulated:
            test_fixture = {
                "simulated_approval": simulated == SIMULATED_APPROVAL_PROVENANCE,
                "provenance": simulated,
                "excluded_from_human_gold": True,
            }

    if status not in REVIEW_PENDING_STATES:
        # Missing and unknown status fail closed into a review-required packet.
        status = "HUMAN_REVIEW_REQUIRED"

    return {
        "status": status,
        "human_decision": None,
        "human_notes": "",
        "decision_source": "NONE",
        "reviewer_id": None,
        "reviewed_at": None,
        "evidence_ref": None,
        "human_gold": False,
        "test_fixture": test_fixture,
    }


def _scope(value: Mapping[str, Any]) -> dict[str, str]:
    target = value.get("target_scope")
    if not isinstance(target, Mapping):
        target = {}
    return {
        "population": _text(
            target.get("population", value.get("target_population")), "UNKNOWN"
        ),
        "role": _text(target.get("role", value.get("target_role")), "UNKNOWN"),
        "purpose": _text(target.get("purpose", value.get("target_purpose")), "UNKNOWN"),
    }


def _status_from_value(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("status", value.get("state"))
    status = _text(value, "UNKNOWN").strip().upper()
    aliases = {
        "APPLICABLE": "MATCH",
        "MATCHES": "MATCH",
        "IN_SCOPE": "MATCH",
        "MISMATCHED": "MISMATCH",
        "OUT_OF_SCOPE": "MISMATCH",
        "NOT_APPLICABLE": "MISMATCH",
        "UNKNOWN": "UNRESOLVED",
        "NOT_ASSESSED": "UNRESOLVED",
    }
    return aliases.get(status, status)


def _applicability(claim: Mapping[str, Any]) -> dict[str, Any]:
    nested = claim.get("applicability")
    nested = nested if isinstance(nested, Mapping) else {}
    result: dict[str, Any] = {}
    for dimension, direct_key in (
        ("population", "population_applicability"),
        ("role", "role_applicability"),
        ("purpose", "purpose_applicability"),
    ):
        raw = nested.get(dimension, claim.get(direct_key, "UNKNOWN"))
        if isinstance(raw, Mapping):
            result[dimension] = {
                "status": _status_from_value(raw),
                "reason": _text(raw.get("reason")),
                "expected_scope": raw.get("expected_scope"),
                "evidence_scope": list(raw.get("evidence_scope", ())),
            }
        else:
            result[dimension] = {
                "status": _status_from_value(raw),
                "reason": "Applicability source did not provide a structured reason.",
                "expected_scope": None,
                "evidence_scope": [],
            }
    return result


def _evidence_identity(evidence: Mapping[str, Any]) -> dict[str, Any]:
    review_state = (
        _text(evidence.get("review_state"), "HUMAN_REVIEW_REQUIRED").strip().upper()
    )
    if review_state in {"HUMAN_APPROVED", "APPROVED"}:
        review_state = "HUMAN_REVIEW_REQUIRED"
    return {
        "chunk_id": _text(evidence.get("chunk_id")),
        "document_id": _text(evidence.get("document_id")),
        "citation_id": _text(evidence.get("citation_id")),
        "source_title": _text(evidence.get("source_title")),
        "source_organization": _text(evidence.get("source_organization")),
        "locator": _text(evidence.get("locator")),
        "text": _text(evidence.get("text")),
        "population_scope": list(evidence.get("population_scope", ())),
        "role_scope": list(evidence.get("role_scope", ())),
        "purpose_scope": list(evidence.get("purpose_scope", ())),
        "review_state": review_state,
        "human_gold": False,
        "content_hash": _text(evidence.get("content_hash")),
        "data_classification": list(DATA_CLASSIFICATION),
    }


def _citation_identity(
    cited_ids: Sequence[str],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    valid_ids: list[str] = []
    unknown_ids: list[str] = []
    missing_fields: dict[str, list[str]] = {}
    for chunk_id in cited_ids:
        evidence = evidence_by_id.get(chunk_id)
        if evidence is None:
            unknown_ids.append(chunk_id)
            continue
        missing = [
            field
            for field in PROVENANCE_FIELDS
            if not _text(evidence.get(field)).strip()
        ]
        if missing:
            unknown_ids.append(chunk_id)
            missing_fields[chunk_id] = missing
        else:
            valid_ids.append(chunk_id)
    if not cited_ids:
        status = "NONE"
    elif len(valid_ids) == len(cited_ids):
        status = "VALID"
    else:
        status = "UNKNOWN"
    return {
        "status": status,
        "identity_source": "CASE_EVIDENCE_MEMBERSHIP",
        "cited_chunk_ids": list(cited_ids),
        "valid_chunk_ids": valid_ids,
        "unknown_chunk_ids": unknown_ids,
        "provenance_complete": status == "VALID",
        "missing_provenance_fields": missing_fields,
    }


def _claim_label(claim: Mapping[str, Any]) -> str:
    label = claim.get("support_label", claim.get("textual_entailment"))
    label = _text(label, "UNSUPPORTED").strip().upper().replace("-", "_")
    applicability = _applicability(claim)
    if label in {"SUPPORTS", "PARTIALLY_SUPPORTS"} and any(
        item.get("status") == "MISMATCH" for item in applicability.values()
    ):
        return "OUT_OF_SCOPE"
    if label not in SUPPORT_LABELS:
        return "UNSUPPORTED"
    return label


def _draft_rationale(label: str, claim: Mapping[str, Any]) -> str:
    cited = list(claim.get("cited_chunk_ids", ()))
    applicability = _applicability(claim)
    mismatches = [
        dimension
        for dimension, item in applicability.items()
        if item.get("status") == "MISMATCH"
    ]
    if label == "SUPPORTS":
        return (
            "草拟判断：引用证据与主张方向一致；请复核文字支持强度及三个适用范围维度。"
        )
    if label == "PARTIALLY_SUPPORTS":
        return "草拟判断：引用证据只覆盖主张的一部分；请收窄主张或补充可核验证据。"
    if label == "UNSUPPORTED":
        return (
            "草拟判断：当前引用不能支持主张；请确认是否应删去主张或转为明确不确定性。"
        )
    if label == "CONTRADICTS":
        return "草拟判断：引用内容与主张存在冲突；请保留冲突依据并决定如何改写。"
    if mismatches:
        return (
            "草拟判断：适用范围在 "
            + ", ".join(mismatches)
            + " 维度不匹配；文字相关性不能替代范围适用性。"
        )
    if not cited:
        return "草拟判断：主张需要引用但当前未绑定证据；请补充或标记为不支持。"
    return "草拟判断：请由指定审核人确认主张、引用和范围关系。"


def _claim_packet(
    claim: Mapping[str, Any],
    evidence_by_id: Mapping[str, Mapping[str, Any]],
    case_scope: Mapping[str, str],
) -> dict[str, Any]:
    claim_id = _text(claim.get("claim_id", claim.get("id")), "UNKNOWN_CLAIM")
    cited_ids = _unique(claim.get("cited_chunk_ids", ()))
    cited_evidence: list[dict[str, Any]] = []
    for chunk_id in cited_ids:
        if chunk_id in evidence_by_id:
            cited_evidence.append(_evidence_identity(evidence_by_id[chunk_id]))
        else:
            cited_evidence.append(
                {
                    "chunk_id": chunk_id,
                    "missing_from_case_evidence": True,
                    "data_classification": list(DATA_CLASSIFICATION),
                }
            )
    label = _claim_label(claim)
    return {
        "claim_id": claim_id,
        "case_id": _text(claim.get("case_id")),
        "text": _text(claim.get("text")),
        "content_hash": claim.get("content_hash"),
        "answer_span": dict(claim.get("answer_span", {})),
        "traceability": [
            dict(item)
            for item in claim.get("traceability", ())
            if isinstance(item, Mapping)
        ],
        "claim_type": _text(claim.get("claim_type")),
        "citation_required": bool(
            claim.get("citation_required", claim.get("required_citation", False))
        ),
        "citation_reason": _text(claim.get("citation_reason")),
        "cited_chunk_ids": cited_ids,
        "cited_evidence": cited_evidence,
        "citation_identity": _citation_identity(cited_ids, evidence_by_id),
        "textual_entailment": _text(
            claim.get("textual_entailment", claim.get("support_label")),
            "UNKNOWN",
        )
        .strip()
        .upper(),
        "support_label": label,
        "annotation_status": "DRAFT",
        "human_gold": False,
        "applicability": _applicability(claim),
        "case_scope": dict(case_scope),
        "contradiction": dict(claim.get("contradiction", {}))
        if isinstance(claim.get("contradiction"), Mapping)
        else {"flag": label == "CONTRADICTS", "reason": None},
        "draft_rationale": _draft_rationale(label, claim),
        "review": _review(claim),
        "data_classification": list(DATA_CLASSIFICATION),
    }


def _case_packet(case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = _text(case.get("case_id", case.get("id")), "UNKNOWN_CASE")
    case_scope = _scope(case)
    evidence = [item for item in case.get("evidence", ()) if isinstance(item, Mapping)]
    evidence_by_id = {
        _text(item.get("chunk_id")): item
        for item in evidence
        if _text(item.get("chunk_id"))
    }
    claims = [item for item in case.get("claims", ()) if isinstance(item, Mapping)]
    claim_packets = sorted(
        (_claim_packet(claim, evidence_by_id, case_scope) for claim in claims),
        key=lambda item: item["claim_id"],
    )
    evidence_packets = sorted(
        (_evidence_identity(item) for item in evidence),
        key=lambda item: item["chunk_id"],
    )
    review = _review(case)
    transcript = [
        {
            "turn_id": "TURN_SYNTHETIC_OUTPUT_001",
            "role": "system_output",
            "content": _text(case.get("original_answer")),
        }
    ]
    return {
        "case_id": case_id,
        "content_hash": case.get("content_hash"),
        "synthetic_transcript": transcript,
        "system_output": _text(case.get("original_answer")),
        "target_scope": case_scope,
        "scope_dimensions": {
            "population": case_scope["population"],
            "role": case_scope["role"],
            "purpose": case_scope["purpose"],
        },
        "citations": evidence_packets,
        "claims": claim_packets,
        "support_labels": [
            {"claim_id": item["claim_id"], "label": item["support_label"]}
            for item in claim_packets
        ],
        "allowed_support_labels": list(SUPPORT_LABELS),
        "behavior_flags": [],
        "rubric": {
            "label_legend": dict(LABEL_RUBRIC),
            "review_instruction": "分别判断文本支持、适用范围和冲突，不把引用身份自动视为支持。",
        },
        "grader_result": {
            "source": "DETERMINISTIC_SYNTHETIC_FIXTURE",
            "human_gold": False,
            "status": "PENDING_REVIEW",
        },
        "draft_rationale": "请逐条复核主张、证据身份、文本支持和 population/role/purpose 适用范围。",
        "review": review,
        "reviewer_fields": {
            "status": review["status"],
            "decision": None,
            "notes": "",
            "reviewer_id": None,
            "reviewed_at": None,
            "evidence_ref": None,
        },
        "decision": None,
        "notes": "",
        "data_classification": list(DATA_CLASSIFICATION),
    }


def _answerability_review(case: Mapping[str, Any]) -> dict[str, Any]:
    human_gold = case.get("human_gold")
    if not isinstance(human_gold, Mapping):
        return _review(case)
    status = _text(human_gold.get("status"), "HUMAN_REVIEW_REQUIRED").strip().upper()
    provenance = _text(human_gold.get("provenance"), "").strip().upper()
    if status == "HUMAN_APPROVED":
        if provenance == SIMULATED_APPROVAL_PROVENANCE:
            status = "HUMAN_REVIEW_REQUIRED"
            fixture = {
                "simulated_approval": True,
                "provenance": SIMULATED_APPROVAL_PROVENANCE,
                "excluded_from_human_gold": True,
            }
        else:
            raise ReviewPacketError(
                "a human-approved answerability case cannot be emitted as a review packet"
            )
    else:
        fixture = None
    if status not in REVIEW_PENDING_STATES:
        status = "HUMAN_REVIEW_REQUIRED"
    return {
        "status": status,
        "human_decision": None,
        "human_notes": "",
        "decision_source": "NONE",
        "reviewer_id": None,
        "reviewed_at": None,
        "evidence_ref": None,
        "human_gold": False,
        "test_fixture": fixture,
    }


def _answerability_packet(case: Mapping[str, Any]) -> dict[str, Any]:
    review = _answerability_review(case)
    expected = _text(case.get("expected_response_class"), "UNKNOWN").strip().upper()
    required_evidence_ids = _unique(case.get("required_evidence_ids", ()))
    available_inapplicable = _unique(
        case.get("available_but_inapplicable_evidence_ids", ())
    )
    return {
        "case_id": _text(case.get("case_id", case.get("id")), "UNKNOWN_CASE"),
        "pair_id": _text(case.get("pair_id")),
        "paired_case_id": _text(case.get("paired_case_id")),
        "request": _text(case.get("request")),
        "target_scope": dict(case.get("target_scope", {}))
        if isinstance(case.get("target_scope"), Mapping)
        else {},
        "evidence_bindings": [
            dict(item)
            for item in case.get("evidence_bindings", ())
            if isinstance(item, Mapping)
        ],
        "expected_response_class": expected,
        "class_label_status": "DRAFT",
        "human_gold": False,
        "mismatch_dimension": case.get("mismatch_dimension"),
        "required_evidence_ids": required_evidence_ids,
        "available_but_inapplicable_evidence_ids": available_inapplicable,
        "minimum_useful_behavior": _text(case.get("minimum_useful_behavior")),
        "minimum_useful_content_expectation": _text(
            case.get("minimum_useful_content_expectation")
        ),
        "prohibited_refusal_outcomes": list(
            case.get("prohibited_refusal_outcomes", ())
        ),
        "expected_rationale": _text(case.get("expected_rationale")),
        "human_review": review,
        "human_decision": None,
        "human_notes": "",
        "data_classification": list(DATA_CLASSIFICATION),
    }


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _derived_source_hash(value: Any, records: Sequence[Mapping[str, Any]]) -> str:
    plain = _plain(value)
    if isinstance(plain, Mapping):
        supplied = plain.get("dataset_hash")
        if isinstance(supplied, str) and supplied.strip():
            return supplied.strip()
        payload: Any = dict(plain)
    else:
        payload = {"cases": [dict(item) for item in records]}

    def stable_case(raw_case: Mapping[str, Any]) -> dict[str, Any]:
        case = dict(raw_case)
        for field_name, id_name in (
            ("claims", "claim_id"),
            ("evidence", "chunk_id"),
            ("citation_identity", "claim_id"),
        ):
            items = case.get(field_name)
            if isinstance(items, list) and all(
                isinstance(item, Mapping) for item in items
            ):
                case[field_name] = sorted(
                    items,
                    key=lambda item: _text(item.get(id_name)),
                )
        return case

    if isinstance(payload, Mapping) and (
        payload.get("record_type") == "case" or "case_id" in payload
    ):
        payload = stable_case(payload)
    if isinstance(payload, Mapping) and isinstance(payload.get("cases"), list):
        ordered_cases: list[dict[str, Any]] = []
        for raw_case in payload["cases"]:
            if not isinstance(raw_case, Mapping):
                ordered_cases.append(raw_case)
                continue
            ordered_cases.append(stable_case(raw_case))
        payload = dict(payload)
        payload["cases"] = sorted(
            ordered_cases,
            key=lambda item: (
                _text(item.get("case_id")) if isinstance(item, Mapping) else ""
            ),
        )
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _dataset_binding(
    value: Any,
    records: Sequence[Mapping[str, Any]],
    *,
    default_id: str,
    default_version: str,
    explicit_hash: str | None,
) -> dict[str, str]:
    plain = _plain(value)
    if isinstance(plain, Mapping):
        dataset_id = _text(plain.get("dataset_id"), default_id)
        dataset_version = _text(
            plain.get("dataset_version", plain.get("version")), default_version
        )
    else:
        dataset_id = default_id
        dataset_version = default_version
    return {
        "id": dataset_id,
        "version": dataset_version,
        "hash": explicit_hash or _derived_source_hash(value, records),
    }


def _markdown_inline(value: Any) -> str:
    return (
        _text(value)
        .replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("|", "\\|")
        .replace("\r", "")
        .replace("\n", " ")
    )


def _markdown_block(value: Any) -> str:
    text = _text(value).replace("\r", "")
    return text.replace("```", "``\\`")


def packet_hash(packet: Mapping[str, Any]) -> str:
    """Hash packet content excluding its self-reported ``packet_hash`` field."""

    payload = dict(_plain(packet))
    payload.pop("packet_hash", None)
    return "sha256:" + hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def verify_packet_hash(packet: Mapping[str, Any]) -> bool:
    supplied = packet.get("packet_hash")
    return isinstance(supplied, str) and supplied == packet_hash(packet)


def build_review_packet(
    value: Any,
    *,
    packet_id: str = "D4-PACKET-CITATION-UTILITY-V1",
    source_dataset_id: str = "d4-citation-support",
    source_dataset_version: str = "cases.v1",
    answerability_cases: Any = None,
    source_dataset_hash: str | None = None,
    answerability_dataset_hash: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic pending human-review packet."""

    source_value = value
    answerability_value = answerability_cases
    if isinstance(value, Mapping):
        source_value = value.get("citation_cases", value)
        if answerability_value is None:
            answerability_value = value.get("answerability_cases")
    cases = sorted(
        _as_records(source_value), key=lambda item: _text(item.get("case_id"))
    )
    answerability_records: list[dict[str, Any]] = []
    if answerability_value is not None:
        answerability_records = sorted(
            _as_records(answerability_value),
            key=lambda item: _text(item.get("case_id")),
        )
    citation_binding = _dataset_binding(
        source_value,
        cases,
        default_id=source_dataset_id,
        default_version=source_dataset_version,
        explicit_hash=source_dataset_hash,
    )
    answerability_binding = None
    if answerability_value is not None:
        answerability_binding = _dataset_binding(
            answerability_value,
            answerability_records,
            default_id="d4-answerability-neutral-educational",
            default_version="v1",
            explicit_hash=answerability_dataset_hash,
        )
    packet: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "version": PACKET_VERSION,
        "packet_id": packet_id,
        "source_dataset_id": citation_binding["id"],
        "source_dataset_version": citation_binding["version"],
        "source_dataset_hash": citation_binding["hash"],
        "source_binding": {
            "citation_support": citation_binding,
            "answerability": answerability_binding,
        },
        "review_status": "HUMAN_REVIEW_REQUIRED",
        "annotation_status": "DRAFT",
        "human_gold": False,
        "label_legend": [
            {"label": label, "meaning": LABEL_RUBRIC[label]} for label in SUPPORT_LABELS
        ],
        "data_classification": list(DATA_CLASSIFICATION),
        "cases": [_case_packet(case) for case in cases],
        "answerability_cases": [
            _answerability_packet(case) for case in answerability_records
        ],
        "limitations": [
            "synthetic_only",
            "evaluation_only",
            "human_decisions_and_notes_are_blank",
            "packet_does_not_promote_D2_content_or_production_knowledge",
        ],
    }
    packet["packet_hash"] = packet_hash(packet)
    return packet


def packet_to_json(packet: Mapping[str, Any]) -> str:
    """Serialize a packet canonically for stable storage and hashing."""

    if not verify_packet_hash(packet):
        raise ReviewPacketError("cannot serialize a packet with an invalid packet_hash")
    return _canonical(dict(_plain(packet))) + "\n"


def packet_from_json(value: str) -> dict[str, Any]:
    """Parse and hash-check a serialized packet."""

    try:
        packet = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ReviewPacketError("review packet JSON is invalid") from exc
    if not isinstance(packet, Mapping) or not verify_packet_hash(packet):
        raise ReviewPacketError("review packet hash is missing or invalid")
    if packet.get("review_status") == "HUMAN_APPROVED":
        raise ReviewPacketError("review packet cannot contain HUMAN_APPROVED")
    return dict(packet)


def packet_to_markdown(packet: Mapping[str, Any]) -> str:
    """Render a deterministic, reviewer-facing Markdown packet."""

    if not verify_packet_hash(packet):
        raise ReviewPacketError("cannot render a packet with an invalid packet_hash")
    lines = [
        f"# D4-3A Human Review Packet: {packet['packet_id']}",
        "",
        f"- Version: `{packet['version']}`",
        f"- Review status: `{packet['review_status']}`",
        f"- Human gold: `{str(packet['human_gold']).lower()}`",
        f"- Packet hash: `{packet['packet_hash']}`",
        f"- Citation source hash: `{packet['source_binding']['citation_support']['hash']}`",
        f"- Answerability source hash: `{packet['source_binding']['answerability']['hash'] if packet['source_binding']['answerability'] else '(not included)'}`",
        "- Data classification: "
        + ", ".join(f"`{item}`" for item in packet["data_classification"]),
        "",
        "## Support label rubric",
        "",
        "| Label | Draft meaning |",
        "| --- | --- |",
    ]
    for item in packet["label_legend"]:
        lines.append(f"| `{item['label']}` | {item['meaning']} |")
    for case in packet["cases"]:
        lines.extend(
            [
                "",
                f"## Case `{case['case_id']}`",
                "",
                f"- Review status: `{case['review']['status']}`",
                f"- Scope: population=`{case['scope_dimensions']['population']}`, role=`{case['scope_dimensions']['role']}`, purpose=`{case['scope_dimensions']['purpose']}`",
                f"- Draft rationale: {_markdown_inline(case['draft_rationale'])}",
                f"- Human decision: `{_markdown_inline(case['decision']) if case['decision'] is not None else '(blank)'}`",
                f"- Human notes: {case['notes'] or '(blank)'}",
                "",
                "### Synthetic output",
                "",
                _markdown_block(case["system_output"]),
                "",
                "### Evidence identity",
                "",
                "| Chunk | Document | Citation | Locator |",
                "| --- | --- | --- | --- |",
            ]
        )
        for evidence in case["citations"]:
            lines.append(
                f"| `{evidence.get('chunk_id', '')}` | `{evidence.get('document_id', '')}` | "
                f"`{evidence.get('citation_id', '')}` | `{evidence.get('locator', '')}` |"
            )
        lines.extend(["", "### Evidence text", ""])
        for evidence in case["citations"]:
            lines.extend(
                [
                    f"#### `{_markdown_inline(evidence.get('chunk_id', ''))}`",
                    "",
                    "```text",
                    _markdown_block(evidence.get("text", "")),
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "",
                "### Claims",
                "",
                "| Claim | Textual entailment | Final label | Citation identity | Citation required | Draft rationale |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for claim in case["claims"]:
            lines.append(
                f"| `{claim['claim_id']}` | `{claim['textual_entailment']}` | "
                f"`{claim['support_label']}` | `{claim['citation_identity']['status']}` | "
                f"`{str(claim['citation_required']).lower()}` | {_markdown_inline(claim['draft_rationale'])} |"
            )
        lines.extend(["", "### Claim text and spans", ""])
        for claim in case["claims"]:
            lines.extend(
                [
                    f"#### `{_markdown_inline(claim['claim_id'])}`",
                    "",
                    f"- Textual entailment: `{_markdown_inline(claim['textual_entailment'])}`",
                    f"- Final label: `{_markdown_inline(claim['support_label'])}`",
                    f"- Answer span: `{_markdown_inline(json.dumps(claim['answer_span'], ensure_ascii=False, sort_keys=True))}`",
                    f"- Traceability: `{_markdown_inline(json.dumps([{'operation': item.get('operation'), 'source_claim_ids': item.get('source_claim_ids', [])} for item in claim.get('traceability', [])], ensure_ascii=False, sort_keys=True))}`",
                    "",
                    "```text",
                    _markdown_block(claim.get("text", "")),
                    "```",
                    "",
                ]
            )
        lines.extend(
            [
                "",
                "### Reviewer fields",
                "",
                "- Status: `" + case["reviewer_fields"]["status"] + "`",
                "- Decision: (blank)",
                "- Notes: (blank)",
            ]
        )
    if packet.get("answerability_cases"):
        lines.extend(["", "## Answerability controls", ""])
        for case in packet["answerability_cases"]:
            lines.extend(
                [
                    f"### Answerability case `{case['case_id']}`",
                    "",
                    f"- Pair: `{case['pair_id']}` ↔ `{case['paired_case_id']}`",
                    f"- Expected response class: `{case['expected_response_class']}`",
                    "#### Synthetic request",
                    "",
                    _markdown_block(case["request"]),
                    "",
                    f"- Mismatch dimension: `{_markdown_inline(case['mismatch_dimension']) if case['mismatch_dimension'] is not None else '(none)'}`",
                    f"- Target scope: population=`{_markdown_inline(case['target_scope'].get('population', 'UNKNOWN'))}`, role=`{_markdown_inline(case['target_scope'].get('role', 'UNKNOWN'))}`, purpose=`{_markdown_inline(case['target_scope'].get('purpose', 'UNKNOWN'))}`",
                    "- Evidence bindings: "
                    + (
                        "; ".join(
                            f"`{_markdown_inline(item.get('evidence_id', ''))}` "
                            f"population={_markdown_inline(','.join(item.get('population_scope', [])))} "
                            f"role={_markdown_inline(','.join(item.get('role_scope', [])))} "
                            f"purpose={_markdown_inline(','.join(item.get('purpose_scope', [])))}"
                            for item in case.get("evidence_bindings", [])
                        )
                        or "(none)"
                    ),
                    f"- Required evidence IDs: {', '.join(f'`{item}`' for item in case['required_evidence_ids']) or '(none)'}",
                    f"- Minimum useful behavior: `{case['minimum_useful_behavior']}`",
                    f"- Minimum useful content: {_markdown_inline(case['minimum_useful_content_expectation'])}",
                    f"- Prohibited outcomes: {', '.join(f'`{item}`' for item in case['prohibited_refusal_outcomes'])}",
                    f"- Draft rationale: {_markdown_inline(case['expected_rationale'])}",
                    f"- Review status: `{case['human_review']['status']}`",
                    "- Human decision: (blank)",
                    "- Human notes: (blank)",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def round_trip_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Serialize and parse a packet while re-checking its deterministic hash."""

    return packet_from_json(packet_to_json(packet))


# Friendly aliases for integration callers.
export_review_packet = build_review_packet
render_review_packet_markdown = packet_to_markdown
serialize_review_packet = packet_to_json
load_review_packet = packet_from_json
review_packet_hash = packet_hash


__all__ = [
    "DATA_CLASSIFICATION",
    "LABEL_RUBRIC",
    "PACKET_SCHEMA_VERSION",
    "PACKET_VERSION",
    "PROVENANCE_FIELDS",
    "SIMULATED_APPROVAL_PROVENANCE",
    "SUPPORT_LABELS",
    "ReviewPacketError",
    "build_review_packet",
    "export_review_packet",
    "load_review_packet",
    "packet_from_json",
    "packet_hash",
    "packet_to_json",
    "packet_to_markdown",
    "render_review_packet_markdown",
    "review_packet_hash",
    "round_trip_packet",
    "serialize_review_packet",
    "verify_packet_hash",
]
