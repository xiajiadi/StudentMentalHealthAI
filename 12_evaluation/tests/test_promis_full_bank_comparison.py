import csv
import hashlib
import json
import random
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from promis_full_bank_comparison import (
    FullBankComparisonError,
    _independent_full_bank_eap,
    _parse_args,
    _read_seeded_complement,
    _serialize_response_rows,
)


def _symmetric_eight_item_profile():
    items = tuple(
        SimpleNamespace(
            qid=f"ITEM_{index}",
            a=1.0,
            thresholds=(-1.5, -0.5, 0.5, 1.5),
            key_direction="positive",
        )
        for index in range(8)
    )
    return SimpleNamespace(items=items, source_categories=(1, 2, 3, 4, 5))


def test_full_bank_reference_is_symmetric_for_symmetric_parameters_and_middle_answers():
    profile = _symmetric_eight_item_profile()

    theta, standard_error = _independent_full_bank_eap(profile, (3,) * 8)

    assert abs(theta) < 1e-12
    assert 0.0 < standard_error < 1.0


def test_full_bank_reference_reflects_all_low_vs_all_high_categories():
    profile = _symmetric_eight_item_profile()

    low_theta, _ = _independent_full_bank_eap(profile, (1,) * 8)
    high_theta, _ = _independent_full_bank_eap(profile, (5,) * 8)

    assert low_theta < 0.0 < high_theta
    assert high_theta == pytest.approx(-low_theta, abs=1e-12)


def test_full_bank_reference_rejects_out_of_scale_observations():
    profile = _symmetric_eight_item_profile()

    with pytest.raises(FullBankComparisonError) as error:
        _independent_full_bank_eap(profile, (1, 2, 3, 4, 5, 1, 2, 9))

    assert error.value.code == "RESPONSE_CATEGORY_INVALID"


def _write_source_fixture(path, columns, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _seeded_split_fixture(tmp_path):
    columns = tuple(f"ITEM_{index}" for index in range(8))
    labels = ["Never", "Almost Never", "Sometimes", "Often", "Almost Always"]
    label_to_raw = dict(zip(labels, range(1, 6), strict=True))
    raw_rows = []
    numeric_rows = []
    complete_rows = []
    for row_index in range(1005):
        raw = {
            column: labels[(row_index + column_index) % len(labels)]
            for column_index, column in enumerate(columns)
        }
        numeric = {column: str(label_to_raw[raw[column]]) for column in columns}
        if row_index >= 958:
            raw[columns[0]] = ""
            numeric[columns[0]] = "NA"
        else:
            complete_rows.append(numeric)
        raw_rows.append(raw)
        numeric_rows.append(numeric)

    source_path = tmp_path / "source.csv"
    _write_source_fixture(source_path, columns, raw_rows)
    selected_indices = set(random.Random(2026101403).sample(range(958), 800))
    selected = [row for index, row in enumerate(complete_rows) if index in selected_indices]
    complement = [row for index, row in enumerate(complete_rows) if index not in selected_indices]
    selected_path = tmp_path / "selected-800.csv"
    selected_path.write_bytes(_serialize_response_rows(columns, selected))
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    numeric_sha = hashlib.sha256(_serialize_response_rows(columns, numeric_rows)).hexdigest()
    selected_sha = hashlib.sha256(selected_path.read_bytes()).hexdigest()
    metadata = {
        "source_data": {"observed_response_source": {"response_only_csv_sha256": source_sha}},
        "response_scale": {"source_labels": labels, "source_raw_codes": list(range(1, 6))},
        "provenance": {
            "numeric_1_5_csv_sha256": numeric_sha,
            "complete_observed_800_csv_sha256": selected_sha,
            "coverage_sample": {
                "seed": 2026101403,
                "complete_source_rows": 958,
                "selected_rows": 800,
                "complete_rows_not_selected": 158,
                "algorithm": "Python random.Random(seed).sample without replacement over ordered complete-case rows",
            },
        },
    }
    profile = SimpleNamespace(
        items=tuple(SimpleNamespace(qid=column) for column in columns),
        raw_metadata_json=json.dumps(metadata),
    )
    expected = [tuple(int(row[column]) for column in columns) for row in complement]
    return profile, source_path, selected_path, expected


def test_seeded_complement_is_exact_and_excludes_selected_800(tmp_path):
    profile, source_path, selected_path, expected = _seeded_split_fixture(tmp_path)

    rows, provenance = _read_seeded_complement(source_path, selected_path, profile)

    assert rows == expected
    assert len(rows) == 158
    assert provenance["source_rows"] == 1005
    assert provenance["complete_source_rows"] == 958
    assert provenance["selected_rows"] == 800
    assert provenance["complement_rows"] == 158
    assert provenance["split_indices_disjoint"] is True
    assert provenance["individual_row_indices_or_hashes_written"] is False


def test_seeded_complement_rejects_selected_matrix_drift(tmp_path):
    profile, source_path, selected_path, _ = _seeded_split_fixture(tmp_path)
    selected_path.write_bytes(selected_path.read_bytes() + b"\n")

    with pytest.raises(FullBankComparisonError) as error:
        _read_seeded_complement(source_path, selected_path, profile)

    assert error.value.code == "SELECTED_RESPONSE_HASH_MISMATCH"


def test_cli_keeps_original_800_mode_and_requires_complete_complement_inputs():
    legacy = _parse_args(
        [
            "--profile", "profile.json",
            "--manifest", "manifest.json",
            "--responses", "complete_observed_800.csv",
            "--output", "summary.json",
        ]
    )
    complement = _parse_args(
        [
            "--profile", "profile.json",
            "--manifest", "manifest.json",
            "--source-responses", "source.csv",
            "--selected-responses", "complete_observed_800.csv",
            "--output", "summary.json",
        ]
    )

    assert legacy.mode == "legacy"
    assert complement.mode == "complement"
