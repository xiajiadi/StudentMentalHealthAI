"""Aggregate-only full-bank EAP reference for the pinned PROMIS eight-item sample.

This is a numeric cross-check of the fixed eight-item research path. The data
manifest declares no calibration/evaluation split, and the profile fixes both
minimum and maximum length at eight; this module makes no shortening, accuracy,
school-population, or clinical-validity claim.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from cat_engine.domain.config import CATConfig
from cat_engine.research.research_session import (
    ResearchCATProfile,
    ResearchCATSession,
    ResearchSessionError,
    _PROMIS_PEDIATRIC_MANIFEST_SHA256,
    _PROMIS_PEDIATRIC_PROFILE_SHA256,
    _keyed_score,
)


FORMAT_VERSION = "promis-eight-full-bank-eap-comparison.v1"
GRID_STEPS = 10_000
EXPECTED_RECORDS = 800
_CATEGORY_COUNT = 5


class FullBankComparisonError(ValueError):
    """Closed failure without echoing response values or paths from input rows."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _Aggregate:
    records: int
    completed: int
    failures: Mapping[str, int]
    stop_reasons: Mapping[str, int]
    test_length_counts: Mapping[str, int]
    item_exposure_counts: Mapping[str, int]
    estimate_mean_difference: float
    estimate_mae: float
    estimate_rmse: float
    estimate_max_absolute_difference: float
    standard_error_mae: float
    standard_error_max_absolute_difference: float


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise FullBankComparisonError("INPUT_UNREADABLE", "a pinned aggregate input is unavailable") from exc
    return digest.hexdigest()


def _logistic_array(values: np.ndarray) -> np.ndarray:
    # Values are bounded by the fixed theta interval and published item
    # parameters, but use a stable branch so this remains safe if they change.
    result = np.empty_like(values, dtype=np.float64)
    nonnegative = values >= 0.0
    result[nonnegative] = 1.0 / (1.0 + np.exp(-values[nonnegative]))
    exp_value = np.exp(values[~nonnegative])
    result[~nonnegative] = exp_value / (1.0 + exp_value)
    return result


def _independent_full_bank_eap(
    profile: ResearchCATProfile,
    raw_responses: Sequence[int],
    *,
    grid_steps: int = GRID_STEPS,
) -> tuple[float, float]:
    """Compute full-bank EAP by direct GRM likelihood quadrature.

    The calculation deliberately does not call the CAT engine's EAP estimator.
    It shares only the verified profile parameters and the profile's explicit
    raw-category/key mapping.
    """

    if (
        type(grid_steps) is not int
        or grid_steps < 100
        or len(raw_responses) != len(profile.items)
        or len(profile.items) != 8
        or len(profile.source_categories) != _CATEGORY_COUNT
    ):
        raise FullBankComparisonError("REFERENCE_INPUT_INVALID", "reference requires exactly eight valid items")
    try:
        categories = [
            _keyed_score(raw, item.key_direction, profile.source_categories)
            for item, raw in zip(profile.items, raw_responses, strict=True)
        ]
    except ResearchSessionError as exc:
        raise FullBankComparisonError("RESPONSE_CATEGORY_INVALID", "a response is outside the pinned source categories") from exc

    theta = np.linspace(-4.0, 4.0, grid_steps + 1, dtype=np.float64)
    log_likelihood = np.zeros(theta.shape, dtype=np.float64)
    for item, category in zip(profile.items, categories, strict=True):
        cumulative = [np.ones(theta.shape, dtype=np.float64)]
        cumulative.extend(
            _logistic_array(item.a * (theta - threshold))
            for threshold in item.thresholds
        )
        cumulative.append(np.zeros(theta.shape, dtype=np.float64))
        probabilities = cumulative[category] - cumulative[category + 1]
        if np.any(probabilities < 0.0) or not np.all(np.isfinite(probabilities)):
            raise FullBankComparisonError("REFERENCE_PROBABILITY_INVALID", "pinned GRM probabilities are invalid")
        with np.errstate(divide="ignore"):
            log_likelihood += np.log(probabilities)

    # N(0,1) prior over the declared [-4,4] integration interval. The
    # normalizing constant cancels in the posterior ratio.
    log_posterior = log_likelihood - 0.5 * theta * theta
    maximum = float(np.max(log_posterior))
    if not math.isfinite(maximum):
        raise FullBankComparisonError("REFERENCE_MASS_INVALID", "full-bank posterior has no finite mass")
    weights = np.exp(log_posterior - maximum)
    weights[[0, -1]] *= 0.5  # composite trapezoid rule
    mass = float(np.sum(weights))
    if not math.isfinite(mass) or mass <= 0.0:
        raise FullBankComparisonError("REFERENCE_MASS_INVALID", "full-bank posterior has no positive mass")
    mean = float(np.dot(theta, weights) / mass)
    variance = float(np.dot((theta - mean) ** 2, weights) / mass)
    if not math.isfinite(mean) or not math.isfinite(variance) or variance < 0.0:
        raise FullBankComparisonError("REFERENCE_MOMENT_INVALID", "full-bank posterior moments are invalid")
    return mean, math.sqrt(variance)


