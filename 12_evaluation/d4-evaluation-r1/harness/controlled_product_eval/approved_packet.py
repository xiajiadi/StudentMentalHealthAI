"""Strict, evaluation-only consumer for the immutable D4-3A Human Gold packet.

This intentionally does not call ``packet_from_json``: that public exporter
parser rejects HUMAN_APPROVED packets by design. The consumer verifies the
approved source in place and never normalizes or writes it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

try:
    from harness.citation_utility.review_packet import (
        PACKET_SCHEMA_VERSION,
        PACKET_VERSION,
        packet_hash as canonical_packet_hash,
        verify_packet_hash,
    )
    from harness.foundation.hashing import canonical_sha256_tag
except ModuleNotFoundError:  # pragma: no cover - package-relative import mode
    from ..citation_utility.review_packet import (
        PACKET_SCHEMA_VERSION,
        PACKET_VERSION,
        packet_hash as canonical_packet_hash,
        verify_packet_hash,
    )
    from ..foundation.hashing import canonical_sha256_tag


APPROVED_PACKET_ID = "D4-PACKET-SLICE3A-CITATION-UTILITY-R1"
APPROVED_PACKET_HASH = (
    "sha256:cfbe640300c2cbfbfe9616bb20b10b6ed80e7ee1e15169aadf2052ac8de107c6"
)
PREPUBLICATION_PACKET_HASH = (
    "sha256:8b2e83469888fc195dbf9baea1389f97ab5dcaa0c48e83c9c5ae1efcf25cbe67"
)
APPROVAL_EVIDENCE_REF = "D4_SLICE3A_HUMAN_GOLD_APPROVAL.md"
APPROVAL_REVIEWER_ID = "PROJECT_OWNER_HUMAN_REVIEWER"
APPROVAL_REVIEWED_AT = "2026-09-24T19:46:59+08:00"
APPROVED_CITATION_CASES = 7
APPROVED_ANSWERABILITY_CASES = 12
EXPECTED_CLASS_DISTRIBUTION = {
    "MUST_ANSWER": 5,
    "SHOULD_ABSTAIN": 4,
    "SHOULD_ANSWER": 1,
    "MUST_ROUTE": 1,
    "MUST_DENY": 1,
}
EXPECTED_SOURCE_BINDING = {
    "citation_support": {
        "id": "D4SUP_DEV_SYNTHETIC_V1",
        "version": "v1",
        "hash": "sha256:4ff97838c8ea641651898b2d8ed01616bbcc1a37064511cd1caad9d624771d42",
    },
    "answerability": {
        "id": "d4-answerability-neutral-educational",
        "version": "v1",
        "hash": "sha256:c522f016646ff420a8973c652d610e505e8215b69560a1a5827c0a8a03c3af27",
    },
}
EXPECTED_DATA_CLASSIFICATION = (
    "SYNTHETIC_EVALUATION_ONLY",
    "NOT_D2_PUBLICATION",
    "NOT_PRODUCTION_KNOWLEDGE",
    "NOT_REAL_STUDENT_DATA",
    "NOT_PSYCHOLOGY_VALIDATION",
)


class ApprovedPacketError(ValueError):
    """The immutable approved packet is missing, invalid, or has drifted."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ApprovedPacketError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def thaw_json(value: Any) -> Any:
    """Return an ordinary JSON-shaped copy of a frozen packet value."""

    if isinstance(value, Mapping):
        return {key: thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(item) for item in value]
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ApprovedPacketError(message)


def _validate_review_object(review: Any, *, case_id: str, label: str) -> None:
    _require(isinstance(review, Mapping), f"{case_id}: {label} review is missing")
    assert isinstance(review, Mapping)
    expected_fields = {
        "decision_source": "HUMAN_REVIEWER",
        "evidence_ref": APPROVAL_EVIDENCE_REF,
        "human_decision": "APPROVED",
        "human_gold": True,
        "reviewed_at": APPROVAL_REVIEWED_AT,
        "reviewer_id": APPROVAL_REVIEWER_ID,
        "status": "HUMAN_APPROVED",
        "test_fixture": None,
    }
    for field, expected in expected_fields.items():
        _require(review.get(field) == expected, f"{case_id}: invalid {label} approval field {field}")


