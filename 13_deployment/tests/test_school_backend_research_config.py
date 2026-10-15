import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_backend as backend


def _write_service_config(
    path: Path, *, host: str = "127.0.0.1", port: int = 58540
) -> str:
    document = {
        "schema": "psynova.research-cat-service.v1",
        "school_scope": "school:synthetic",
        "resource_root": "D:/research",
        "listener": {"host": host, "port": port},
        "signing": {},
        "profiles": [],
        "bindings": [],
    }
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime_file = workspace / "research-runtime.json"
    runtime_file.write_text("{}", encoding="utf-8")
    service_file = workspace / "research-service.json"
    service_sha = _write_service_config(service_file)
    cat_python = tmp_path / "python.exe"
    cat_python.write_bytes(b"synthetic executable fixture")
    cat_source = tmp_path / "cat-source"
    cat_source.mkdir()
    cat_dependencies = tmp_path / "cat-dependencies"
    cat_dependencies.mkdir()
    args = backend.build_parser().parse_args(
        [
            "--workspace",
            str(workspace),
            "--research-runtime-file",
            str(runtime_file),
            "--research-runtime-sha256",
            "a" * 64,
            "--research-service-file",
            str(service_file),
            "--research-service-sha256",
            service_sha,
            "--research-cat-python",
            str(cat_python),
            "--research-cat-source",
            str(cat_source),
            "--research-cat-dependencies",
            str(cat_dependencies),
        ]
    )
    return workspace, args, service_file, service_sha


def test_no_research_cli_preserves_existing_disabled_defaults(tmp_path, monkeypatch):
    args = backend.build_parser().parse_args(["--workspace", str(tmp_path)])

    assert backend.build_research_settings_kwargs(args, tmp_path) == {}
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)
    monkeypatch.setenv("SMHAI_RESEARCH_EDUCATION_WORKER__ENABLED", "true")
    from smhai_backend.core.config import BackendSettings

    cli_settings, research = backend.build_cli_settings_kwargs(args)
    assert research == {}
    assert cli_settings["research_education_worker"] == {"enabled": False}
    settings = BackendSettings(
        _env_file=None, **cli_settings
    )
    assert settings.school_research_enabled is False
    assert settings.school_research_managed_enabled is False
    assert settings.research_education_worker_enabled is False


def test_general_education_draft_is_disabled_by_default_even_with_environment_override(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "SMHAI_RESEARCH_GENERAL_EDUCATION_DRAFT__ENABLED", "true"
    )
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)
    args = backend.build_parser().parse_args(["--workspace", str(tmp_path)])

    settings, _research = backend.build_cli_settings_kwargs(args)

    assert settings["research_general_education_draft"] == {"enabled": False}
    from smhai_backend.core.config import BackendSettings

    parsed = BackendSettings(_env_file=None, **settings)
    assert parsed.research_general_education_draft.enabled is False


def test_general_education_draft_requires_both_explicit_config_pins(tmp_path):
    args = backend.build_parser().parse_args(
        [
            "--workspace", str(tmp_path),
            "--research-education-draft-config-file", str(tmp_path / "draft.json"),
        ]
    )

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_cli_settings_kwargs(args)

    assert exc.value.code == "research_education_draft_config_incomplete"


def test_general_education_draft_maps_only_matching_source_study_and_8161_runtime(
    tmp_path, monkeypatch
):
    from school_research_education_draft_config import ResearchEducationDraftConfig
    from school_research_student_config import StudentResearchConfig

    workspace, args, _service, _service_sha = _fixture(tmp_path)
    study_file = _attach_study_use(args, workspace)
    student_file = workspace / "student.json"
    student_sha = "b" * 64
    source = StudentResearchConfig(
        config_file=str(student_file),
        config_sha256=student_sha,
        school_id=7,
        manifest_file=str(workspace / "source-r3.json"),
        manifest_sha256="ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b",
    )
    draft_file = workspace / "draft.json"
    draft_sha = "c" * 64
    draft = ResearchEducationDraftConfig(
        config_file=str(draft_file),
        config_sha256=draft_sha,
        school_id=7,
        school_study_ref="school-study-r3",
        student_source=source,
    )
    args.research_student_config_file = student_file
    args.research_student_config_sha256 = student_sha
    args.research_education_draft_config_file = draft_file
    args.research_education_draft_config_sha256 = draft_sha
    monkeypatch.setattr(backend, "_validate_study_use_policy", lambda **_kwargs: None)
    monkeypatch.setattr(backend, "load_student_research_config", lambda *_args: source)
    monkeypatch.setattr(
        backend, "load_research_education_draft_config", lambda *_args: draft
    )
    monkeypatch.setattr(
        "smhai_backend.domains.school_research.study_use.load_research_study_use_policy",
        lambda *_args, **_kwargs: SimpleNamespace(
            school_id=7,
            study_ref="school-study-r3",
            source_rights_verified=True,
        ),
        raising=False,
    )

    settings, research = backend.build_cli_settings_kwargs(args)

    assert settings["research_general_education_draft"] == draft.core_settings()
    assert research["research_programme_runtime"] == {
        "mode": "http",
        "base_url": "http://127.0.0.1:8161",
        "timeout": {"read": 65.0},
    }
    assert "research_programme_worker" not in research
    assert research["school_research_study_use_file"] == str(study_file)

    from smhai_backend.core.config import BackendSettings

    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)
    parsed = BackendSettings(_env_file=None, **settings)
    assert parsed.research_general_education_draft.enabled is True
    assert parsed.research_programme_runtime.timeout.read >= 65