def _load_profile(profile_path: Path, manifest_path: Path) -> ResearchCATProfile:
    try:
        return ResearchCATProfile.load(
            profile_path,
            expected_file_sha256=_PROMIS_PEDIATRIC_PROFILE_SHA256,
            manifest_path=manifest_path,
            expected_manifest_sha256=_PROMIS_PEDIATRIC_MANIFEST_SHA256,
        )
    except ResearchSessionError as exc:
        raise FullBankComparisonError("PROFILE_PIN_INVALID", "pinned PROMIS profile verification failed") from exc


def _read_complete_responses(path: Path, profile: ResearchCATProfile) -> tuple[list[tuple[int, ...]], str]:
    expected_columns = tuple(item.qid for item in profile.items)
    if len(expected_columns) != 8 or len(set(expected_columns)) != 8:
        raise FullBankComparisonError("PROFILE_ITEM_SET_INVALID", "pinned profile is not the expected eight-item bank")
    file_hash = _sha256_file(path)
    try:
        metadata = json.loads(profile.raw_metadata_json)
        expected_hash = metadata["provenance"]["complete_observed_800_csv_sha256"]
        if file_hash != expected_hash:
            raise FullBankComparisonError("RESPONSE_HASH_MISMATCH", "observed response matrix does not match the pinned profile")
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != expected_columns:
                raise FullBankComparisonError("RESPONSE_COLUMNS_INVALID", "response matrix columns differ from the pinned eight-item bank")
            rows: list[tuple[int, ...]] = []
            for row in reader:
                if row is None or set(row) != set(expected_columns) or any(row[key] is None for key in expected_columns):
                    raise FullBankComparisonError("RESPONSE_ROW_INVALID", "response matrix row has an invalid shape")
                try:
                    values = tuple(int(row[key]) for key in expected_columns)
                except (TypeError, ValueError) as exc:
                    raise FullBankComparisonError("RESPONSE_CATEGORY_INVALID", "response matrix contains a non-integer category") from exc
                if any(value not in profile.source_categories for value in values):
                    raise FullBankComparisonError("RESPONSE_CATEGORY_INVALID", "response matrix contains a category outside the source scale")
                rows.append(values)
    except FullBankComparisonError:
        raise
    except (OSError, csv.Error, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise FullBankComparisonError("RESPONSE_MATRIX_INVALID", "pinned complete response matrix could not be validated") from exc
    if len(rows) != EXPECTED_RECORDS:
        raise FullBankComparisonError("RESPONSE_COUNT_INVALID", "response matrix does not contain the pinned 800 complete records")
    return rows, file_hash


def _run_aggregate(profile: ResearchCATProfile, rows: Sequence[Sequence[int]]) -> _Aggregate:
    config = CATConfig.from_dict(
        {
            "config_version": "promis-pediatric-observed-coverage-unapproved-v1",
            "model": "GRM",
            "estimator": "EAP",
            "selection_method": "MFI",
            "min_items": 8,
            "max_items": 8,
            "se_threshold": None,
            "initial_theta": 0.0,
            "prior_mean": 0.0,
            "prior_sd": 1.0,
            "optimization_interval": [-4.0, 4.0],
            "seed": 2026101414,
            "exposure_control": "none",
            "content_balancing": "none",
        }
    )
    if len(profile.items) != 8 or config.min_items != config.max_items or config.max_items != 8:
        raise FullBankComparisonError("CONFIG_SCOPE_INVALID", "comparison must remain fixed at all eight bank items")

    exposures = dict.fromkeys((item.qid for item in profile.items), 0)
    length_counts: dict[str, int] = {}
    stop_counts: dict[str, int] = {}
    differences: list[float] = []
    se_differences: list[float] = []
    failures: dict[str, int] = {}

    for raw_values in rows:
        by_qid = {item.qid: raw for item, raw in zip(profile.items, raw_values, strict=True)}
        try:
            session = ResearchCATSession.start(
                profile,
                config,
                session_id="ephemeral-fullbank-reference",
            )
            while session.status == "ACTIVE":
                question = session.next_item()
                if question is None:
                    raise FullBankComparisonError("CAT_PATH_INCOMPLETE", "fixed eight-item CAT path stopped before completion")
                if question.qid not in by_qid:
                    raise FullBankComparisonError("CAT_ITEM_OUTSIDE_PROFILE", "CAT selected an item outside the verified response bank")
                session.answer(question.item_id, by_qid[question.qid])
                exposures[question.qid] += 1
            if session.status != "COMPLETED" or session.items_answered != 8:
                raise FullBankComparisonError("CAT_PATH_INCOMPLETE", "fixed eight-item CAT path did not administer the full bank")
            reference_theta, reference_se = _independent_full_bank_eap(profile, raw_values)
            differences.append(float(session._theta) - reference_theta)
            se_differences.append(float(session._se) - reference_se)
            stop_reason = session.stop_reason or "UNKNOWN"
            stop_counts[stop_reason] = stop_counts.get(stop_reason, 0) + 1
            length_key = str(session.items_answered)
            length_counts[length_key] = length_counts.get(length_key, 0) + 1
        except FullBankComparisonError as exc:
            failures[exc.code] = failures.get(exc.code, 0) + 1
        except Exception as exc:
            # Fail closed without serializing per-record values or exception text.
            code = type(exc).__name__
            failures[code] = failures.get(code, 0) + 1

    completed = len(differences)
    if completed == 0:
        raise FullBankComparisonError("CAT_RUN_EMPTY", "no complete CAT/reference comparisons were produced")
    abs_diff = [abs(value) for value in differences]
    abs_se_diff = [abs(value) for value in se_differences]
    return _Aggregate(
        records=len(rows),
        completed=completed,
        failures=dict(sorted(failures.items())),
        stop_reasons=dict(sorted(stop_counts.items())),
        test_length_counts=dict(sorted(length_counts.items(), key=lambda pair: int(pair[0]))),
        item_exposure_counts=dict(sorted(exposures.items())),
        estimate_mean_difference=math.fsum(differences) / completed,
        estimate_mae=math.fsum(abs_diff) / completed,
        estimate_rmse=math.sqrt(math.fsum(value * value for value in differences) / completed),
        estimate_max_absolute_difference=max(abs_diff),
        standard_error_mae=math.fsum(abs_se_diff) / completed,
        standard_error_max_absolute_difference=max(abs_se_diff),
    )


def build_report(profile_path: Path, manifest_path: Path, responses_path: Path) -> dict[str, object]:
    profile = _load_profile(profile_path, manifest_path)
    rows, response_sha256 = _read_complete_responses(responses_path, profile)
    aggregate = _run_aggregate(profile, rows)
    source = json.loads(profile.source_metadata_json)
    model = json.loads(profile.model_metadata_json)
    provenance = json.loads(profile.provenance_metadata_json)
    return {
        "format_version": FORMAT_VERSION,
        "status": "COMPLETED_AGGREGATE_ONLY" if not aggregate.failures else "COMPLETED_WITH_FAILURES_AGGREGATE_ONLY",
        "research_only": True,
        "publication_status": "not_approved",
        "psychological_interpretation_allowed": False,
        "scope": "fixed_full_eight_item_PROMIS_pediatric_anxiety_reference_only",
        "comparison": {
            "kind": "same_records_full_bank_CAT_vs_independent_full_bank_EAP_numerical_consistency",
            "uses_observed_response_matrix": True,
            "calibration_evaluation_split": "none; profile uses published parameters and declares no local fit or held-out split",
            "shortening_evaluated": False,
            "full_bank_items_per_record": 8,
            "quadrature": {
                "method": "composite_trapezoid",
                "grid_steps": GRID_STEPS,
                "theta_interval": [-4.0, 4.0],
                "prior": {"family": "Gaussian", "mean": 0.0, "sd": 1.0},
            },
        },
        "source": {
            "profile_id": profile.profile_id,
            "instrument_id": profile.instrument_id,
            "profile_sha256": profile.file_sha256,
            "manifest_sha256": profile.manifest_sha256,
            "response_matrix_sha256": response_sha256,
            "response_records": aggregate.records,
            "items": len(profile.items),
            "parameter_origin": model["parameter_origin"],
            "parameter_version": model["parameter_version"],
            "parameter_precision": model["precision"],
            "response_population": source["observed_response_source"]["population"],
            "response_sample": provenance["coverage_sample"],
        },
        "aggregate": {
            "records_started": aggregate.records,
            "full_bank_comparisons_completed": aggregate.completed,
            "comparison_denominator": aggregate.completed,
            "failure_counts": dict(aggregate.failures),
            "stop_reason_counts": dict(aggregate.stop_reasons),
            "test_length_counts": dict(aggregate.test_length_counts),
            "item_exposure_counts": dict(aggregate.item_exposure_counts),
            "cat_vs_independent_full_bank_eap": {
                "mean_signed_difference": aggregate.estimate_mean_difference,
                "mae": aggregate.estimate_mae,
                "rmse": aggregate.estimate_rmse,
                "max_absolute_difference": aggregate.estimate_max_absolute_difference,
                "standard_error_mae": aggregate.standard_error_mae,
                "standard_error_max_absolute_difference": aggregate.standard_error_max_absolute_difference,
            },
            "individual_theta_or_response_rows_written": False,
        },
        "limitations": [
            "the 800 records are a seeded complete-case sample from a US general-population caregiver/child panel; not school-based or representative of Chinese secondary-school students",
            "the profile explicitly declares no calibration/evaluation split; this is not held-out validation",
            "all eight bank items are administered, so the result does not evaluate adaptive shortening or item reduction",
            "CAT estimates and reference use the same observed records, published parameters, scoring map, and prior; differences are numerical consistency only, not prediction or measurement accuracy",
            "published parameters are rounded to two decimals; uncertainty in their original estimation is not propagated",
            "the research profile is not approved for psychological interpretation, school administration, a production item bank, or clinical decisions",
            "only aggregate metrics are retained; no row identifiers, responses, individual theta estimates, or per-record errors are written",
        ],
    }


def write_report(report: Mapping[str, object], output_path: Path) -> None:
    output = output_path.resolve()
    if output.exists():
        raise FullBankComparisonError("OUTPUT_ALREADY_EXISTS", "refusing to replace an existing report")
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    try:
        with output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except OSError as exc:
        raise FullBankComparisonError("OUTPUT_WRITE_FAILED", "aggregate report could not be created exclusively") from exc


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(args.profile, args.manifest, args.responses)
    write_report(report, args.output)
    aggregate = report["aggregate"]
    metrics = aggregate["cat_vs_independent_full_bank_eap"]
    print(json.dumps({
        "status": report["status"],
        "records": aggregate["records_started"],
        "completed": aggregate["full_bank_comparisons_completed"],
        "mae": metrics["mae"],
        "rmse": metrics["rmse"],
        "report_path": str(args.output.resolve()),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