def _validate_case_review(case: Mapping[str, Any], *, label: str) -> None:
    case_id = case.get("case_id")
    _require(isinstance(case_id, str) and bool(case_id), f"{label} case has no case_id")
    if label == "citation":
        _require(case.get("decision") == "APPROVED", f"{case_id}: citation decision is not approved")
        _validate_review_object(case.get("review"), case_id=case_id, label="case")
        reviewer_fields = case.get("reviewer_fields")
        _require(isinstance(reviewer_fields, Mapping), f"{case_id}: reviewer_fields are missing")
        assert isinstance(reviewer_fields, Mapping)
        expected_reviewer_fields = {
            "decision": "APPROVED",
            "evidence_ref": APPROVAL_EVIDENCE_REF,
            "notes": "",
            "reviewed_at": APPROVAL_REVIEWED_AT,
            "reviewer_id": APPROVAL_REVIEWER_ID,
            "status": "HUMAN_APPROVED",
        }
        for field, expected in expected_reviewer_fields.items():
            _require(reviewer_fields.get(field) == expected, f"{case_id}: invalid reviewer_fields.{field}")
        claims = case.get("claims")
        _require(isinstance(claims, list) and bool(claims), f"{case_id}: approved claims are missing")
        label_by_claim = {
            item.get("claim_id"): item.get("label")
            for item in case.get("support_labels", ())
            if isinstance(item, Mapping)
        }
        for claim in claims:
            _require(isinstance(claim, Mapping), f"{case_id}: claim annotation must be an object")
            assert isinstance(claim, Mapping)
            claim_id = claim.get("claim_id")
            _require(claim.get("annotation_status") == "HUMAN_APPROVED", f"{case_id}: claim annotation is not HUMAN_APPROVED")
            _require(claim.get("human_gold") is True, f"{case_id}: claim human_gold is not true")
            _require(claim.get("support_label") in {"SUPPORTS", "PARTIALLY_SUPPORTS", "UNSUPPORTED", "CONTRADICTS", "OUT_OF_SCOPE"}, f"{case_id}: approved support label is invalid")
            _require(label_by_claim.get(claim_id) == claim.get("support_label"), f"{case_id}: support label index differs from the approved claim")
            _validate_review_object(claim.get("review"), case_id=f"{case_id}/{claim_id}", label="claim")
        return

    _require(case.get("class_label_status") == "HUMAN_APPROVED", f"{case_id}: class label is not HUMAN_APPROVED")
    _require(case.get("human_decision") == "APPROVED", f"{case_id}: human decision is not APPROVED")
    _require(case.get("human_gold") is True, f"{case_id}: human_gold is not true")
    _validate_review_object(case.get("human_review"), case_id=case_id, label="answerability")


@dataclass(frozen=True, slots=True)
class ApprovedPacket:
    """Read-only view retaining the exact approved packet and provenance."""

    path: Path
    packet_id: str
    packet_hash: str
    raw_file_sha256: str
    payload: Mapping[str, Any]
    citation_cases: tuple[Mapping[str, Any], ...]
    answerability_cases: tuple[Mapping[str, Any], ...]
    source_provenance: Mapping[str, Any]

    def verify_unchanged(self) -> None:
        """Fail if the source file changed after it was loaded."""

        try:
            current = self.path.read_bytes()
        except OSError as exc:
            raise ApprovedPacketError(f"cannot re-read approved packet: {exc}") from exc
        actual = hashlib.sha256(current).hexdigest()
        if actual != self.raw_file_sha256:
            raise ApprovedPacketError("approved Human Gold source file changed after load")
        if not verify_packet_hash(self.payload):
            raise ApprovedPacketError("approved packet canonical hash changed after load")

    def provenance_dict(self) -> dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "packet_hash": self.packet_hash,
            "packet_file_sha256": self.raw_file_sha256,
            "source_binding": thaw_json(self.source_provenance),
        }


