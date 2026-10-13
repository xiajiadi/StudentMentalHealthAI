"""Import allowlisted ordinal response columns for isolated research only.

The importer deliberately does not create ItemBank objects, scores, or CAT
parameters. Unknown source columns are discarded and never written to output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from typing import Sequence


MINIMUM_EVALUATION_SIZE = 800
_TEMP_DIRECTORY_PREFIX = ".research-import-"
_SAFE_RESPONSE_COLUMN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_BLOCKED_COLUMN_TOKENS = {
    "address",
    "age",
    "birth",
    "case",
    "city",
    "class",
    "clinic",
    "clinical",
    "comment",
    "contact",
    "country",
    "date",
    "demographic",
    "diagnosis",
    "dob",
    "duration",
    "email",
    "ethnicity",
    "freeform",
    "freetext",
    "gender",
    "grade",
    "id",
    "name",
    "note",
    "patient",
    "person",
    "phone",
    "race",
    "record",
    "respondent",
    "risk",
    "score",
    "se",
    "school",
    "sex",
    "site",
    "source",
    "student",
    "subject",
    "summary",
    "theta",
    "text",
    "time",
    "timestamp",
    "total",
    "estimate",
    "uuid",
    "zip",
}


class ImportErrorSafe(ValueError):
    """A validation error safe to show without including source values."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ImportSpec:
    source_path: Path
    output_dir: Path
    delimiter: str
    response_columns: tuple[str, ...]
    ordinal_values: tuple[int, ...]
    missing_codes: tuple[str, ...]
    expected_source_sha256: str
    source_reference: str
    source_license: str
    source_population: str
    source_language: str
    source_version: str
    seed: int
    calibration_size: int
    evaluation_size: int


@dataclass(frozen=True)
class SelectedRecord:
    """A sampled numeric response tuple with ephemeral source row tracking."""

    source_record_number: int
    responses: tuple[int | None, ...]


