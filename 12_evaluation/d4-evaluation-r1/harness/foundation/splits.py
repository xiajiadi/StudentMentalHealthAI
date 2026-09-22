"""DEV/REGRESSION/SEALED_EVAL dataset partition enforcement."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .errors import HashIntegrityError, SplitIntegrityError
from .fixtures import enforce_fixture_mode_isolation, validate_fixture_record
from .hashing import canonical_dataset_hash, verify_self_hash
from .paths import safe_artifact_path

DATASET_SPLITS = frozenset({"DEV", "REGRESSION", "SEALED_EVAL"})
SPLITS = DATASET_SPLITS
SPLIT_DIRECTORY_NAMES = {
    "DEV": "dev",
    "REGRESSION": "regression",
    "SEALED_EVAL": "sealed",
}
REQUIRED_PARTITION_FIELDS = ("scenario_family", "source_family", "semantic_family")
CASE_ID_PATTERN = re.compile(
    r"^(?:D4E-(?:0[1-9]|[1-5][0-9]|60)|D4SUP-(?:0[1-9]|1[0-9]|20))(?:-[A-Z0-9][A-Z0-9_-]*)?$"
)
FAMILY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class FamilyCollision:
    """One family key observed in more than one dataset split."""

    field: str
    value: str
    splits: tuple[str, ...]
    case_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "value": self.value,
            "splits": list(self.splits),
            "case_ids": list(self.case_ids),
        }


def _read_records_file(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix.lower() == ".jsonl":
            records: list[dict[str, Any]] = []
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise SplitIntegrityError(
                        f"invalid JSONL at {path}:{line_number}: {exc}"
                    ) from exc
                if not isinstance(value, dict):
                    raise SplitIntegrityError(
                        f"dataset record at {path}:{line_number} is not an object"
                    )
                records.append(value)
            return records
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SplitIntegrityError(f"cannot read dataset file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SplitIntegrityError(f"invalid JSON at {path}: {exc}") from exc
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        return list(value)
    raise SplitIntegrityError(f"dataset file must contain object/list of objects: {path}")


def _iter_data_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        relative_parts = {part.lower() for part in path.relative_to(root).parts}
        if (
            path.is_file()
            and path.suffix.lower() in {".json", ".jsonl"}
            and "fixtures" not in relative_parts
        ):
            yield path


def _validate_record_shape(record: Mapping[str, Any], expected_split: str | None) -> None:
    case_id = record.get("case_id")
    if not isinstance(case_id, str) or not CASE_ID_PATTERN.fullmatch(case_id):
        raise SplitIntegrityError("every D4 scenario requires a schema-shaped case_id")
    split = record.get("split")
    if split not in DATASET_SPLITS:
        raise SplitIntegrityError(
            f"case {case_id} has invalid split {split!r}; expected {sorted(DATASET_SPLITS)}"
        )
    if expected_split is not None and split != expected_split:
        raise SplitIntegrityError(
            f"case {case_id} declares {split}, but is loaded from {expected_split}"
        )
    for field in REQUIRED_PARTITION_FIELDS:
        value = record.get(field)
        if not isinstance(value, str) or not FAMILY_PATTERN.fullmatch(value):
            raise SplitIntegrityError(f"case {case_id} requires {field}")
    if record.get("real_student_data") is True:
        raise SplitIntegrityError(f"case {case_id} is marked as real student data")
    try:
        verify_self_hash(record, field="hash", tagged=True)
    except HashIntegrityError as exc:
        raise SplitIntegrityError(f"case {case_id} has invalid self hash: {exc}") from exc
    try:
        validate_fixture_record(record)
    except Exception as exc:
        raise SplitIntegrityError(f"case {case_id} has invalid fixture binding: {exc}") from exc
    try:
        # Dataset loading is a trust boundary: a record that only has the
        # partition fields is not a valid D4 scenario.  Import lazily to keep
        # the schema helper independent from the split module at import time.
        from .schema_validation import validate_scenario

        validate_scenario(record)
    except Exception as exc:
        raise SplitIntegrityError(f"case {case_id} fails scenario schema validation: {exc}") from exc


def load_dataset_records(
    path: str | Path,
    *,
    expected_split: str | None = None,
) -> list[dict[str, Any]]:
    """Load and validate JSON/JSONL scenarios from a split directory or file."""

    if expected_split is not None and expected_split not in DATASET_SPLITS:
        raise SplitIntegrityError(f"invalid expected_split: {expected_split}")
    root = Path(path)
    if not root.exists():
        raise SplitIntegrityError(f"dataset path does not exist: {root}")
    files = [root] if root.is_file() else list(_iter_data_files(root))
    records: list[dict[str, Any]] = []
    for file_path in files:
        file_records = _read_records_file(file_path)
        for record in file_records:
            _validate_record_shape(record, expected_split)
            records.append(record)
    seen: set[str] = set()
    for record in records:
        case_id = record["case_id"]
        if case_id in seen:
            raise SplitIntegrityError(f"duplicate case_id in dataset path: {case_id}")
        seen.add(case_id)
    return records


def detect_cross_split_collisions(
    records: Iterable[Mapping[str, Any]],
    *,
    family_fields: Sequence[str] = REQUIRED_PARTITION_FIELDS,
) -> list[FamilyCollision]:
    """Find case/family keys that occur in more than one split.

    Explicit semantic families are authoritative.  Near-duplicate wording is
    therefore kept together whenever records share ``semantic_family``; no
    random paraphrase or text-only heuristic is used to split them.
    """

    grouped: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for record in records:
        split = record.get("split")
        if split not in DATASET_SPLITS:
            raise SplitIntegrityError(f"invalid split in collision check: {split!r}")
        case_id = str(record.get("case_id", ""))
        if not case_id:
            raise SplitIntegrityError("collision check requires case_id")
        fields = tuple(family_fields) + ("case_id",)
        for field in fields:
            value = record.get(field)
            if not isinstance(value, str) or not value:
                raise SplitIntegrityError(f"collision check requires {field}")
            grouped[(field, value)]["splits"].add(split)
            grouped[(field, value)]["case_ids"].add(case_id)
    collisions: list[FamilyCollision] = []
    for (field, value), data in sorted(grouped.items()):
        splits = tuple(sorted(data["splits"]))
        if len(splits) > 1:
            collisions.append(
                FamilyCollision(
                    field=field,
                    value=value,
                    splits=splits,
                    case_ids=tuple(sorted(data["case_ids"])),
                )
            )
    return collisions


def enforce_split_integrity(
    records: Iterable[Mapping[str, Any]],
    *,
    validate_records: bool = True,
) -> dict[str, Any]:
    """Enforce split, hash, family, duplicate, and fixture isolation rules.

    The returned summary is safe to place in a manifest and contains counts,
    not scenario text.  A violation raises before any summary is returned.
    """

    materialized = list(records)
    if validate_records:
        for record in materialized:
            _validate_record_shape(record, None)
    seen_ids: dict[str, str] = {}
    for record in materialized:
        case_id = str(record.get("case_id", ""))
        split = record.get("split")
        previous = seen_ids.get(case_id)
        if previous is not None:
            raise SplitIntegrityError(
                f"case_id {case_id} appears more than once ({previous}, {split})"
            )
        seen_ids[case_id] = str(split)
    collisions = detect_cross_split_collisions(materialized)
    if collisions:
        details = "; ".join(
            f"{item.field}={item.value!r}: {','.join(item.splits)}"
            for item in collisions
        )
        raise SplitIntegrityError(f"cross-split family collision: {details}")
    fixture_mode = enforce_fixture_mode_isolation(materialized)
    split_counts = Counter(str(record["split"]) for record in materialized)
    family_counts = {
        field: len({str(record[field]) for record in materialized})
        for field in REQUIRED_PARTITION_FIELDS
    }
    return {
        "case_count": len(materialized),
        "split_counts": {split: split_counts.get(split, 0) for split in sorted(DATASET_SPLITS)},
        "family_counts": family_counts,
        "fixture_mode": fixture_mode,
        "dataset_hash": canonical_dataset_hash(materialized),
    }


def enforce_split_tree(root: str | Path) -> dict[str, Any]:
    """Load ``datasets/dev``, ``regression`` and ``sealed`` and enforce all rules."""

    root_path = Path(root)
    by_split: dict[str, list[dict[str, Any]]] = {}
    for split, dirname in SPLIT_DIRECTORY_NAMES.items():
        split_path = safe_artifact_path(root_path, dirname)
        if split_path.exists():
            by_split[split] = load_dataset_records(split_path, expected_split=split)
        else:
            by_split[split] = []
    all_records = [record for records in by_split.values() for record in records]
    summary = enforce_split_integrity(all_records)
    summary["split_paths"] = {
        split: SPLIT_DIRECTORY_NAMES[split] for split in sorted(DATASET_SPLITS)
    }
    return summary


# Names used by callers that prefer the singular form.
detect_semantic_family_cross_split = detect_cross_split_collisions
assert_split_integrity = enforce_split_integrity