def test_general_education_draft_rejects_source_and_study_scope_mismatches(
    tmp_path, monkeypatch
):
    from school_research_education_draft_config import ResearchEducationDraftConfig
    from school_research_student_config import StudentResearchConfig

    workspace, args, _service, _service_sha = _fixture(tmp_path)
    _attach_study_use(args, workspace)
    student_file = workspace / "student.json"
    source = StudentResearchConfig(
        config_file=str(student_file), config_sha256="b" * 64, school_id=7,
        manifest_file=str(workspace / "source-r3.json"),
        manifest_sha256="ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b",
    )
    args.research_student_config_file = student_file
    args.research_student_config_sha256 = source.config_sha256
    args.research_education_draft_config_file = workspace / "draft.json"
    args.research_education_draft_config_sha256 = "c" * 64
    monkeypatch.setattr(backend, "_validate_study_use_policy", lambda **_kwargs: None)
    monkeypatch.setattr(backend, "load_student_research_config", lambda *_args: source)
    mismatch_source = replace(source, manifest_sha256="d" * 64)
    mismatch_draft = ResearchEducationDraftConfig(
        config_file=str(workspace / "draft.json"), config_sha256="c" * 64,
        school_id=7, school_study_ref="school-study-r3", student_source=mismatch_source,
    )
    monkeypatch.setattr(
        backend, "load_research_education_draft_config", lambda *_args: mismatch_draft
    )
    with pytest.raises(backend.ResearchCLIConfigError) as source_exc:
        backend.build_cli_settings_kwargs(args)
    assert source_exc.value.code == "research_education_draft_source_mismatch"

    matching_draft = replace(mismatch_draft, student_source=source)
    monkeypatch.setattr(
        backend, "load_research_education_draft_config", lambda *_args: matching_draft
    )
    monkeypatch.setattr(
        "smhai_backend.domains.school_research.study_use.load_research_study_use_policy",
        lambda *_args, **_kwargs: SimpleNamespace(
            school_id=7, study_ref="another-study", source_rights_verified=True
        ),
        raising=False,
    )
    with pytest.raises(backend.ResearchCLIConfigError) as study_exc:
        backend.build_cli_settings_kwargs(args)
    assert study_exc.value.code == "research_education_draft_study_mismatch"


def test_complete_research_cli_maps_only_explicit_nonsecret_settings(
    tmp_path, monkeypatch
):
    workspace, args, _service_file, service_sha = _fixture(tmp_path)
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)

    result = backend.build_research_settings_kwargs(args, workspace)

    assert result == {
        "school_research_enabled": True,
        "school_research_runtime_file": str(workspace / "research-runtime.json"),
        "school_research_runtime_sha256": "a" * 64,
        "school_research_base_url": "http://127.0.0.1:58540",
        "school_research_managed_enabled": True,
        "school_research_service_file": str(workspace / "research-service.json"),
        "school_research_service_sha256": service_sha,
        "school_research_cat_python": str(tmp_path / "python.exe"),
        "school_research_cat_source": str(tmp_path / "cat-source"),
        "school_research_cat_dependencies": str(tmp_path / "cat-dependencies"),
    }
    from smhai_backend.core.config import BackendSettings

    settings = BackendSettings(
        _env_file=None,
        **backend.build_school_settings_kwargs(8088, 4178),
        **result,
    )
    assert settings.school_research_enabled is True
    assert settings.school_research_managed_enabled is True
    assert settings.school_research_base_url == "http://127.0.0.1:58540"