@dataclass(frozen=True)
class ParsedSource:
    records: tuple[SelectedRecord, ...]
    source_record_count: int
    missing_by_column: dict[str, int]
    excluded_column_count: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata_text(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ImportErrorSafe("invalid_metadata", f"{field} must be a text value")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 500 or "\n" in cleaned or "\r" in cleaned:
        raise ImportErrorSafe("invalid_metadata", f"{field} must be a short, single-line value")
    return cleaned


def _contains_blocked_column_token(column: str) -> bool:
    # Split common camelCase names before tokenizing, then fail closed if an
    # explicitly selected field resembles an ID, demographic, time, or text field.
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", column)
    tokens = set(re.findall(r"[a-z0-9]+", camel_split.casefold()))
    normalized_tokens = {re.sub(r"\d+$", "", token) for token in tokens}
    return bool(normalized_tokens & _BLOCKED_COLUMN_TOKENS)


def validate_spec(spec: ImportSpec) -> None:
    if not spec.source_path.is_file():
        raise ImportErrorSafe("source_not_found", "source file does not exist or is not a file")
    if spec.delimiter not in {",", "\t"}:
        raise ImportErrorSafe("invalid_delimiter", "delimiter must be comma or tab")
    if not spec.response_columns:
        raise ImportErrorSafe("empty_allowlist", "at least one response column is required")
    if len(set(spec.response_columns)) != len(spec.response_columns):
        raise ImportErrorSafe("duplicate_allowlist_column", "response column allowlist contains duplicates")
    for column in spec.response_columns:
        if not _SAFE_RESPONSE_COLUMN.fullmatch(column):
            raise ImportErrorSafe("unsafe_response_column", "allowlisted response column has an unsupported name")
        if _contains_blocked_column_token(column):
            raise ImportErrorSafe("blocked_response_column", "allowlist contains an ID, demographic, time, or text field")
    if (
        not spec.ordinal_values
        or any(type(value) is not int for value in spec.ordinal_values)
        or tuple(sorted(set(spec.ordinal_values))) != spec.ordinal_values
    ):
        raise ImportErrorSafe("invalid_ordinal_values", "ordinal values must be unique integers in ascending order")
    if (
        len(set(spec.missing_codes)) != len(spec.missing_codes)
        or any(not isinstance(code, str) or not code or code != code.strip() for code in spec.missing_codes)
        or set(spec.missing_codes) & {str(value) for value in spec.ordinal_values}
    ):
        raise ImportErrorSafe("invalid_missing_codes", "missing codes must be unique, nonblank, and distinct from ordinal values")
    if len(spec.expected_source_sha256) != 64 or not re.fullmatch(r"[a-fA-F0-9]{64}", spec.expected_source_sha256):
        raise ImportErrorSafe("invalid_source_hash", "expected source SHA-256 must be 64 hexadecimal characters")
    if type(spec.calibration_size) is not int or spec.calibration_size < 1:
        raise ImportErrorSafe("invalid_calibration_size", "calibration size must be positive")
    if type(spec.evaluation_size) is not int:
        raise ImportErrorSafe("invalid_evaluation_size", "evaluation size must be an integer")
    if spec.evaluation_size < MINIMUM_EVALUATION_SIZE:
        raise ImportErrorSafe(
            "evaluation_below_minimum",
            f"evaluation size must be at least {MINIMUM_EVALUATION_SIZE}",
        )
    if type(spec.seed) is not int or spec.seed < 0:
        raise ImportErrorSafe("invalid_seed", "seed must be non-negative")
    missing = [
        _metadata_text(spec.source_reference, "source reference"),
        _metadata_text(spec.source_license, "source license"),
        _metadata_text(spec.source_population, "source population"),
        _metadata_text(spec.source_language, "source language"),
        _metadata_text(spec.source_version, "source version"),
    ]
    if any(not value for value in missing):
        raise ImportErrorSafe("invalid_metadata", "required source metadata is missing")


def _parse_row(
    row: dict[str | None, str | list[str] | None],
    *,
    record_number: int,
    response_columns: tuple[str, ...],
    allowed_values: set[str],
    missing_codes: set[str],
) -> tuple[tuple[int | None, ...], tuple[bool, ...]]:
    if None in row:
        raise ImportErrorSafe("malformed_row", f"source record {record_number} has extra cells")
    converted: list[int | None] = []
    missing_flags: list[bool] = []
    for column in response_columns:
        raw = row.get(column)
        if raw is None or isinstance(raw, list):
            raise ImportErrorSafe("malformed_row", f"source record {record_number} is missing a response cell")
        value = raw.strip()
        if value == "" or value in missing_codes:
            converted.append(None)
            missing_flags.append(True)
            continue
        if value not in allowed_values:
            raise ImportErrorSafe(
                "invalid_ordinal_response",
                f"source record {record_number} contains a response outside the allowed ordinal values in column {column}",
            )
        converted.append(int(value))
        missing_flags.append(False)
    return tuple(converted), tuple(missing_flags)


def _read_and_sample(spec: ImportSpec, *, sample_size: int) -> ParsedSource:
    expected_columns = set(spec.response_columns)
    allowed_values = {str(value) for value in spec.ordinal_values}
    missing_codes = set(spec.missing_codes)
    rng = random.Random(spec.seed)
    reservoir: list[SelectedRecord] = []
    missing_by_column = dict.fromkeys(spec.response_columns, 0)
    seen = 0
    excluded_column_count = 0

    try:
        with spec.source_path.open("r", encoding="utf-8-sig", newline="") as source:
            reader = csv.DictReader(source, delimiter=spec.delimiter, strict=True)
            headers = reader.fieldnames
            if not headers:
                raise ImportErrorSafe("empty_source", "source has no header row")
            if any(not header or header.strip() != header for header in headers):
                raise ImportErrorSafe("invalid_header", "source header contains an empty or padded field name")
            if len(set(headers)) != len(headers):
                raise ImportErrorSafe("duplicate_source_header", "source header contains duplicate column names")
            if not expected_columns.issubset(set(headers)):
                raise ImportErrorSafe("allowlist_column_missing", "one or more allowlisted response columns are absent")
            excluded_column_count = len(set(headers) - expected_columns)

            for record_number, row in enumerate(reader, start=1):
                responses, missing_flags = _parse_row(
                    row,
                    record_number=record_number,
                    response_columns=spec.response_columns,
                    allowed_values=allowed_values,
                    missing_codes=missing_codes,
                )
                for column, is_missing in zip(spec.response_columns, missing_flags, strict=True):
                    if is_missing:
                        missing_by_column[column] += 1

                seen += 1
                selected = SelectedRecord(record_number, responses)
                if len(reservoir) < sample_size:
                    reservoir.append(selected)
                else:
                    replacement_index = rng.randrange(seen)
                    if replacement_index < sample_size:
                        reservoir[replacement_index] = selected
    except UnicodeDecodeError as exc:
        raise ImportErrorSafe("invalid_encoding", "source must be UTF-8 or UTF-8 with BOM") from exc
    except csv.Error as exc:
        raise ImportErrorSafe("invalid_csv", "source has invalid CSV/TSV quoting or structure") from exc
    except OSError as exc:
        raise ImportErrorSafe("source_read_failed", "source file could not be read") from exc

    if seen < sample_size:
        raise ImportErrorSafe("insufficient_records", "source has fewer valid records than requested split sizes")
    rng.shuffle(reservoir)
    return ParsedSource(tuple(reservoir), seen, missing_by_column, excluded_column_count)


def _missing_counts(records: Sequence[SelectedRecord], response_columns: tuple[str, ...]) -> dict[str, int]:
    counts = dict.fromkeys(response_columns, 0)
    for record in records:
        for column, value in zip(response_columns, record.responses, strict=True):
            if value is None:
                counts[column] += 1
    return counts


def _write_response_csv(path: Path, columns: tuple[str, ...], records: Sequence[SelectedRecord]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(columns)
        for record in records:
            writer.writerow(["" if value is None else value for value in record.responses])


def _cleanup_owned_temporary_directory(temporary_dir: Path, destination_parent: Path) -> None:
    try:
        info = temporary_dir.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ImportErrorSafe("cleanup_failed", "temporary output directory could not be inspected") from exc

    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    is_reparse_point = bool(getattr(info, "st_file_attributes", 0) & reparse_flag)
    try:
        expected_parent = destination_parent.resolve(strict=True)
        actual_parent = temporary_dir.parent.resolve(strict=True)
        resolved_temporary_dir = temporary_dir.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ImportErrorSafe("cleanup_failed", "temporary output directory path could not be verified") from exc

    if (
        not temporary_dir.name.startswith(_TEMP_DIRECTORY_PREFIX)
        or actual_parent != expected_parent
        or resolved_temporary_dir.parent != expected_parent
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or is_reparse_point
    ):
        raise ImportErrorSafe("cleanup_failed", "refusing to remove a directory outside the owned temporary scope")
    try:
        shutil.rmtree(temporary_dir)
    except OSError as exc:
        raise ImportErrorSafe("cleanup_failed", "owned temporary output directory could not be removed") from exc


def import_responses(spec: ImportSpec) -> dict[str, object]:
    """Validate, randomly sample, split, and write only numeric responses."""

    validate_spec(spec)
    try:
        actual_hash = sha256_file(spec.source_path)
    except OSError as exc:
        raise ImportErrorSafe("source_read_failed", "source file could not be read for hash verification") from exc
    if actual_hash.casefold() != spec.expected_source_sha256.casefold():
        raise ImportErrorSafe("source_hash_mismatch", "source SHA-256 does not match the supplied provenance hash")

    destination = spec.output_dir
    if destination.exists():
        raise ImportErrorSafe("output_exists", "output directory already exists; choose a new empty destination")

    sample_size = spec.calibration_size + spec.evaluation_size
    parsed = _read_and_sample(spec, sample_size=sample_size)
    try:
        if sha256_file(spec.source_path).casefold() != actual_hash.casefold():
            raise ImportErrorSafe("source_changed_during_import", "source SHA-256 changed while it was being imported")
    except OSError as exc:
        raise ImportErrorSafe("source_read_failed", "source file could not be rechecked after validation") from exc
    calibration = parsed.records[: spec.calibration_size]
    evaluation = parsed.records[spec.calibration_size :]

    # Source row markers exist only in memory for audit/test of split disjointness.
    calibration_markers = {record.source_record_number for record in calibration}
    evaluation_markers = {record.source_record_number for record in evaluation}
    if len(calibration_markers) != len(calibration) or len(evaluation_markers) != len(evaluation):
        raise ImportErrorSafe("duplicate_sample_record", "sampling produced duplicate source records")
    if calibration_markers & evaluation_markers:
        raise ImportErrorSafe("overlapping_splits", "calibration and evaluation splits overlap")

    manifest: dict[str, object] = {
        "format_version": "research-response.v1",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "source": {
            "reference": _metadata_text(spec.source_reference, "source reference"),
            "sha256": actual_hash,
            "license": _metadata_text(spec.source_license, "source license"),
            "population": _metadata_text(spec.source_population, "source population"),
            "language": _metadata_text(spec.source_language, "source language"),
            "version": _metadata_text(spec.source_version, "source version"),
        },
        "response_columns": list(spec.response_columns),
        "ordinal_values": list(spec.ordinal_values),
        "missing_policy": {
            "blank_is_missing": True,
            "additional_missing_codes": list(spec.missing_codes),
            "missing_preserved_as_empty_cells": True,
        },
        "sampling": {
            "method": "seeded_reservoir_sample_without_replacement_then_shuffle",
            "seed": spec.seed,
            "source_record_count": parsed.source_record_count,
            "excluded_source_column_count": parsed.excluded_column_count,
            "selected_record_count": sample_size,
            "unused_source_record_count": parsed.source_record_count - sample_size,
            "calibration_record_count": len(calibration),
            "evaluation_record_count": len(evaluation),
            "splits_disjoint": True,
            "source_row_identifiers_written": False,
        },
        "aggregate_missing_cells": {
            "source_by_response_column": parsed.missing_by_column,
            "calibration_by_response_column": _missing_counts(calibration, spec.response_columns),
            "evaluation_by_response_column": _missing_counts(evaluation, spec.response_columns),
        },
        "not_created": {
            "calibrated_parameters": True,
            "published_scale": True,
            "scores_or_interpretations": True,
        },
    }

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_dir = Path(tempfile.mkdtemp(prefix=_TEMP_DIRECTORY_PREFIX, dir=destination.parent))
    except OSError as exc:
        raise ImportErrorSafe("output_write_failed", "output parent or temporary directory could not be created") from exc
    try:
        _write_response_csv(temporary_dir / "calibration.csv", spec.response_columns, calibration)
        _write_response_csv(temporary_dir / "evaluation.csv", spec.response_columns, evaluation)
        manifest["output_integrity"] = {
            "calibration.csv": {
                "sha256": sha256_file(temporary_dir / "calibration.csv"),
                "record_count": len(calibration),
            },
            "evaluation.csv": {
                "sha256": sha256_file(temporary_dir / "evaluation.csv"),
                "record_count": len(evaluation),
            },
        }
        manifest_path = temporary_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.rename(temporary_dir, destination)
    except OSError as exc:
        _cleanup_owned_temporary_directory(temporary_dir, destination.parent)
        raise ImportErrorSafe("output_write_failed", "could not atomically write the research output directory") from exc
    except Exception as exc:
        _cleanup_owned_temporary_directory(temporary_dir, destination.parent)
        raise

    return {
        "status": "ok",
        "calibration_records": len(calibration),
        "evaluation_records": len(evaluation),
        "source_records": parsed.source_record_count,
        "output_files": ["calibration.csv", "evaluation.csv", "manifest.json"],
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create isolated response-only research splits; does not publish a scale or run online CAT."
    )
    parser.add_argument("--source", required=True, type=Path, help="UTF-8 CSV/TSV source path")
    parser.add_argument("--output-dir", required=True, type=Path, help="New output directory; must not already exist")
    parser.add_argument("--delimiter", choices=("comma", "tab"), required=True)
    parser.add_argument("--response-column", action="append", required=True, dest="response_columns", help="Allowlisted ordinal response column; repeat for each item")
    parser.add_argument("--ordinal-values", required=True, nargs="+", type=int, help="Allowed integer response categories in ascending order")
    parser.add_argument("--missing-code", action="append", default=[], dest="missing_codes", help="Explicit additional missing code; may be repeated")
    parser.add_argument("--source-sha256", required=True, dest="expected_source_sha256")
    parser.add_argument("--source-reference", required=True, help="DOI or public source URL")
    parser.add_argument("--source-license", required=True)
    parser.add_argument("--source-population", required=True)
    parser.add_argument("--source-language", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--calibration-size", required=True, type=int)
    parser.add_argument("--evaluation-size", required=True, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    delimiter = "," if args.delimiter == "comma" else "\t"
    spec = ImportSpec(
        source_path=args.source,
        output_dir=args.output_dir,
        delimiter=delimiter,
        response_columns=tuple(args.response_columns),
        ordinal_values=tuple(args.ordinal_values),
        missing_codes=tuple(args.missing_codes),
        expected_source_sha256=args.expected_source_sha256,
        source_reference=args.source_reference,
        source_license=args.source_license,
        source_population=args.source_population,
        source_language=args.source_language,
        source_version=args.source_version,
        seed=args.seed,
        calibration_size=args.calibration_size,
        evaluation_size=args.evaluation_size,
    )
    try:
        summary = import_responses(spec)
    except ImportErrorSafe as exc:
        print(f"research-import failed [{exc.code}]: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
