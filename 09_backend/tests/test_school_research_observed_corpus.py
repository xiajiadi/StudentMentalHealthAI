from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from smhai_backend.domains.school_research.observed_corpus import (
    ObservedCorpusError,
    load_observed_response_corpus,
)
from smhai_backend.domains.school_research.trust import (
    ParameterOrigin,
    PublicationStatusProjection,
    ResearchProfileRegistry,
    ResearchProfileRegistryEntry,
    TrustedResearchProfile,
)

PROFILE_REF = "promis-pediatric-anxiety-8-item-subset-20261014-r1"
PROFILE_DIR = Path(
    r"D:\Dev\datasets\psynova-public-research\research-profiles\promis-pediatric-anxiety-8-item-subset-20261014-r1"
)
EXPECTED_PROFILE_SHA256 = "a2720adf10496f495efe21262de0e1890650847a84aff770aa025e9da825acf3"
EXPECTED_MANIFEST_SHA256 = "984d395c29c26c1ce728d97790abf99d583ef47518ee6e058e067c8e8c15f524"


def test_pinned_public_promis_response_corpus_loads_without_exposing_rows() -> None:
    profile_path = PROFILE_DIR / "profile.json"
    manifest_path = PROFILE_DIR / "manifest.json"
    response_path = PROFILE_DIR / "complete_observed_800.csv"
    if not all(path.is_file() for path in (profile_path, manifest_path, response_path)):
        pytest.skip("pinned external PROMIS research artifact is not staged on this host")

    profile_bytes = profile_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    assert hashlib.sha256(profile_bytes).hexdigest() == EXPECTED_PROFILE_SHA256
    assert hashlib.sha256(manifest_bytes).hexdigest() == EXPECTED_MANIFEST_SHA256
    profile_doc = json.loads(profile_bytes.decode("utf-8"))
    registry = ResearchProfileRegistry(
        allowed_root=PROFILE_DIR,
        entries=(
            ResearchProfileRegistryEntry(
                profile_ref=PROFILE_REF,
                profile_schema="psynova.research-profile.v3",
                expected_profile_sha256=EXPECTED_PROFILE_SHA256,
                expected_manifest_sha256=EXPECTED_MANIFEST_SHA256,
                source_family=profile_doc["instrument_family"],
                parameter_origin=ParameterOrigin.PUBLISHED_ROUNDED_REFERENCE,
                profile_path=profile_path,
                manifest_path=manifest_path,
            ),
        ),
    )
    trusted = registry.load(PROFILE_REF)
    corpus = load_observed_response_corpus(trusted)

    assert corpus.row_count == 800
    assert "_rows=" not in repr(corpus)
    assert "response_csv_sha256=" not in repr(corpus)
    # Assert each source row has a valid category through the boolean interface;
    # never print or retain the actual public response value in test output.
    for item in profile_doc["items"]:
        for case_index in range(corpus.row_count):
            assert any(
                corpus.matches(case_index, item["item_id"], value)
                for value in range(1, 6)
            )
    assert not corpus.matches(-1, profile_doc["items"][0]["item_id"], 1)
    assert not corpus.matches(True, profile_doc["items"][0]["item_id"], 1)
    assert not corpus.matches(0, "unknown-item", 1)
    assert not corpus.matches(0, profile_doc["items"][0]["item_id"], True)


def test_response_match_is_bound_to_case_and_item(tmp_path: Path) -> None:
    trusted, profile_sha, manifest_sha = _write_bundle(tmp_path)
    corpus = load_observed_response_corpus(trusted)

    assert corpus.matches(0, "ITEM_0", 1)
    assert not corpus.matches(0, "ITEM_0", 2)
    assert not corpus.matches(0, "ITEM_1", 1)
    assert corpus.matches(1, "ITEM_0", 2)
    assert not corpus.matches(800, "ITEM_0", 1)
    with pytest.raises(TypeError):
        corpus._column_by_item["ITEM_0"] = 5
    with pytest.raises((AttributeError, TypeError)):
        corpus.row_count = 1


@pytest.mark.parametrize(
    "response_bytes",
    [
        b"Q0,Q0,Q2,Q3,Q4,Q5,Q6,Q7\n" + b"1,1,1,1,1,1,1,1\n" * 800,
        b"Q0,Q1,Q2,Q3,Q4,Q5,Q6,Q7\n" + b"1,1,1,1,1,1,1\n" * 800,
        b"Q0,Q1,Q2,Q3,Q4,Q5,Q6,Q7\n" + b"1,1,1,1,1,1,1,6\n" * 800,
        b"Q0,Q1,Q2,Q3,Q4,Q5,Q6,Q7\n" + b"1,1,1,1,1,1,1,\n" * 800,
        b"Q0,Q1,Q2,Q3,Q4,Q5,Q6,Q7\n" + b"1,1,1,1,1,1,1,1\n" * 799,
        b"Q0,Q1,Q2,Q3,Q4,Q5,Q6,Q7\n" + b"1,1,1,1,1,1,1,1\n" * 801,
        b"Q0,Q1,Q2,Q3,Q4,Q5,Q6,Q7\n" + b"1,1,1,1,1,1,1,\xff\n" * 800,
    ],
    ids=[
        "duplicate header",
        "short rows",
        "out-of-range",
        "missing response",
        "short file",
        "long file",
        "invalid utf8",
    ],
)
def test_invalid_response_matrix_fails_closed(tmp_path: Path, response_bytes: bytes) -> None:
    trusted, _profile_sha, _manifest_sha = _write_bundle(
        tmp_path, response_bytes=response_bytes
    )
    with pytest.raises(ObservedCorpusError):
        load_observed_response_corpus(trusted)