def _attach_study_use(args, workspace: Path, *, rights: bool = True) -> Path:
    policy_file = workspace / "study-use.json"
    policy_file.write_text("{}", encoding="utf-8")
    args.research_study_use_file = policy_file
    args.research_study_use_sha256 = hashlib.sha256(policy_file.read_bytes()).hexdigest()
    args.research_source_rights_verified = rights
    args.research_latest_study_end = "2027-06-30T15:59:59Z"
    return policy_file


def test_study_use_cli_requires_all_four_flags_and_explicit_true_rights(tmp_path):
    workspace, args, _service, _sha = _fixture(tmp_path)
    _attach_study_use(args, workspace)
    args.research_latest_study_end = None
    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)
    assert exc.value.code == "study_use_config_incomplete"

    second = tmp_path / "second"
    second.mkdir()
    workspace, args, _service, _sha = _fixture(second)
    _attach_study_use(args, workspace, rights=False)
    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)
    assert exc.value.code == "study_use_config_incomplete"


def test_backend_parser_accepts_all_four_study_use_flags(tmp_path):
    args = backend.build_parser().parse_args(
        [
            "--workspace", str(tmp_path),
            "--research-study-use-file", str(tmp_path / "policy.json"),
            "--research-study-use-sha256", "a" * 64,
            "--research-source-rights-verified",
            "--research-latest-study-end", "2027-06-30T15:59:59Z",
        ]
    )
    assert args.research_study_use_file == tmp_path / "policy.json"
    assert args.research_source_rights_verified is True
    assert args.research_latest_study_end == "2027-06-30T15:59:59Z"


def test_research_education_worker_is_opt_in_and_requires_pinned_study_use(
    tmp_path, monkeypatch
):
    missing_policy = backend.build_parser().parse_args(
        [
            "--workspace", str(tmp_path),
            "--enable-research-education-worker",
        ]
    )
    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(missing_policy, tmp_path)
    assert exc.value.code == "research_worker_requires_pinned_study_use"
    missing_policy.enable_research_education_worker = 1
    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(missing_policy, tmp_path)
    assert exc.value.code == "research_worker_config_invalid"

    configured_root = tmp_path / "configured"
    configured_root.mkdir()
    workspace, args, _service, _sha = _fixture(configured_root)
    _attach_study_use(args, workspace)
    args.enable_research_education_worker = True
    validated = []
    monkeypatch.setattr(
        backend,
        "_validate_study_use_policy",
        lambda **kwargs: validated.append(kwargs),
    )
    cli_settings, research = backend.build_cli_settings_kwargs(args)

    assert research["research_education_worker"] == {"enabled": True}
    assert cli_settings["research_education_worker"] == {"enabled": True}
    assert len(validated) == 1
    assert validated[0]["study_sha256"] == args.research_study_use_sha256
    assert validated[0]["latest_end"] == research["school_research_latest_study_end"]

    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)
    from smhai_backend.core.config import BackendSettings

    backend_settings = BackendSettings(
        _env_file=None,
        **cli_settings,
    )
    assert backend_settings.research_education_worker.enabled is True


def test_study_use_cli_maps_only_verified_policy_metadata(tmp_path, monkeypatch):
    workspace, args, _service, _sha = _fixture(tmp_path)
    policy_file = _attach_study_use(args, workspace)
    checked = []
    monkeypatch.setattr(
        backend,
        "_validate_study_use_policy",
        lambda **kwargs: checked.append(kwargs),
    )

    result = backend.build_research_settings_kwargs(args, workspace)

    assert result["school_research_study_use_file"] == str(policy_file)
    assert result["school_research_study_use_sha256"] == hashlib.sha256(
        policy_file.read_bytes()
    ).hexdigest()
    assert result["school_research_source_rights_verified"] is True
    assert result["school_research_latest_study_end"].isoformat() == (
        "2027-06-30T15:59:59+00:00"
    )
    assert checked[0]["latest_end"] == result["school_research_latest_study_end"]
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)
    from smhai_backend.core.config import BackendSettings

    settings = BackendSettings(
        _env_file=None,
        **backend.build_school_settings_kwargs(8088, 4178),
        **result,
    )
    assert settings.school_research_source_rights_verified is True
    assert settings.school_research_latest_study_end == result[
        "school_research_latest_study_end"
    ]


@pytest.mark.parametrize(
    "value", ["2027-06-30T23:59:59+08:00", "2027-06-30T15:59:59", "2027-13-01T00:00:00Z"]
)
def test_study_latest_end_requires_valid_utc_timestamp(value):
    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend._parse_study_end(value)
    assert exc.value.code == "study_use_config_invalid"


