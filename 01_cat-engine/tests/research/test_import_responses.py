"""Privacy and reproducibility checks for the isolated research importer."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from cat_engine.research.import_responses import (
    ImportErrorSafe,
    ImportSpec,
    MINIMUM_EVALUATION_SIZE,
    _cleanup_owned_temporary_directory,
    _read_and_sample,
    import_responses,
    main,
    sha256_file,
)


def write_source(path: Path, rows: list[dict[str, str]], *, delimiter: str = ",") -> None:
    headers = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter=delimiter, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def make_spec(
    source: Path,
    output: Path,
    *,
    response_columns: tuple[str, ...] = ("R1", "R2"),
    calibration_size: int = 2,
    evaluation_size: int = MINIMUM_EVALUATION_SIZE,
    seed: int = 47,
    delimiter: str = ",",
) -> ImportSpec:
    return ImportSpec(
        source_path=source,
        output_dir=output,
        delimiter=delimiter,
        response_columns=response_columns,
        ordinal_values=(1, 2, 3, 4, 5),
        missing_codes=("NA", "-9"),
        expected_source_sha256=sha256_file(source),
        source_reference="synthetic://importer-tests/ordinal-responses",
        source_license="CC0-1.0",
        source_population="synthetic importer test records; no real population claim",
        source_language="en-US",
        source_version="synthetic-test-v1",
        seed=seed,
        calibration_size=calibration_size,
        evaluation_size=evaluation_size,
    )


def read_response_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_unknown_pii_and_text_columns_are_dropped_and_missing_is_preserved(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    rows = [
        {
            "participantID": f"SYNTHETIC_PERSON_{index:04d}",
            "age": str(15 + index % 4),
            "sex": "SYNTHETIC_X",
            "responseDate": f"2099-01-{index % 28 + 1:02d}",
            "freeText": f"SYNTHETIC_TEXT_SENTINEL_{index:04d}",
            "R1": str(index % 5 + 1),
            "R2": "NA" if index % 2 else "-9",
        }
        for index in range(805)
    ]
    write_source(source, rows)
    output = tmp_path / "result"

    summary = import_responses(make_spec(source, output, calibration_size=2, evaluation_size=800))

    assert summary["calibration_records"] == 2
    assert summary["evaluation_records"] == 800
    for file_name in ("calibration.csv", "evaluation.csv"):
        response_file = output / file_name
        assert response_file.exists()
        assert response_file.read_text(encoding="utf-8").splitlines()[0] == "R1,R2"
        content = response_file.read_text(encoding="utf-8")
        assert "SYNTHETIC_PERSON_" not in content
        assert "SYNTHETIC_TEXT" not in content
        assert "responseDate" not in content
        assert "age" not in content
        assert "sex" not in content

    all_output = "".join(path.read_text(encoding="utf-8") for path in output.iterdir() if path.is_file())
    assert "SYNTHETIC_PERSON_" not in all_output
    assert "SYNTHETIC_TEXT_SENTINEL" not in all_output
    assert "participantID" not in all_output
    assert "responseDate" not in all_output
    assert sum(row["R2"] == "" for row in read_response_rows(output / "calibration.csv")) + sum(
        row["R2"] == "" for row in read_response_rows(output / "evaluation.csv")
    ) == 802

    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["research_only"] is True
    assert manifest["psychological_interpretation_allowed"] is False
    assert manifest["source"]["sha256"] == sha256_file(source)
    assert manifest["source"]["license"] == "CC0-1.0"
    assert manifest["source"]["language"] == "en-US"
    assert manifest["source"]["version"] == "synthetic-test-v1"
    assert manifest["sampling"]["excluded_source_column_count"] == 5
    assert manifest["sampling"]["source_row_identifiers_written"] is False
    assert manifest["aggregate_missing_cells"]["source_by_response_column"]["R2"] == 805
    assert manifest["missing_policy"]["additional_missing_codes"] == ["NA", "-9"]
    for file_name in ("calibration.csv", "evaluation.csv"):
        assert manifest["output_integrity"][file_name]["sha256"] == sha256_file(output / file_name)
    assert manifest["not_created"]["calibrated_parameters"] is True
    assert manifest["not_created"]["published_scale"] is True


def test_seeded_random_sample_is_reproducible_disjoint_and_not_first_records(tmp_path: Path) -> None:
    source = tmp_path / "many.csv"
    rows = [
        {"R1": str((index % 5) + 1), "R2": str(((index + 1) % 5) + 1)}
        for index in range(1, 851)
    ]
    write_source(source, rows)
    spec = make_spec(source, tmp_path / "first", calibration_size=10, evaluation_size=800, seed=735)
    left = _read_and_sample(spec, sample_size=810)
    right = _read_and_sample(spec, sample_size=810)

    assert left.records == right.records
    calibration = left.records[:10]
    evaluation = left.records[10:]
    calibration_ids = {record.source_record_number for record in calibration}
    evaluation_ids = {record.source_record_number for record in evaluation}
    assert calibration_ids.isdisjoint(evaluation_ids)
    assert len(calibration_ids | evaluation_ids) == 810
    assert calibration_ids | evaluation_ids != set(range(1, 811))

    first_summary = import_responses(spec)
    second_spec = make_spec(source, tmp_path / "second", calibration_size=10, evaluation_size=800, seed=735)
    import_responses(second_spec)
    for file_name in ("calibration.csv", "evaluation.csv", "manifest.json"):
        assert (tmp_path / "first" / file_name).read_bytes() == (tmp_path / "second" / file_name).read_bytes()
    assert first_summary["source_records"] == 850


def test_tsv_source_is_supported(tmp_path: Path) -> None:
    source = tmp_path / "source.tsv"
    rows = [{"R1": str(index % 5 + 1), "R2": str((index + 1) % 5 + 1)} for index in range(802)]
    write_source(source, rows, delimiter="\t")
    spec = make_spec(source, tmp_path / "result", calibration_size=2, evaluation_size=800, delimiter="\t")

    summary = import_responses(spec)

    assert summary["evaluation_records"] == 800
    assert (tmp_path / "result" / "calibration.csv").read_text(encoding="utf-8").splitlines()[0] == "R1,R2"


def test_illegal_response_fails_closed_without_output_or_echoing_value(tmp_path: Path) -> None:
    source = tmp_path / "invalid.csv"
    rows = [{"R1": str(index % 5 + 1), "R2": "3"} for index in range(803)]
    rows[401]["R1"] = "PRIVATE_VALUE_SENTINEL"
    write_source(source, rows)
    output = tmp_path / "result"

    with pytest.raises(ImportErrorSafe, match="outside the allowed ordinal values") as error:
        import_responses(make_spec(source, output, calibration_size=2, evaluation_size=800))

    assert error.value.code == "invalid_ordinal_response"
    assert "PRIVATE_VALUE_SENTINEL" not in str(error.value)
    assert not output.exists()
    assert list(tmp_path.glob(".research-import-*")) == []


def test_source_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    write_source(source, [{"R1": "1", "R2": "2"}, {"R1": "3", "R2": "4"}])
    spec = make_spec(source, tmp_path / "result", calibration_size=2, evaluation_size=800)
    wrong_hash = hashlib.sha256(b"different source").hexdigest()
    spec = ImportSpec(**{**spec.__dict__, "expected_source_sha256": wrong_hash})

    with pytest.raises(ImportErrorSafe, match="does not match") as error:
        import_responses(spec)

    assert error.value.code == "source_hash_mismatch"
    assert not spec.output_dir.exists()


def test_id_or_demographic_fields_cannot_be_explicitly_allowlisted(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    write_source(source, [{"participantID": "1", "R1": "2"}])
    spec = make_spec(source, tmp_path / "result", response_columns=("participantID",), calibration_size=2, evaluation_size=800)

    with pytest.raises(ImportErrorSafe) as error:
        import_responses(spec)

    assert error.value.code == "blocked_response_column"
    assert not spec.output_dir.exists()


def test_default_cli_contract_requires_at_least_800_evaluation_records(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    write_source(source, [{"R1": "1", "R2": "2"}])
    spec = make_spec(source, tmp_path / "result", calibration_size=1, evaluation_size=MINIMUM_EVALUATION_SIZE - 1)

    with pytest.raises(ImportErrorSafe) as error:
        import_responses(spec)

    assert error.value.code == "evaluation_below_minimum"
    assert not spec.output_dir.exists()


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("seed", True, "invalid_seed"),
        ("seed", 2.5, "invalid_seed"),
        ("calibration_size", False, "invalid_calibration_size"),
        ("calibration_size", 2.5, "invalid_calibration_size"),
        ("evaluation_size", True, "invalid_evaluation_size"),
        ("evaluation_size", 800.5, "invalid_evaluation_size"),
    ],
)
def test_seed_and_split_sizes_require_strict_integers(
    tmp_path: Path,
    field: str,
    value: bool | float,
    expected_code: str,
) -> None:
    source = tmp_path / "source.csv"
    write_source(source, [{"R1": "1", "R2": "2"}])
    spec = replace(make_spec(source, tmp_path / "result"), **{field: value})

    with pytest.raises(ImportErrorSafe) as error:
        import_responses(spec)

    assert error.value.code == expected_code
    assert not spec.output_dir.exists()


def test_temporary_cleanup_refuses_directories_outside_its_owned_scope(tmp_path: Path) -> None:
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    sentinel = unrelated / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(ImportErrorSafe) as error:
        _cleanup_owned_temporary_directory(unrelated, output_parent)

    assert error.value.code == "cleanup_failed"
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    owned_temporary = output_parent / ".research-import-test"
    owned_temporary.mkdir()
    (owned_temporary / "temporary.txt").write_text("temporary", encoding="utf-8")
    _cleanup_owned_temporary_directory(owned_temporary, output_parent)
    assert not owned_temporary.exists()


def test_temporary_cleanup_refuses_reparse_point_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    output_parent = tmp_path / "output"
    output_parent.mkdir()
    owned_temporary = output_parent / ".research-import-reparse"
    owned_temporary.mkdir()
    sentinel = owned_temporary / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")
    original_lstat = Path.lstat

    def reparse_lstat(path: Path) -> object:
        if path == owned_temporary:
            return SimpleNamespace(st_mode=0o040755, st_file_attributes=0x400)
        return original_lstat(path)

    monkeypatch.setattr(Path, "lstat", reparse_lstat)

    with pytest.raises(ImportErrorSafe) as error:
        _cleanup_owned_temporary_directory(owned_temporary, output_parent)

    assert error.value.code == "cleanup_failed"
    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_cli_stdout_reports_counts_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "source.csv"
    rows = [{"R1": "1", "R2": "5", "participantID": f"SYNTHETIC_ONLY_{index}"} for index in range(805)]
    write_source(source, rows)
    args = [
        "--source", str(source),
        "--output-dir", str(tmp_path / "result"),
        "--delimiter", "comma",
        "--response-column", "R1",
        "--response-column", "R2",
        "--ordinal-values", "1", "2", "3", "4", "5",
        "--source-sha256", sha256_file(source),
        "--source-reference", "doi:10.7910/DVN/IBWSUD",
        "--source-license", "CC0-1.0",
        "--source-population", "synthetic test records",
        "--source-language", "en-US",
        "--source-version", "test-v1",
        "--seed", "7",
        "--calibration-size", "2",
        "--evaluation-size", "800",
    ]

    assert main(args) == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["status"] == "ok"
    assert summary["calibration_records"] == 2
    assert summary["evaluation_records"] == 800
    assert captured.err == ""
    assert "SYNTHETIC_ONLY" not in captured.out
    assert "1,5" not in captured.out
    assert "R1" not in captured.out