def test_wrong_registry_pin_or_changed_file_fails_without_details(tmp_path: Path) -> None:
    trusted, _profile_sha, _manifest_sha = _write_bundle(tmp_path)
    bad_profile_pin = replace(trusted, profile_sha256="f" * 64)
    with pytest.raises(ObservedCorpusError) as wrong_profile:
        load_observed_response_corpus(bad_profile_pin)
    assert wrong_profile.value.code == "profile_pin_mismatch"
    assert "Q0" not in str(wrong_profile.value)
    assert "1" not in str(wrong_profile.value)
    bad_manifest_pin = replace(trusted, manifest_sha256="e" * 64)
    with pytest.raises(ObservedCorpusError) as wrong_manifest:
        load_observed_response_corpus(bad_manifest_pin)
    assert wrong_manifest.value.code == "profile_pin_mismatch"

    response_path = tmp_path / "complete_observed_800.csv"
    response_path.write_bytes(response_path.read_bytes() + b"\n")
    with pytest.raises(ObservedCorpusError) as changed_file:
        load_observed_response_corpus(trusted)
    assert changed_file.value.code == "response_hash_mismatch"
    assert str(response_path) not in str(changed_file.value)


def test_oversized_response_file_fails_closed(tmp_path: Path) -> None:
    trusted, _profile_sha, _manifest_sha = _write_bundle(tmp_path)
    response_path = tmp_path / "complete_observed_800.csv"
    response_path.write_bytes(b"x" * (256 * 1024 + 1))
    with pytest.raises(ObservedCorpusError) as oversized:
        load_observed_response_corpus(trusted)
    assert oversized.value.code == "source_artifact_invalid"


def test_unpinned_manifest_filename_is_rejected(tmp_path: Path) -> None:
    trusted, _profile_sha, _manifest_sha = _write_bundle(
        tmp_path, manifest_path="other.csv"
    )
    with pytest.raises(ObservedCorpusError) as manifest_error:
        load_observed_response_corpus(trusted)
    assert manifest_error.value.code == "manifest_response_pin_invalid"


def _write_bundle(
    root: Path,
    *,
    response_bytes: bytes | None = None,
    manifest_path: str = "complete_observed_800.csv",
) -> tuple[TrustedResearchProfile, str, str]:
    root.mkdir(parents=True, exist_ok=True)
    source_columns = [f"Q{index}" for index in range(8)]
    items = [
        {"item_id": f"ITEM_{index}", "source_column": source_column}
        for index, source_column in enumerate(source_columns)
    ]
    profile: dict[str, object] = {
        "schema": "psynova.research-profile.v3",
        "profile_id": "test-promis-v3",
        "profile_type": "research_only_candidate",
        "research_only": True,
        "publication_status": "not_approved",
        "human_curated": False,
        "psychological_interpretation_allowed": False,
        "items": items,
        "provenance": {"complete_observed_800_csv_sha256": "0" * 64},
    }
    responses = response_bytes or _valid_csv(source_columns)
    response_sha = hashlib.sha256(responses).hexdigest()
    profile["provenance"] = {"complete_observed_800_csv_sha256": response_sha}
    profile_bytes = json.dumps(profile, separators=(",", ":")).encode("utf-8")
    profile_sha = hashlib.sha256(profile_bytes).hexdigest()
    manifest = {
        "profile_sha256": profile_sha,
        "profile_json_sha256": profile_sha,
        "no_person_response_hashes_or_identifiers": True,
        "no_scores_or_person_parameters": True,
        "numeric_response_csv": {
            "path": "responses_numeric_1_5.csv",
            "sha256": "a" * 64,
            "rows": 900,
            "columns": source_columns,
            "partial_rows_NA_retained": 100,
            "category_counts": {},
        },
        "complete_observed_800": {
            "path": manifest_path,
            "sha256": response_sha,
            "rows": 800,
            "complete_source_rows": 900,
            "not_selected_complete_rows": 100,
            "seed": 20261014,
            "sampling": "synthetic test rows",
            "python_implementation": "CPython",
            "python_version": "3.14",
        },
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":")).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    (root / "complete_observed_800.csv").write_bytes(responses)
    trusted = TrustedResearchProfile(
        profile_ref="test-promis-v3",
        profile_schema="psynova.research-profile.v3",
        profile_sha256=profile_sha,
        manifest_sha256=manifest_sha,
        source_family="PROMIS_PEDIATRIC_ANXIETY_8_ITEM_SUBSET",
        parameter_origin=ParameterOrigin.PUBLISHED_ROUNDED_REFERENCE,
        publication_status_projection=PublicationStatusProjection.NOT_APPROVED,
        repository_schema_compatible=True,
        raw_profile_bytes=profile_bytes,
        raw_manifest_bytes=manifest_bytes,
        artifact_root=root,
    )
    return trusted, profile_sha, manifest_sha


def _valid_csv(source_columns: list[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(source_columns)
    for row in range(800):
        writer.writerow([str((row + column) % 5 + 1) for column in range(8)])
    return buffer.getvalue().encode("utf-8")