def test_study_use_policy_rejects_wrong_school_profile_or_crosswalk(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from smhai_backend.domains.school_research import bootstrap, managed, study_use

    runtime_file = tmp_path / "runtime.json"
    runtime_file.write_text(json.dumps({"profiles": [{"profile_ref": "profile-a"}]}))
    trusted = SimpleNamespace(
        raw_manifest_bytes=json.dumps(
            {"parameter_crosswalk_sha256": "c" * 64}
        ).encode(),
        profile_sha256="a" * 64,
        manifest_sha256="b" * 64,
    )
    runtime = SimpleNamespace(
        school_id=701,
        _registry=SimpleNamespace(load=lambda _ref: trusted),
    )
    pin = SimpleNamespace(
        profile_ref="profile-a",
        published_crosswalk_sha256="c" * 64,
    )

    class FakePolicy:
        source_rights_verified = True
        school_id = 701
        profiles = (pin,)

        def require_scope(self, **_kwargs):
            return pin

    monkeypatch.setattr(bootstrap, "load_research_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(
        managed, "validate_managed_research_config_pair", lambda **_kwargs: None
    )
    monkeypatch.setattr(
        study_use, "load_research_study_use_policy", lambda *_args, **_kwargs: FakePolicy()
    )
    common = {
        "study_file": tmp_path / "policy.json",
        "study_sha256": "d" * 64,
        "latest_end": backend.datetime.now(backend.UTC),
        "runtime_file": runtime_file,
        "runtime_sha256": "e" * 64,
        "service_file": tmp_path / "service.json",
        "service_sha256": "f" * 64,
        "base_url": "http://127.0.0.1:58540",
    }
    backend._validate_study_use_policy(**common)

    runtime.school_id = 702
    with pytest.raises(backend.ResearchCLIConfigError):
        backend._validate_study_use_policy(**common)
    runtime.school_id = 701
    pin.published_crosswalk_sha256 = "1" * 64
    with pytest.raises(backend.ResearchCLIConfigError):
        backend._validate_study_use_policy(**common)


def test_study_policy_loader_enforces_hash_expiry_school_and_crosswalk(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from smhai_backend.domains.school_research import bootstrap, managed

    runtime_file = tmp_path / "runtime.json"
    runtime_file.write_text(json.dumps({"profiles": [{"profile_ref": "profile-a"}]}))
    service_file = tmp_path / "service.json"
    service_file.write_text("{}")
    trusted = SimpleNamespace(
        raw_manifest_bytes=json.dumps(
            {"parameter_crosswalk_sha256": "c" * 64}
        ).encode(),
        profile_sha256="a" * 64,
        manifest_sha256="b" * 64,
    )
    runtime = SimpleNamespace(
        school_id=701,
        _registry=SimpleNamespace(load=lambda _ref: trusted),
    )
    monkeypatch.setattr(bootstrap, "load_research_runtime", lambda **_kwargs: runtime)
    monkeypatch.setattr(
        managed, "validate_managed_research_config_pair", lambda **_kwargs: None
    )

    document = {
        "schema": "psynova.research-study-use.v1",
        "study_ref": "study:replay-01",
        "school_id": 701,
        "institution": "Synthetic institution declaration",
        "use_scope": "ISOLATED_HISTORICAL_REPLAY",
        "noncommercial": True,
        "historical_replay_only": True,
        "english_unchanged": True,
        "starts_at": "2026-10-14T00:00:00Z",
        "ends_at": "2027-06-30T23:59:59Z",
        "profiles": [
            {
                "profile_ref": "profile-a",
                "profile_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "published_crosswalk_sha256": "c" * 64,
            }
        ],
        "rights_basis": "Recorded test-only research scope.",
        "rights_source_urls": ["https://example.org/research-rights"],
        "recorded_by": "operator:test",
        "recorded_at": "2026-10-14T00:00:00Z",
        "operator_declaration": "Synthetic test fixture only.",
        "clinical_approval": False,
        "ethics_approval": False,
        "psychometric_approval": False,
    }
    policy_file = tmp_path / "policy.json"
    base = {
        "study_file": policy_file,
        "study_sha256": "",
        "latest_end": backend._parse_study_end("2027-06-30T15:59:59Z"),
        "runtime_file": runtime_file,
        "runtime_sha256": "e" * 64,
        "service_file": service_file,
        "service_sha256": "f" * 64,
        "base_url": "http://127.0.0.1:58540",
    }

    def write_and_check(changes, *, wrong_hash=False):
        value = dict(document)
        value.update(changes)
        raw = json.dumps(value, separators=(",", ":")).encode()
        policy_file.write_bytes(raw)
        base["study_sha256"] = "0" * 64 if wrong_hash else hashlib.sha256(raw).hexdigest()
        with pytest.raises(backend.ResearchCLIConfigError) as exc:
            backend._validate_study_use_policy(**base)
        assert exc.value.code == "study_use_config_invalid"

    write_and_check({}, wrong_hash=True)
    write_and_check({})  # Policy expiry exceeds the trusted UTC upper bound.
    write_and_check({"school_id": 702})
    write_and_check(
        {
            "profiles": [
                {
                    **document["profiles"][0],
                    "published_crosswalk_sha256": "d" * 64,
                }
            ]
        }
    )


def test_partial_research_cli_fails_with_fixed_code_and_no_paths(tmp_path):
    args = backend.build_parser().parse_args(
        [
            "--workspace",
            str(tmp_path),
            "--research-runtime-file",
            str(tmp_path / "secret-path"),
        ]
    )

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, tmp_path)

    assert exc.value.code == "research_config_incomplete"
    assert str(tmp_path) not in str(exc.value)


def test_partial_research_cli_emits_only_fixed_error_code(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "school_backend.py",
            "--workspace",
            str(tmp_path),
            "--research-runtime-file",
            str(tmp_path / "private-name.json"),
        ],
    )
    monkeypatch.setattr(backend, "load_runtime", lambda *_args: {})

    assert backend.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "school_backend": "BLOCKED",
        "error_code": "research_config_incomplete",
    }
    assert str(tmp_path) not in output


