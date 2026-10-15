from __future__ import annotations

import hashlib
import json

import pytest
import school_research_education_draft_config as config
from school_research_student_config import StudentResearchConfig


def _write(tmp_path, **overrides):
    document = {
        "schema_version": config.SCHEMA_VERSION,
        "enabled": True,
        "school_id": 7,
        "school_study_ref": "HUNNU_PROMIS_HISTORICAL_REPLAY_2026_R1",
        "purpose": "RESEARCH_SIMULATION",
        "policy_version": config.POLICY_VERSION,
        "student_source_config_file": str(tmp_path / "source.json"),
        "student_source_config_sha256": "a" * 64,
        "content_mode": "GENERAL_INFORMATION_NO_ASSESSMENT_INPUT",
        "release_mode": "HELD_THEN_EXPLICIT_REVIEW_AND_PUBLISH",
    }
    document.update(overrides)
    path = tmp_path / "draft.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _source(tmp_path, *, school_id=7, manifest_sha=None):
    return StudentResearchConfig(
        config_file=str(tmp_path / "source.json"), config_sha256="a" * 64,
        school_id=school_id, manifest_file=str(tmp_path / "manifest.json"),
        manifest_sha256=manifest_sha or config.SOURCE_MANIFEST_SHA256,
    )


def test_policy_hash_binds_entire_opt_in_config_and_distinct_studies(tmp_path, monkeypatch):
    path, digest = _write(tmp_path)
    source = _source(tmp_path)
    calls = []

    def load(file, sha):
        calls.append((file, sha))
        return source

    monkeypatch.setattr(config, "load_student_research_config", load)
    loaded = config.load_research_education_draft_config(path, digest)
    assert loaded.policy_hash == digest
    assert loaded.school_study_ref != loaded.source_study_ref
    assert loaded.source_manifest_sha256 == source.manifest_sha256
    assert calls == [(tmp_path / "source.json", "a" * 64)]
    assert loaded.manifest_value()["release_mode"] == "HELD_THEN_EXPLICIT_REVIEW_AND_PUBLISH"
    assert "source.json" not in repr(loaded)


@pytest.mark.parametrize("override", [
    {"enabled": False}, {"enabled": 1}, {"school_id": True}, {"school_id": 0},
    {"school_study_ref": "study with spaces"}, {"purpose": "production"},
    {"content_mode": "PERSONALIZED"}, {"release_mode": "AUTO_PUBLISH"},
    {"policy_version": "RESEARCH_STAFF_PROGRAMME_POLICY_V1"}, {"extra": True},
    {"student_source_config_file": "relative.json"},
])
def test_closed_config_rejects_unapproved_scope(tmp_path, monkeypatch, override):
    path, digest = _write(tmp_path, **override)
    monkeypatch.setattr(config, "load_student_research_config", lambda *_: _source(tmp_path))
    with pytest.raises(config.ResearchEducationDraftConfigError):
        config.load_research_education_draft_config(path, digest)


@pytest.mark.parametrize("source_school,source_sha", [(8, None), (7, "b" * 64)])
def test_rejects_other_school_or_old_source(tmp_path, monkeypatch, source_school, source_sha):
    path, digest = _write(tmp_path)
    monkeypatch.setattr(config, "load_student_research_config", lambda *_: _source(
        tmp_path, school_id=source_school, manifest_sha=source_sha,
    ))
    with pytest.raises(config.ResearchEducationDraftConfigError):
        config.load_research_education_draft_config(path, digest)


def test_file_tamper_fails_before_source_loader(tmp_path, monkeypatch):
    path, digest = _write(tmp_path)
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    calls = []
    monkeypatch.setattr(config, "load_student_research_config", lambda *_: calls.append(True))
    with pytest.raises(config.ResearchEducationDraftConfigError):
        config.load_research_education_draft_config(path, digest)
    assert not calls
