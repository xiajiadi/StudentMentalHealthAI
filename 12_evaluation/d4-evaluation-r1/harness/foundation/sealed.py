"""SEALED_EVAL freeze and anti-tuning checks."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .errors import SealedMutationError
from .fixtures import enforce_fixture_mode_isolation
from .hashing import canonical_dataset_hash, canonical_sha256, verify_self_hash


def _distribution(records: Iterable[Mapping[str, Any]], field_name: str) -> dict[str, int]:
    return dict(
        sorted(
            Counter(str(record.get(field_name, "")) for record in records).items()
        )
    )


def _record_hashes(records: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    return {
        str(record["case_id"]): canonical_sha256(record, self_field="hash")
        for record in records
    }


@dataclass(frozen=True)
class SealedDatasetSnapshot:
    """Immutable metadata captured before a sealed target is exercised."""

    version: str
    dataset_hash: str
    case_count: int
    scenario_family_distribution: dict[str, int]
    semantic_family_distribution: dict[str, int]
    source_family_distribution: dict[str, int]
    record_hashes: dict[str, str]
    creation_provenance: str
    approval_ref: str
    frozen_at: str
    fixture_mode: str | None
    reported_hashes: dict[str, str] = field(default_factory=dict)

    def as_manifest_fields(self) -> dict[str, Any]:
        return {
            "status": "COMPLETE",
            "case_count": self.case_count,
            "scenario_family_distribution": dict(self.scenario_family_distribution),
            "creation_provenance": self.creation_provenance,
            "approval_ref": self.approval_ref,
        }


def freeze_sealed_dataset(
    records: Iterable[Mapping[str, Any]],
    *,
    version: str,
    creation_provenance: str,
    approval_ref: str,
    frozen_at: datetime | None = None,
) -> SealedDatasetSnapshot:
    """Capture the sealed hash and family distribution before evaluation."""

    materialized = list(records)
    if not materialized:
        raise SealedMutationError("SEALED_EVAL cannot be frozen with zero cases")
    if not isinstance(version, str) or not version.strip():
        raise SealedMutationError("sealed dataset version is required")
    if not isinstance(creation_provenance, str) or not creation_provenance.strip():
        raise SealedMutationError("sealed creation provenance is required")
    if not isinstance(approval_ref, str) or not approval_ref.strip():
        raise SealedMutationError("sealed approval_ref is required")
    for record in materialized:
        if record.get("split") != "SEALED_EVAL":
            raise SealedMutationError(
                f"sealed snapshot received non-sealed case {record.get('case_id')!r}"
            )
        try:
            verify_self_hash(record, field="hash", tagged=True)
        except Exception as exc:
            raise SealedMutationError(
                f"sealed case {record.get('case_id')!r} has invalid self hash: {exc}"
            ) from exc
        try:
            from .schema_validation import validate_scenario

            validate_scenario(record)
        except Exception as exc:
            raise SealedMutationError(
                f"sealed case {record.get('case_id')!r} fails scenario schema validation: {exc}"
            ) from exc
    try:
        fixture_mode = enforce_fixture_mode_isolation(materialized)
    except Exception as exc:
        raise SealedMutationError(f"sealed fixture isolation failed: {exc}") from exc
    timestamp = frozen_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise SealedMutationError("frozen_at must be timezone-aware")
    return SealedDatasetSnapshot(
        version=version.strip(),
        dataset_hash=canonical_dataset_hash(materialized),
        case_count=len(materialized),
        scenario_family_distribution=_distribution(materialized, "scenario_family"),
        semantic_family_distribution=_distribution(materialized, "semantic_family"),
        source_family_distribution=_distribution(materialized, "source_family"),
        record_hashes=_record_hashes(materialized),
        creation_provenance=creation_provenance.strip(),
        approval_ref=approval_ref.strip(),
        frozen_at=timestamp.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
        fixture_mode=fixture_mode,
        reported_hashes={
            str(record["case_id"]): str(record["hash"]) for record in materialized
        },
    )


def assert_sealed_unchanged(
    snapshot: SealedDatasetSnapshot,
    records: Iterable[Mapping[str, Any]],
) -> bool:
    """Raise when a sealed case, family, order-independent hash, or mode changed."""

    materialized = list(records)
    if any(record.get("split") != "SEALED_EVAL" for record in materialized):
        raise SealedMutationError("sealed records changed split")
    actual_hash = canonical_dataset_hash(materialized)
    if actual_hash != snapshot.dataset_hash:
        raise SealedMutationError(
            f"SEALED_EVAL hash changed from {snapshot.dataset_hash} to {actual_hash}"
        )
    if len(materialized) != snapshot.case_count:
        raise SealedMutationError("SEALED_EVAL case count changed")
    for field_name, expected in (
        ("scenario_family", snapshot.scenario_family_distribution),
        ("semantic_family", snapshot.semantic_family_distribution),
        ("source_family", snapshot.source_family_distribution),
    ):
        actual = _distribution(materialized, field_name)
        if actual != expected:
            raise SealedMutationError(
                f"SEALED_EVAL {field_name} distribution changed: {expected} -> {actual}"
            )
    actual_records = _record_hashes(materialized)
    if actual_records != snapshot.record_hashes:
        changed = sorted(
            set(actual_records).symmetric_difference(snapshot.record_hashes)
            | {
                key
                for key in set(actual_records) & set(snapshot.record_hashes)
                if actual_records[key] != snapshot.record_hashes[key]
            }
        )
        raise SealedMutationError(
            "SEALED_EVAL case mutation detected: " + ", ".join(changed)
        )
    if snapshot.reported_hashes:
        actual_reported = {
            str(record["case_id"]): str(record.get("hash", ""))
            for record in materialized
        }
        if actual_reported != snapshot.reported_hashes:
            raise SealedMutationError("SEALED_EVAL self hash field changed")
    current_mode = enforce_fixture_mode_isolation(materialized)
    if current_mode != snapshot.fixture_mode:
        raise SealedMutationError(
            f"SEALED_EVAL fixture mode changed from {snapshot.fixture_mode} to {current_mode}"
        )
    return True


@dataclass
class SealedEvaluationGuard:
    """Runtime guard that blocks tuning after sealed output is observed."""

    snapshot: SealedDatasetSnapshot
    protected_fingerprint: str | None = None
    outputs_observed: set[str] = field(default_factory=set)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Mapping[str, Any]],
        *,
        version: str,
        creation_provenance: str,
        approval_ref: str,
        protected_inputs: Any = None,
    ) -> "SealedEvaluationGuard":
        snapshot = freeze_sealed_dataset(
            records,
            version=version,
            creation_provenance=creation_provenance,
            approval_ref=approval_ref,
        )
        fingerprint = (
            None
            if protected_inputs is None
            else canonical_sha256(protected_inputs, self_field=None)
        )
        return cls(snapshot=snapshot, protected_fingerprint=fingerprint)

    def observe_output(self, case_id: str) -> None:
        if not isinstance(case_id, str) or not case_id:
            raise SealedMutationError("observed sealed output requires case_id")
        if case_id not in self.snapshot.record_hashes:
            raise SealedMutationError(
                f"observed output is not part of the frozen SEALED_EVAL set: {case_id}"
            )
        self.outputs_observed.add(case_id)

    def assert_dataset(self, records: Iterable[Mapping[str, Any]]) -> bool:
        return assert_sealed_unchanged(self.snapshot, records)

    def assert_protected_inputs(self, current_inputs: Any) -> bool:
        if self.protected_fingerprint is None:
            raise SealedMutationError("no protected input fingerprint was frozen")
        actual = canonical_sha256(current_inputs, self_field=None)
        if actual != self.protected_fingerprint:
            raise SealedMutationError(
                "sealed protected evaluation inputs changed after freeze"
            )
        return True

    def assert_tuning_allowed(self, *, kind: str = "evaluation input") -> None:
        """Raise after any sealed output has been observed.

        A caller can use this before changing prompts, policies, providers, or
        fixtures.  The guard does not claim that a code diff is safe; it only
        enforces the point at which tuning becomes forbidden.
        """

        if self.outputs_observed:
            observed = ", ".join(sorted(self.outputs_observed))
            raise SealedMutationError(
                f"cannot tune {kind} after SEALED_EVAL output was observed: {observed}"
            )

    def record_tuning_attempt(self, *, kind: str = "evaluation input") -> None:
        self.assert_tuning_allowed(kind=kind)


# Alias used by evidence wrappers.
detect_sealed_mutation = assert_sealed_unchanged
assert_no_sealed_mutation = assert_sealed_unchanged