def _main_argv(args, *, preflight: bool = True) -> list[str]:
    values = ["school_backend.py", "--workspace", str(args.workspace)]
    if preflight:
        values.append("--preflight-only")
    for name, flag in (
        ("research_runtime_file", "--research-runtime-file"),
        ("research_runtime_sha256", "--research-runtime-sha256"),
        ("research_service_file", "--research-service-file"),
        ("research_service_sha256", "--research-service-sha256"),
        ("research_cat_python", "--research-cat-python"),
        ("research_cat_source", "--research-cat-source"),
        ("research_cat_dependencies", "--research-cat-dependencies"),
    ):
        value = getattr(args, name)
        if value is not None:
            values.extend((flag, str(value)))
    policy_file = getattr(args, "research_study_use_file", None)
    policy_sha = getattr(args, "research_study_use_sha256", None)
    latest_end = getattr(args, "research_latest_study_end", None)
    if policy_file is not None:
        values.extend(("--research-study-use-file", str(policy_file)))
    if policy_sha is not None:
        values.extend(("--research-study-use-sha256", policy_sha))
    if getattr(args, "research_source_rights_verified", False):
        values.append("--research-source-rights-verified")
    if latest_end is not None:
        values.extend(("--research-latest-study-end", latest_end))
    return values


def _write_valid_managed_pair(workspace: Path):
    resource_root = workspace / "resources"
    resource_root.mkdir()
    profile_path = resource_root / "profile.json"
    manifest_path = resource_root / "manifest.json"
    profile_path.write_text("synthetic profile metadata", encoding="utf-8")
    manifest_path.write_text("synthetic manifest metadata", encoding="utf-8")
    profile_sha = hashlib.sha256(profile_path.read_bytes()).hexdigest()
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    cat_config = {
        "config_version": "research-config-v1",
        "model": "GRM",
        "estimator": "EAP",
        "selection_method": "MFI",
        "min_items": 1,
        "max_items": 1,
        "se_threshold": None,
        "initial_theta": 0.0,
        "prior_mean": 0.0,
        "prior_sd": 1.0,
        "optimization_interval": [-4.0, 4.0],
        "seed": 20261014,
        "exposure_control": "none",
        "content_balancing": "none",
    }
    config_raw = json.dumps(
        cat_config,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    config_sha = hashlib.sha256(config_raw).hexdigest()
    runtime = {
        "schema": "psynova.school-research-runtime.v1",
        "school_id": 701,
        "resource_root": str(resource_root),
        "signing_version": "v1",
        "accepted_key_versions": ["v1"],
        "profiles": [
            {
                "profile_ref": "profile-1",
                "profile_schema": "psynova.research-profile.v3",
                "expected_profile_sha256": profile_sha,
                "expected_manifest_sha256": manifest_sha,
                "source_family": "synthetic-test-fixture",
                "parameter_origin": "PUBLISHED_ROUNDED_REFERENCE",
                "profile_path": str(profile_path),
                "manifest_path": str(manifest_path),
                "expected_fit_sha256": None,
                "expected_calibration_sha256": None,
            }
        ],
        "bindings": [
            {
                "binding_ref": "binding-1",
                "profile_ref": "profile-1",
                "config_version": "research-config-v1",
                "config_sha256": config_sha,
            }
        ],
    }
    service = {
        "schema": "psynova.research-cat-service.v1",
        "school_scope": {"school_id": 701, "scope": "school:701"},
        "resource_root": str(resource_root),
        "listener": {"host": "127.0.0.1", "port": 58540},
        "signing": {"signing_version": "v1", "accepted_key_versions": ["v1"]},
        "profiles": [
            {
                "profile_ref": "profile-1",
                "profile_schema": "psynova.research-profile.v3",
                "profile_path": str(profile_path),
                "profile_sha256": profile_sha,
                "manifest_path": str(manifest_path),
                "manifest_sha256": manifest_sha,
            }
        ],
        "bindings": [
            {
                "binding_ref": "binding-1",
                "profile_ref": "profile-1",
                "config_version": "research-config-v1",
                "config_sha256": config_sha,
                "cat_config": cat_config,
            }
        ],
    }

    def write_document(path: Path, document: dict) -> str:
        raw = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        path.write_bytes(raw)
        return hashlib.sha256(raw).hexdigest()

    runtime_file = workspace / "research-runtime.json"
    service_file = workspace / "research-service.json"
    runtime_sha = write_document(runtime_file, runtime)
    service_sha = write_document(service_file, service)
    cat_python = workspace / "cat-python.exe"
    cat_python.write_bytes(b"test-only executable marker")
    cat_source = workspace / "cat-source"
    cat_source.mkdir()
    cat_dependencies = workspace / "cat-dependencies"
    cat_dependencies.mkdir()
    argv = [
        "school_backend.py",
        "--workspace",
        str(workspace),
        "--preflight-only",
        "--research-runtime-file",
        str(runtime_file),
        "--research-runtime-sha256",
        runtime_sha,
        "--research-service-file",
        str(service_file),
        "--research-service-sha256",
        service_sha,
        "--research-cat-python",
        str(cat_python),
        "--research-cat-source",
        str(cat_source),
        "--research-cat-dependencies",
        str(cat_dependencies),
    ]
    return argv, service, service_file


def test_preflight_calls_managed_pair_validator_before_app_construction(
    tmp_path, monkeypatch, capsys
):
    workspace, args, _service_file, _service_sha = _fixture(tmp_path)
    args.workspace = workspace
    monkeypatch.setattr(sys, "argv", _main_argv(args))
    monkeypatch.setattr(backend, "load_runtime", lambda *_args: {})
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)

    from smhai_backend import app_factory
    from smhai_backend.domains.school_research import managed

    events = []

    def validate(**kwargs):
        events.append(("validate", kwargs))

    def create_app(*, settings):
        events.append(("create_app", settings.school_research_enabled))
        return object()

    monkeypatch.setattr(
        managed, "validate_managed_research_config_pair", validate, raising=False
    )
    monkeypatch.setattr(app_factory, "create_app", create_app)

    assert backend.main() == 0
    assert events[0][0] == "validate"
    assert events[0][1]["runtime_config_file"] == workspace / "research-runtime.json"
    assert events[0][1]["service_config_file"] == workspace / "research-service.json"
    assert events[1] == ("create_app", True)
    assert json.loads(capsys.readouterr().out)["preflight"] == "PASS"