def _validate_payload(value: Any) -> dict[str, Any]:
    _require(isinstance(value, dict), "approved packet root must be a JSON object")
    packet: dict[str, Any] = value
    _require(packet.get("schema_version") == PACKET_SCHEMA_VERSION, "approved packet schema_version mismatch")
    _require(packet.get("version") == PACKET_VERSION, "approved packet version mismatch")
    _require(packet.get("packet_id") == APPROVED_PACKET_ID, "approved packet_id mismatch")
    _require(packet.get("review_status") == "HUMAN_APPROVED", "top-level review_status is not HUMAN_APPROVED")
    _require(packet.get("annotation_status") == "HUMAN_APPROVED", "top-level annotation_status is not HUMAN_APPROVED")
    _require(packet.get("human_gold") is True, "top-level human_gold is not true")
    _require(verify_packet_hash(packet), "approved packet hash is missing or invalid")
    _require(canonical_packet_hash(packet) == APPROVED_PACKET_HASH, "approved packet canonical hash differs from accepted Human Gold")
    _require(canonical_sha256_tag(packet, self_field="packet_hash") == APPROVED_PACKET_HASH, "foundation canonical hash disagrees with packet hash verifier")

    approval = packet.get("approval_record")
    _require(isinstance(approval, Mapping), "approval_record is missing")
    assert isinstance(approval, Mapping)
    approval_fields = {
        "approval_source": "PROJECT_OWNER_HUMAN_REVIEW",
        "answerability_units_approved": APPROVED_ANSWERABILITY_CASES,
        "citation_units_approved": APPROVED_CITATION_CASES,
        "decision": "APPROVE_AS_DRAFTED",
        "evidence_ref": APPROVAL_EVIDENCE_REF,
        "network_deviation": "ACCEPTED_AS_DOCUMENTED_PROCESS_DEVIATION",
        "prepublication_packet_hash": PREPUBLICATION_PACKET_HASH,
        "reviewed_at": APPROVAL_REVIEWED_AT,
        "reviewer_id": APPROVAL_REVIEWER_ID,
    }
    for field, expected in approval_fields.items():
        _require(approval.get(field) == expected, f"approval_record field mismatch: {field}")

    binding = packet.get("source_binding")
    _require(isinstance(binding, Mapping), "source_binding is missing")
    assert isinstance(binding, Mapping)
    _require(thaw_json(binding) == EXPECTED_SOURCE_BINDING, "source dataset provenance differs from accepted D4-3A hashes")
    _require(packet.get("source_dataset_hash") == EXPECTED_SOURCE_BINDING["citation_support"]["hash"], "top-level source_dataset_hash mismatch")

    classification = packet.get("data_classification")
    _require(tuple(classification or ()) == EXPECTED_DATA_CLASSIFICATION, "packet data classification markers mismatch")
    citation_cases = packet.get("cases")
    answerability_cases = packet.get("answerability_cases")
    _require(isinstance(citation_cases, list) and len(citation_cases) == APPROVED_CITATION_CASES, "approved citation case count mismatch")
    _require(isinstance(answerability_cases, list) and len(answerability_cases) == APPROVED_ANSWERABILITY_CASES, "approved answerability case count mismatch")

    for label, records in (("citation", citation_cases), ("answerability", answerability_cases)):
        ids: list[str] = []
        for record in records:
            _require(isinstance(record, Mapping), f"{label} case must be an object")
            _validate_case_review(record, label=label)
            _require(tuple(record.get("data_classification", ())) == EXPECTED_DATA_CLASSIFICATION, f"{record.get('case_id')}: classification markers mismatch")
            ids.append(str(record["case_id"]))
        _require(len(ids) == len(set(ids)), f"duplicate {label} case_id")

    distribution: dict[str, int] = {}
    for case in answerability_cases:
        response_class = case.get("expected_response_class")
        _require(response_class in EXPECTED_CLASS_DISTRIBUTION, f"{case.get('case_id')}: unknown approved response class")
        distribution[str(response_class)] = distribution.get(str(response_class), 0) + 1
    _require(distribution == EXPECTED_CLASS_DISTRIBUTION, "approved answerability class distribution mismatch")

    for case in answerability_cases:
        scope = case.get("target_scope")
        _require(isinstance(scope, Mapping), f"{case.get('case_id')}: target_scope is missing")
        assert isinstance(scope, Mapping)
        _require(scope.get("population") == "university_freshman", f"{case.get('case_id')}: approved population mismatch")

    return packet


def load_approved_packet(path: str | Path) -> ApprovedPacket:
    """Load the accepted D4-3A packet without reordering or normalizing it."""

    source = Path(path)
    try:
        raw = source.read_bytes()
        text = raw.decode("utf-8")
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except ApprovedPacketError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApprovedPacketError(f"cannot read approved packet JSON: {exc}") from exc

    verified = _validate_payload(payload)
    frozen = _freeze(verified)
    return ApprovedPacket(
        path=source.resolve(),
        packet_id=APPROVED_PACKET_ID,
        packet_hash=APPROVED_PACKET_HASH,
        raw_file_sha256=hashlib.sha256(raw).hexdigest(),
        payload=frozen,
        citation_cases=frozen["cases"],
        answerability_cases=frozen["answerability_cases"],
        source_provenance=frozen["source_binding"],
    )
