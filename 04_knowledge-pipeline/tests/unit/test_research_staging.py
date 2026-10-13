from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from knowledge_pipeline.config import PipelineConfig
from knowledge_pipeline.domain.source import SourceRecord, SourceRequest
from knowledge_pipeline.parsers.markdown_parser import MarkdownCuratedParser
from knowledge_pipeline.research_staging import ResearchStagingError, stage_research_sources


def _write_fixture_manifest(root: Path, *, include_metadata_only: bool = True) -> tuple[Path, bytes]:
    root.mkdir(parents=True, exist_ok=True)
    body = b"# Source excerpt heading\n\nVisible source text remains unchanged.\n"
    (root / "excerpt.md").write_bytes(body)
    staged = {
        "id": "RAG-TEST-001",
        "title": "Fixture source title",
        "canonical_url": "https://example.test/source",
        "publisher": "Fixture publisher",
        "version_date": "2024-04-10; page updated 2025-01-02",
        "layer": "intervention",
        "license": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "license_evidence": "Publisher page states CC BY 4.0.",
        "text_scope": "Main text only; no figures or references.",
        "source_population": "General school-age evidence sample; exact age limits are in the source.",
        "stage_modifications": "Navigation and figures omitted; source wording preserved.",
        "required_attribution": "Fixture publisher, title, URL and license; indicate omissions.",
        "stage_retrieved_date_utc": "2026-10-13",
        "stage_retrieval_method": "Fixture supplied as local staging Markdown.",
        "stage_recommendation": "text_only_staged_pending_content_review",
        "review_status": "pending_human_review",
        "rights_status": "verified",
        "human_curated": False,
        "publication_eligible": False,
        "stage_file": "excerpt.md",
        "stage_sha256": hashlib.sha256(body).hexdigest(),
    }
    records = [staged]
    if include_metadata_only:
        records.append(
            {
                "id": "RAG-TEST-META-001",
                "title": "Metadata-only candidate",
                "canonical_url": "https://example.test/metadata-only",
                "publisher": "Fixture publisher",
                "license": "Not project verified",
                "rights_status": "not_project_verified",
                "stage_recommendation": "metadata only until review",
                "review_status": "pending_human_review",
                "human_curated": False,
                "publication_eligible": False,
            }
        )
    manifest = root / "research_source_candidates.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "live_corpus_changed": False,
                "staging_root": str(root),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest, body