def test_preflight_pair_mismatch_is_sanitized_and_blocks_app_construction(
    tmp_path, monkeypatch, capsys
):
    workspace, args, _service_file, _service_sha = _fixture(tmp_path)
    args.workspace = workspace
    monkeypatch.setattr(sys, "argv", _main_argv(args))
    monkeypatch.setattr(backend, "load_runtime", lambda *_args: {})
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)

    from smhai_backend import app_factory
    from smhai_backend.domains.school_research import managed

    monkeypatch.setattr(
        managed,
        "validate_managed_research_config_pair",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("sensitive config detail")),
        raising=False,
    )
    monkeypatch.setattr(
        app_factory,
        "create_app",
        lambda **_kwargs: pytest.fail(
            "mismatched pair must fail before app construction"
        ),
    )

    assert backend.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "school_backend": "BLOCKED",
        "error_code": "research_config_pair_mismatch",
    }
    assert "sensitive config detail" not in output
    assert str(workspace) not in output


def test_preflight_accepts_matching_config_pair_without_starting_process(
    tmp_path, monkeypatch, capsys
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    argv, _service, _service_file = _write_valid_managed_pair(workspace)
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(backend, "load_runtime", lambda *_args: {})
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)

    from smhai_backend import app_factory

    constructed = []
    monkeypatch.setattr(
        app_factory,
        "create_app",
        lambda *, settings: constructed.append(settings) or object(),
    )

    assert backend.main() == 0
    assert len(constructed) == 1
    assert constructed[0].school_research_enabled is True
    assert json.loads(capsys.readouterr().out)["preflight"] == "PASS"


