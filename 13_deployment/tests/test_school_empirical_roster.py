"""Unit checks use tiny fictional rosters plus held-out metadata fixtures only."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_empirical_roster as roster


def _research_manifest(path: Path) -> Path:
    source_population = (
        "Self-selected SAPA Project online respondents from the source collection period; "
        "not a school, high-school, university-representative, clinical, or diagnostic sample."
    )
    manifest = {
        "format_version": "research-response.v1",
        "research_only": True,
        "publication_status": "not_approved_for_publication_or_operational_use",
        "psychological_interpretation_allowed": False,
        "not_created": {"scores_or_interpretations": True},
        "source": {
            "reference": "https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/C40K1U",
            "sha256": hashlib.sha256(b"source metadata fixture").hexdigest(),
            "license": "CC0-1.0",
            "population": source_population,
        },
        "response_columns": [f"q_{index:03d}" for index in range(99)],
        "sampling": {
            "source_record_count": 128_464,
            "selected_record_count": 10_800,
            "calibration_record_count": 10_000,
            "evaluation_record_count": 800,
            "source_row_identifiers_written": False,
            "splits_disjoint": True,
        },
        "output_integrity": {
            "evaluation.csv": {
                "sha256": hashlib.sha256(b"held-out hash metadata fixture").hexdigest(),
                "record_count": 800,
            }
        },
    }
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _spec(tmp_path: Path, research_manifest: Path, **overrides) -> roster.ScenarioSpec:
    values = {
        "scenario_id": "TEST_ROSTER_A",
        "output_dir": tmp_path / "scenario-a",
        "research_manifest": research_manifest,
        "count": 7,
        "class_size": 3,
        "seed": 41,
    }
    values.update(overrides)
    return roster.ScenarioSpec(**values)


def test_generates_small_fictional_batches_and_metadata_only_heldout_reference(tmp_path: Path) -> None:
    research = _research_manifest(tmp_path / "heldout-manifest-fixture.json")
    output = tmp_path / "scenario-a"

    result = roster.generate_roster(_spec(tmp_path, research))

    assert result["fictional"] is True
    assert result["student_count"] == 7
    assert result["class_count"] == result["batch_count"] == 3
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["scenario"]["fictional"] is True
    assert manifest["scenario"]["student_count"] == 7
    assert manifest["scenario"]["class_size"] == 3
    assert manifest["account_import_contract"]["csv_header"] == ["login_name", "display_name", "role"]
    assert manifest["account_import_contract"]["maximum_rows_per_batch"] == 100
    assert manifest["account_import_contract"]["maximum_csv_bytes"] == 500 * 1024
    assert manifest["account_import_contract"]["password_column_present"] is False

    batches = manifest["class_batches"]
    assert [batch["row_count"] for batch in batches] == [3, 3, 1]
    assert all(batch["class_ref"] is None for batch in batches)
    logins: list[str] = []
    for batch in batches:
        content = (output / batch["csv_file"]).read_bytes()
        assert len(content) <= 500 * 1024
        assert hashlib.sha256(content).hexdigest() == batch["sha256"]
        with (output / batch["csv_file"]).open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        assert len(rows) == batch["row_count"] <= 100
        assert rows and list(rows[0]) == ["login_name", "display_name", "role"]
        assert all(row["role"] == "student" for row in rows)
        assert all(row["display_name"].startswith("合成学生-") for row in rows)
        logins.extend(row["login_name"] for row in rows)
    assert len(set(logins)) == 7
    assert all(re.fullmatch(r"SYNTHETIC_TEST_ROSTER_A_STUDENT_[0-9]{6}", name) for name in logins)

    reference = manifest["research_reference"]
    assert reference["manifest_path"] == str(research.resolve())
    assert reference["evaluation_record_count"] == 800
    assert reference["source_record_count"] == 128_464
    assert reference["source_response_column_count"] == 99
    assert reference["source_population_boundary"].startswith("Self-selected SAPA Project")
    assert "not a school" in reference["source_population_boundary"]
    assert reference["used_to_generate_accounts"] is False
    assert reference["response_rows_copied_to_roster"] is False
    assert reference["account_to_response_row_mapping_created"] is False
    assert reference["source_population_relabelled"] is False
    assert manifest["execution_boundary"]["database_writes_performed"] is False
    assert manifest["execution_boundary"]["api_writes_performed"] is False
    assert manifest["execution_boundary"]["accounts_imported"] is False
    assert manifest["execution_boundary"]["professional_review_or_school_population_approval_claimed"] is False


def test_same_scenario_inputs_produce_byte_identical_batches_and_manifest(tmp_path: Path) -> None:
    research = _research_manifest(tmp_path / "heldout-manifest-fixture.json")
    first = _spec(tmp_path, research, output_dir=tmp_path / "first")
    second = _spec(tmp_path, research, output_dir=tmp_path / "second")

    roster.generate_roster(first)
    roster.generate_roster(second)

    for filename in ("class_001.csv", "class_002.csv", "class_003.csv", "manifest.json"):
        assert (tmp_path / "first" / filename).read_bytes() == (tmp_path / "second" / filename).read_bytes()


def test_rejects_over_limit_class_size_and_existing_destination(tmp_path: Path) -> None:
    research = _research_manifest(tmp_path / "heldout-manifest-fixture.json")
    with pytest.raises(roster.RosterScenarioError) as error:
        roster.generate_roster(_spec(tmp_path, research, class_size=101))
    assert error.value.code == "invalid_parameter"

    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    with pytest.raises(roster.RosterScenarioError) as error:
        roster.generate_roster(_spec(tmp_path, research, output_dir=output))
    assert error.value.code == "output_exists"
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_rejects_population_promotions_and_non_800_heldout_manifests(tmp_path: Path) -> None:
    research = _research_manifest(tmp_path / "bad-population.json")
    manifest = json.loads(research.read_text(encoding="utf-8"))
    manifest["source"]["population"] = "high-school students"
    research.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(roster.RosterScenarioError) as error:
        roster.generate_roster(_spec(tmp_path, research))
    assert error.value.code == "research_manifest_boundary_mismatch"
    assert not (tmp_path / "scenario-a").exists()

    research = _research_manifest(tmp_path / "bad-count.json")
    manifest = json.loads(research.read_text(encoding="utf-8"))
    manifest["sampling"]["evaluation_record_count"] = 799
    research.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(roster.RosterScenarioError) as error:
        roster.generate_roster(_spec(tmp_path, research, output_dir=tmp_path / "other"))
    assert error.value.code == "research_manifest_boundary_mismatch"
    assert not (tmp_path / "other").exists()


def test_cli_defaults_to_800_but_requires_explicit_scenario_and_paths(tmp_path: Path) -> None:
    research = _research_manifest(tmp_path / "heldout-manifest-fixture.json")
    args = roster._build_parser().parse_args(
        ["--scenario-id", "ONE", "--output-dir", str(tmp_path / "out"), "--research-manifest", str(research)]
    )
    assert args.count == 800
    assert args.class_size == 100
    assert args.seed == 20261013