def test_stages_real_body_with_pending_metadata_and_lists_metadata_only_without_body(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging" / "rag"
    source_manifest, original_body = _write_fixture_manifest(staging_root)
    source_manifest_sha256 = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    output = tmp_path / "isolated-output" / "review-package"

    result = stage_research_sources(source_manifest, output, language="en")

    assert result["status"] == "pending_review"
    assert result["staged_excerpt_count"] == 1
    assert result["metadata_only_candidate_count"] == 1
    assert result["publication_eligible"] is False
    assert result["human_curated"] is False
    assert result["indexed"] is False

    output_manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert output_manifest["source_candidate_manifest_sha256"] == source_manifest_sha256
    assert output_manifest["live_corpus_changed"] is False
    assert output_manifest["publication_gate"]["review_state"] == "pending_review"
    assert output_manifest["publication_gate"]["auto_approval"] is False
    assert output_manifest["metadata_only_candidates"][0]["candidate_summary"] == "metadata only until review"
    assert output_manifest["metadata_only_candidates"][0]["body_created"] is False
    assert sorted(path.name for path in output.iterdir()) == ["RAG-TEST-001.md", "manifest.json"]

    packaged = (output / "RAG-TEST-001.md").read_bytes()
    delimiter = b"---\n"
    second_delimiter = packaged.index(delimiter, len(delimiter))
    body_start = second_delimiter + len(delimiter)
    assert packaged[body_start:] == original_body

    source = SourceRecord.from_request(
        SourceRequest(
            path=output / "RAG-TEST-001.md",
            input_mode="raw",
            metadata={"source_type": "other"},
        )
    )
    document = MarkdownCuratedParser().parse(source, PipelineConfig(default_language="en"))
    assert document.title == "Fixture source title"
    assert document.language == "en"
    assert document.metadata.population_scope == ["General school-age evidence sample; exact age limits are in the source."]
    assert document.metadata.category == "practice_guidance"
    assert document.metadata.rights_status == "verified"
    assert document.metadata.review_status == "pending"
    assert document.metadata.human_curated is False
    assert document.metadata.role_scope == []
    assert document.metadata.risk_scope == []
    assert document.metadata.extra["publication_eligible"] is False
    assert document.metadata.extra["review_decision"] == "pending_review"
    assert document.metadata.extra["source_license"] == "CC BY 4.0"
    assert document.metadata.extra["stage_modifications"] == "Navigation and figures omitted; source wording preserved."
    assert document.blocks[-1].text == "Visible source text remains unchanged."


@pytest.mark.parametrize("failure", ["hash", "path", "missing_population", "rights", "human_curated", "publication_eligible"])
def test_invalid_source_metadata_fails_closed_without_creating_output(tmp_path: Path, failure: str) -> None:
    staging_root = tmp_path / "staging"
    source_manifest, _ = _write_fixture_manifest(staging_root, include_metadata_only=False)
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    record = manifest["records"][0]
    if failure == "hash":
        record["stage_sha256"] = "0" * 64
    elif failure == "path":
        record["stage_file"] = "../excerpt.md"
    elif failure == "missing_population":
        del record["source_population"]
    elif failure == "rights":
        record["rights_status"] = "unknown"
    elif failure == "human_curated":
        record["human_curated"] = True
    elif failure == "publication_eligible":
        record["publication_eligible"] = True
    source_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "isolated-output" / failure

    with pytest.raises(ResearchStagingError):
        stage_research_sources(source_manifest, output, language="en")

    assert not output.exists()


def test_duplicate_candidate_ids_fail_closed(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    source_manifest, _ = _write_fixture_manifest(staging_root)
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    manifest["records"].append(dict(manifest["records"][0]))
    source_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "isolated-output" / "duplicates"

    with pytest.raises(ResearchStagingError, match="duplicate candidate id"):
        stage_research_sources(source_manifest, output, language="en")

    assert not output.exists()


def test_metadata_only_candidate_cannot_claim_unmaterialized_hash(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    source_manifest, _ = _write_fixture_manifest(staging_root)
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    manifest["records"][1]["stage_sha256"] = "a" * 64
    source_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    output = tmp_path / "isolated-output" / "metadata-only-hash"

    with pytest.raises(ResearchStagingError, match="metadata-only candidate"):
        stage_research_sources(source_manifest, output, language="en")

    assert not output.exists()


def test_existing_output_is_never_overwritten(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    source_manifest, _ = _write_fixture_manifest(staging_root, include_metadata_only=False)
    output = tmp_path / "isolated-output"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("preserve", encoding="utf-8")

    with pytest.raises(ResearchStagingError, match="already exists"):
        stage_research_sources(source_manifest, output, language="en")

    assert sentinel.read_text(encoding="utf-8") == "preserve"


def test_source_manifest_mutation_during_build_fails_before_manifest_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging_root = tmp_path / "staging"
    source_manifest, _ = _write_fixture_manifest(staging_root, include_metadata_only=False)
    output = tmp_path / "isolated-output" / "manifest-changed"
    original_parse = MarkdownCuratedParser.parse

    def parse_then_mutate(self, source, config):
        document = original_parse(self, source, config)
        source_manifest.write_bytes(source_manifest.read_bytes() + b"\n")
        return document

    monkeypatch.setattr(MarkdownCuratedParser, "parse", parse_then_mutate)

    with pytest.raises(ResearchStagingError, match="manifest changed"):
        stage_research_sources(source_manifest, output, language="en")

    assert output.is_dir()
    assert (output / "RAG-TEST-001.md").is_file()
    assert not (output / "manifest.json").exists()


def test_output_path_reparse_parent_is_rejected_when_platform_supports_symlinks(tmp_path: Path) -> None:
    staging_root = tmp_path / "staging"
    source_manifest, _ = _write_fixture_manifest(staging_root, include_metadata_only=False)
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    try:
        linked_parent.symlink_to(real_parent, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"directory symlinks are unavailable on this platform: {type(exc).__name__}")
    output = linked_parent / "new-package"

    with pytest.raises(ResearchStagingError, match="symlink or reparse-point"):
        stage_research_sources(source_manifest, output, language="en")

    assert not (real_parent / "new-package").exists()