def test_normal_research_launch_validates_pair_before_app_and_uvicorn(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    argv, _service, _service_file = _write_valid_managed_pair(workspace)
    argv.remove("--preflight-only")
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(backend, "load_runtime", lambda *_args: {})
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)

    from smhai_backend import app_factory
    from smhai_backend.domains.school_research import managed

    events = []
    monkeypatch.setattr(
        managed,
        "validate_managed_research_config_pair",
        lambda **_kwargs: events.append("validate"),
    )
    monkeypatch.setattr(
        app_factory,
        "create_app",
        lambda **_kwargs: events.append("create_app") or object(),
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *_args, **_kwargs: events.append("uvicorn")),
    )

    assert backend.main() == 0
    assert events == ["validate", "create_app", "uvicorn"]


def test_study_use_pure_validation_precedes_sealed_runtime_and_app(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    argv, _service, _service_file = _write_valid_managed_pair(workspace)
    policy_file = workspace / "study-use.json"
    policy_file.write_text("{}", encoding="utf-8")
    argv.extend(
        [
            "--research-study-use-file", str(policy_file),
            "--research-study-use-sha256", hashlib.sha256(policy_file.read_bytes()).hexdigest(),
            "--research-source-rights-verified",
            "--research-latest-study-end", "2027-06-30T15:59:59Z",
        ]
    )
    argv.remove("--preflight-only")
    monkeypatch.setattr(sys, "argv", argv)
    events = []
    monkeypatch.setattr(
        backend, "load_runtime", lambda *_args: events.append("sealed-runtime") or {}
    )
    monkeypatch.setattr(
        backend,
        "_validate_study_use_policy",
        lambda **_kwargs: events.append("study-policy"),
    )
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)
    from smhai_backend import app_factory
    from smhai_backend.domains.school_research import managed

    monkeypatch.setattr(
        managed,
        "validate_managed_research_config_pair",
        lambda **_kwargs: events.append("config-pair"),
        raising=False,
    )
    monkeypatch.setattr(
        app_factory, "create_app", lambda **_kwargs: events.append("create-app") or object()
    )
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        SimpleNamespace(run=lambda *_args, **_kwargs: events.append("uvicorn")),
    )

    assert backend.main() == 0
    assert events == ["study-policy", "config-pair", "sealed-runtime", "create-app", "uvicorn"]


