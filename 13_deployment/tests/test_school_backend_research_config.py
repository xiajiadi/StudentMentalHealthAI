import hashlib
import json
import sys
from pathlib import Path

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
    from smhai_backend.core.config import BackendSettings

    settings = BackendSettings(
        _env_file=None, **backend.build_school_settings_kwargs(8088, 4178)
    )
    assert settings.school_research_enabled is False
    assert settings.school_research_managed_enabled is False


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