@pytest.mark.parametrize(
    "mismatch", ["school", "profile_hash", "binding", "binding_hash"]
)
def test_preflight_blocks_individually_valid_but_mismatched_configs(
    tmp_path, monkeypatch, capsys, mismatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    argv, service, service_file = _write_valid_managed_pair(workspace)
    if mismatch == "school":
        service["school_scope"] = {"school_id": 702, "scope": "school:702"}
    elif mismatch == "profile_hash":
        service["profiles"][0]["profile_sha256"] = "b" * 64
    elif mismatch == "binding":
        service["bindings"][0]["binding_ref"] = "different-binding"
    else:
        config = service["bindings"][0]["cat_config"]
        config["seed"] += 1
        config_bytes = json.dumps(
            config,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        service["bindings"][0]["config_sha256"] = hashlib.sha256(
            config_bytes
        ).hexdigest()
    service_bytes = json.dumps(
        service,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    service_file.write_bytes(service_bytes)
    argv[argv.index("--research-service-sha256") + 1] = hashlib.sha256(
        service_bytes
    ).hexdigest()
    from smhai_backend.domains.school_research import managed

    runtime_file = workspace / "research-runtime.json"
    runtime_doc = managed._parse_document(runtime_file.read_bytes(), "runtime-invalid")
    service_doc = managed._parse_document(service_bytes, "service-invalid")
    managed._validate_runtime_document(runtime_doc)
    managed._validate_service_document(service_doc)
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr(backend, "load_runtime", lambda *_args: {})
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)

    from smhai_backend import app_factory

    monkeypatch.setattr(
        app_factory,
        "create_app",
        lambda **_kwargs: pytest.fail("mismatched config pair must block preflight"),
    )

    assert backend.main() == 2
    output = capsys.readouterr().out
    assert json.loads(output) == {
        "school_backend": "BLOCKED",
        "error_code": "research_config_pair_mismatch",
    }
    assert str(workspace) not in output


def test_normal_no_research_cli_does_not_import_or_call_pair_validator(
    tmp_path, monkeypatch, capsys
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        ["school_backend.py", "--workspace", str(workspace), "--preflight-only"],
    )
    monkeypatch.setattr(backend, "load_runtime", lambda *_args: {})
    monkeypatch.setenv("SMHAI_SCHOOL_CSRF_SECRET", "a" * 64)

    from smhai_backend import app_factory

    monkeypatch.setattr(app_factory, "create_app", lambda **_kwargs: object())

    assert backend.main() == 0
    assert json.loads(capsys.readouterr().out)["preflight"] == "PASS"


@pytest.mark.parametrize("digest", ["A" * 64, "a" * 63, "g" * 64, 7])
def test_invalid_runtime_or_service_sha_is_rejected(tmp_path, digest):
    workspace, args, _service_file, _service_sha = _fixture(tmp_path)
    args.research_runtime_sha256 = digest

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)

    assert exc.value.code == "research_config_invalid"


def test_config_files_must_be_inside_target_workspace(tmp_path):
    workspace, args, _service_file, _service_sha = _fixture(tmp_path)
    outside = tmp_path / "outside-runtime.json"
    outside.write_text("{}", encoding="utf-8")
    args.research_runtime_file = outside

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)

    assert exc.value.code == "research_config_invalid"


@pytest.mark.parametrize(
    "field", ["research_cat_python", "research_cat_source", "research_cat_dependencies"]
)
def test_cat_paths_must_be_explicit_absolute_existing_paths(tmp_path, field):
    workspace, args, _service_file, _service_sha = _fixture(tmp_path)
    setattr(args, field, Path("relative-cat-path"))

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)

    assert exc.value.code == "research_config_invalid"


def test_research_config_rejects_symlinked_path_components_when_supported(tmp_path):
    workspace, args, _service_file, _service_sha = _fixture(tmp_path)
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    link = tmp_path / "linked"
    try:
        link.symlink_to(real_dir, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable in this environment")
    args.research_cat_source = link

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)

    assert exc.value.code == "research_config_invalid"


@pytest.mark.parametrize(
    "mutate,expected_sha",
    [
        (lambda doc: doc["listener"].update(host="0.0.0.0"), None),
        (lambda doc: doc["listener"].update(port=True), None),
        (lambda doc: doc.update(unexpected=True), None),
    ],
)
def test_service_config_requires_closed_loopback_listener(
    tmp_path, mutate, expected_sha
):
    workspace, args, service_file, _service_sha = _fixture(tmp_path)
    document = json.loads(service_file.read_text(encoding="utf-8"))
    mutate(document)
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    service_file.write_bytes(raw)
    args.research_service_sha256 = hashlib.sha256(raw).hexdigest()

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)

    assert exc.value.code == "research_service_config_invalid"


def test_service_hash_mismatch_and_duplicate_keys_are_rejected(tmp_path):
    workspace, args, service_file, _service_sha = _fixture(tmp_path)
    args.research_service_sha256 = "b" * 64
    with pytest.raises(
        backend.ResearchCLIConfigError, match="research_service_config_invalid"
    ):
        backend.build_research_settings_kwargs(args, workspace)
    service_file.write_text(
        '{"schema":"psynova.research-cat-service.v1","schema":"duplicate"}',
        encoding="utf-8",
    )
    args.research_service_sha256 = hashlib.sha256(service_file.read_bytes()).hexdigest()
    with pytest.raises(
        backend.ResearchCLIConfigError, match="research_service_config_invalid"
    ):
        backend.build_research_settings_kwargs(args, workspace)


def test_oversized_service_config_is_rejected_after_bounded_read(tmp_path):
    workspace, args, service_file, _service_sha = _fixture(tmp_path)
    oversized = b" " * (backend._RESEARCH_SERVICE_MAX_BYTES + 1)
    service_file.write_bytes(oversized)
    args.research_service_sha256 = hashlib.sha256(oversized).hexdigest()

    with pytest.raises(backend.ResearchCLIConfigError) as exc:
        backend.build_research_settings_kwargs(args, workspace)

    assert exc.value.code == "research_service_config_invalid"
