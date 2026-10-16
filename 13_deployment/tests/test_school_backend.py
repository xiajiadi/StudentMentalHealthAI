import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_backend as backend


def _known_old_snapshot_revision():
    return next(
        revision
        for revision in backend.SUPPORTED_SNAPSHOT_REVISIONS
        if revision != backend.CURRENT_SCHOOL_REVISION
    )


def _configure_runtime_preflight(
    monkeypatch,
    tmp_path,
    revision_rows,
    *,
    grants=None,
    current_role="NONE",
):
    marker = {
        "workspace_id": "expected", "database": "smhai_school_demo", "port": 3308,
        "data_directory": str(tmp_path / "mysql-data"),
    }
    monkeypatch.setattr(backend, "validate_marker", lambda *_: marker)
    monkeypatch.setattr(backend, "verify_process", lambda *_: None)
    (tmp_path / "runtime-ready.json").write_text(
        json.dumps(dict(marker, state="VERIFIED")), encoding="utf-8"
    )
    private = {
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3308",
        "DB_NAME": "smhai_school_demo",
        "DB_USER": "psynova_runtime_test",
        "DB_PASSWORD": "synthetic-only",
    }
    reads = []

    def read(path):
        reads.append(path.name)
        return (
            private
            if path.name == "runtime.private.dpapi"
            else {"SMHAI_SCHOOL_CSRF_SECRET": "a" * 64}
        )

    monkeypatch.setattr(backend, "read_private", read)
    environment = {"DATABASE_URL": "preserved-on-failure", "KEEP": "preserved"}
    monkeypatch.setattr(backend.os, "environ", environment)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql):
            self.sql = sql

        def fetchone(self):
            return (current_role,)

        def fetchall(self):
            if self.sql == "SHOW GRANTS FOR CURRENT_USER()":
                return grants or (
                    ("GRANT USAGE ON *.* TO 'runtime'",),
                    (
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO 'runtime'",
                    ),
                )
            return revision_rows

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    class Driver:
        @staticmethod
        def connect(**kwargs):
            assert kwargs["password"] == private["DB_PASSWORD"]
            assert kwargs["port"] == 3308
            return Connection()

    monkeypatch.setitem(sys.modules, "pymysql", Driver)
    return reads, environment


@pytest.mark.parametrize("state", ["UNVERIFIED", "VERIFIED"])
def test_runtime_readiness_must_match_workspace(tmp_path, monkeypatch, state):
    marker = {
        "workspace_id":"expected", "database":"smhai_school_demo", "port":3308,
        "data_directory": str(tmp_path / "mysql-data"),
    }
    monkeypatch.setattr(backend, "validate_marker", lambda *args: marker)
    monkeypatch.setattr(backend, "verify_process", lambda *args: None)
    monkeypatch.setattr(backend, "read_private", lambda *args: pytest.fail("mismatched readiness must not decrypt"))
    (tmp_path / "runtime-ready.json").write_text(json.dumps(dict(marker, workspace_id="wrong", state=state)))
    with pytest.raises(backend.PreparationError):
        backend.load_runtime(tmp_path, tmp_path / "repo")


def test_missing_readiness_never_decrypts(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "validate_marker", lambda *args: {})
    monkeypatch.setattr(backend, "verify_process", lambda *args: None)
    monkeypatch.setattr(backend, "read_private", lambda *args: pytest.fail("missing readiness must not decrypt"))
    with pytest.raises(FileNotFoundError):
        backend.load_runtime(tmp_path, tmp_path / "repo")


def test_cat_port_defaults_to_original_listener_and_cli_accepts_explicit_restore_port():
    defaults = backend.build_parser().parse_args(["--workspace", "C:/synthetic/workspace"])
    restored = backend.build_parser().parse_args(
        ["--workspace", "C:/synthetic/workspace", "--cat-port", "8181"]
    )

    assert defaults.cat_port == 8180
    assert restored.cat_port == 8181


def test_general_education_worker_disable_cli_is_explicit_and_opt_in():
    defaults = backend.build_parser().parse_args(["--workspace", "C:/synthetic/workspace"])
    disabled = backend.build_parser().parse_args(
        [
            "--workspace",
            "C:/synthetic/workspace",
            "--disable-research-general-education-draft-worker",
        ]
    )

    assert defaults.disable_research_general_education_draft_worker is False
    assert disabled.disable_research_general_education_draft_worker is True


def test_explicit_cat_port_changes_only_the_copied_cat_endpoint():
    original_cat = dict(backend.MODULE_ENDPOINTS["cat"])
    original_endpoints = {name: dict(value) for name, value in backend.MODULE_ENDPOINTS.items()}

    settings = backend.build_school_settings_kwargs(8088, 4178, cat_port=8181)

    assert settings["cat"] == {"mode": "http", "base_url": "http://127.0.0.1:8181"}
    assert settings["rag"] == original_endpoints["rag"]
    assert settings["llm"] == original_endpoints["llm"]
    assert settings["safety"] == original_endpoints["safety"]
    assert backend.MODULE_ENDPOINTS["cat"] == original_cat
    assert backend.MODULE_ENDPOINTS == original_endpoints


def test_cat_port_keeps_the_selected_llm_profile_unchanged():
    settings = backend.build_school_settings_kwargs(
        8088, 4178, "school-gpu-7b", cat_port=8181
    )

    assert settings["cat"]["base_url"] == "http://127.0.0.1:8181"
    assert settings["llm"] == {
        "mode": "http",
        "base_url": "http://127.0.0.1:8160",
        "logical_model_id": "qwen2.5-7b-instruct-school-demo",
        "context_length": 8192,
    }


def test_programme_worker_cli_uses_fixed_8161_without_retargeting_normal_llm(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime_file = workspace / "runtime.json"
    runtime_file.write_text("{}", encoding="utf-8")
    service_file = workspace / "service.json"
    service_file.write_text(
        json.dumps(
            {
                "schema": backend._RESEARCH_SERVICE_SCHEMA,
                "school_scope": "school:1",
                "resource_root": str(tmp_path),
                "listener": {"host": "127.0.0.1", "port": 8182},
                "signing": {},
                "profiles": [],
                "bindings": [],
            }
        ),
        encoding="utf-8",
    )
    study_file = workspace / "study-use.json"
    study_file.write_text("{}", encoding="utf-8")
    cat_python = tmp_path / "cat-python.exe"
    cat_python.touch()
    cat_source = tmp_path / "cat-source"
    cat_source.mkdir()
    cat_dependencies = tmp_path / "cat-dependencies"
    cat_dependencies.mkdir()
    programme_manifest = tmp_path / "programme-manifest.json"
    programme_manifest.write_text('{"synthetic":true}', encoding="utf-8")
    manifest_sha = backend.hashlib.sha256(programme_manifest.read_bytes()).hexdigest()
    monkeypatch.setattr(backend, "_RESEARCH_PROGRAMME_MANIFEST_SHA256", manifest_sha)
    monkeypatch.setattr(backend, "RESEARCH_PROGRAMME_MANIFEST_SHA256", manifest_sha)
    monkeypatch.setattr(backend, "_validate_study_use_policy", lambda **_kwargs: None)

    args = backend.build_parser().parse_args(
        [
            "--workspace", str(workspace),
            "--research-runtime-file", str(runtime_file),
            "--research-runtime-sha256", backend.hashlib.sha256(runtime_file.read_bytes()).hexdigest(),
            "--research-service-file", str(service_file),
            "--research-service-sha256", backend.hashlib.sha256(service_file.read_bytes()).hexdigest(),
            "--research-cat-python", str(cat_python),
            "--research-cat-source", str(cat_source),
            "--research-cat-dependencies", str(cat_dependencies),
            "--research-study-use-file", str(study_file),
            "--research-study-use-sha256", backend.hashlib.sha256(study_file.read_bytes()).hexdigest(),
            "--research-source-rights-verified",
            "--research-latest-study-end", "2027-06-30T15:59:59Z",
            "--enable-research-programme-worker",
            "--research-programme-manifest-file", str(programme_manifest),
            "--research-programme-manifest-sha256", manifest_sha,
        ]
    )
    settings, research = backend.build_cli_settings_kwargs(args)

    assert settings["llm"]["base_url"] == "http://127.0.0.1:8160"
    assert settings["research_programme_runtime"] == {
        "mode": "http", "base_url": "http://127.0.0.1:8161"
    }
    worker = settings["research_programme_worker"]
    assert worker["enabled"] is True
    assert worker["package_manifest_sha256"] == manifest_sha
    assert worker["prompt_version"] == "1.2.0"
    assert worker["model_ref"] == "qwen2.5-7b-instruct-school-demo"
    assert worker["lease_seconds"] == 180
    assert settings["research_education_worker"]["enabled"] is False
    assert research["school_research_study_use_sha256"] == backend.hashlib.sha256(
        study_file.read_bytes()
    ).hexdigest()


def test_programme_worker_cli_requires_study_and_manifest_before_mapping(tmp_path):
    args = backend.build_parser().parse_args(
        [
            "--workspace", str(tmp_path),
            "--enable-research-programme-worker",
            "--research-programme-manifest-file", str(tmp_path / "manifest.json"),
            "--research-programme-manifest-sha256", "f" * 64,
        ]
    )
    with pytest.raises(backend.ResearchCLIConfigError) as raised:
        backend.build_research_settings_kwargs(args, tmp_path)
    assert raised.value.code == "research_programme_worker_requires_pinned_study_use"


def test_research_programme_rag_cold_import_and_bm25_build_use_locked_backend_venv():
    repo = Path(__file__).resolve().parents[2]
    backend_python = repo / "09_backend" / ".venv" / "Scripts" / "python.exe"
    code = """
import sys
from pathlib import Path
repo = Path(sys.argv[1])
sys.path.insert(0, str(repo / "13_deployment"))
import school_backend
school_backend._prepare_research_programme_rag_import(repo)
from rag_engine.domain import KnowledgeRecord
from rag_engine.research import ResearchOnlyRetriever
from rag_engine.sparse import BM25SRetriever
record = KnowledgeRecord(
    chunk_id="CHUNK_SYNTHETIC_01",
    document_id="KB_SYNTHETIC_01",
    text="synthetic public reference excerpt",
    context_text="synthetic public reference excerpt",
    metadata={},
    citation={},
    layer="policy",
)
BM25SRetriever([record]).build()
assert ResearchOnlyRetriever.__module__ == "rag_engine.research.retrieval"
"""
    environment = {
        name: os.environ[name]
        for name in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP")
        if name in os.environ
    }
    completed = subprocess.run(
        [str(backend_python), "-I", "-c", code, str(repo)],
        cwd=repo,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0


def test_general_education_draft_alone_prepares_the_rag_import(monkeypatch, tmp_path):
    import types

    import smhai_backend.core.config as config_module

    prepared = []
    monkeypatch.setattr(
        backend,
        "build_cli_settings_kwargs",
        lambda _args: (
            {
                "research_general_education_draft": {"enabled": True},
                "research_programme_worker": {"enabled": False},
                "school_research_student_conversation": {"enabled": False},
            },
            {},
        ),
    )
    monkeypatch.setattr(
        backend,
        "_prepare_research_programme_rag_import",
        lambda repo: prepared.append(repo),
    )
    monkeypatch.setattr(
        backend,
        "load_runtime",
        lambda *_args: {"database": "smhai_school_demo", "port": 3314},
    )
    monkeypatch.setattr(config_module, "BackendSettings", lambda **values: values)
    monkeypatch.setitem(
        sys.modules,
        "smhai_backend.app_factory",
        types.SimpleNamespace(create_app=lambda **_kwargs: object()),
    )
    monkeypatch.setattr(
        sys, "argv", ["school_backend.py", "--workspace", str(tmp_path), "--preflight-only"]
    )

    result = backend.main()

    assert result == 0
    assert prepared == [Path(backend.__file__).resolve().parents[1]]


@pytest.mark.parametrize("cat_port", [True, False, 8181.0, "8181", 1023, 65536])
def test_cat_port_requires_a_tcp_port_integer_in_range(cat_port):
    with pytest.raises(ValueError, match="cat_port must be between 1024 and 65535"):
        backend.build_school_settings_kwargs(8088, 4178, cat_port=cat_port)


@pytest.mark.parametrize("cat_port", [8088, 4178, 8160, 8170, 8190])
def test_cat_port_rejects_backend_frontend_and_fixed_module_collisions(cat_port):
    with pytest.raises(ValueError, match="cat_port conflicts with another service port"):
        backend.build_school_settings_kwargs(8088, 4178, cat_port=cat_port)


@pytest.mark.parametrize(
    "revision",
    [
        backend.CURRENT_SCHOOL_REVISION,
        *tuple(
            revision
            for revision in sorted(backend.SUPPORTED_SNAPSHOT_REVISIONS)
            if revision != backend.CURRENT_SCHOOL_REVISION
        )[:2],
    ],
)
def test_configuration_uses_only_verified_sealed_target(tmp_path, monkeypatch, revision):
    marker = {
        "workspace_id":"expected", "database":"smhai_school_demo", "port":3308,
        "data_directory": str(tmp_path / "mysql-data"),
    }
    monkeypatch.setattr(backend, "validate_marker", lambda *args: marker)
    monkeypatch.setattr(backend, "verify_process", lambda *args: None)
    (tmp_path / "runtime-ready.json").write_text(json.dumps(dict(marker,state="VERIFIED")))
    private = {
        "DB_HOST": "127.0.0.1",
        "DB_PORT": "3308",
        "DB_NAME": "smhai_school_demo",
        "DB_USER": "psynova_runtime_test",
        "DB_PASSWORD": "synthetic-only",
    }
    reads = []

    def read(path):
        reads.append(path.name)
        return private if path.name == "runtime.private.dpapi" else {"SMHAI_SCHOOL_CSRF_SECRET":"a" * 64}

    monkeypatch.setattr(backend, "read_private", read)
    environment = {
        "DB_PASSWORD": "wrong",
        "DATABASE_URL": "wrong",
        "SMHAI_IDENTITY_PROFILE": "legacy_demo",
        "MYSQL_PWD": "wrong",
        "KEEP": "preserved",
    }
    monkeypatch.setattr(backend.os, "environ", environment)

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self,*args):
            pass

        def execute(self,sql):
            self.sql = sql

        def fetchone(self):
            return ("NONE",)

        def fetchall(self):
            if self.sql == "SHOW GRANTS FOR CURRENT_USER()":
                return (("GRANT USAGE ON *.* TO 'runtime'",), ("GRANT SELECT, INSERT, UPDATE, DELETE ON `smhai_school_demo`.* TO 'runtime'",))
            return ((revision,),)

    class Connection:
        def cursor(self):
            return Cursor()

        def close(self):
            pass

    class Driver:
        @staticmethod
        def connect(**kwargs):
            assert kwargs["password"] == private["DB_PASSWORD"]
            assert kwargs["port"] == 3308
            return Connection()

    monkeypatch.setitem(sys.modules, "pymysql", Driver)
    if revision != backend.CURRENT_SCHOOL_REVISION:
        with pytest.raises(backend.PreparationError):
            backend.load_runtime(tmp_path, tmp_path / "repo")
        assert reads == ["runtime.private.dpapi"]
        assert environment["DATABASE_URL"] == "wrong"
    else:
        result = backend.load_runtime(tmp_path, tmp_path / "repo")
        assert result["identity_profile"] == "school_tenant"
        assert result["schema_revision"] == backend.CURRENT_SCHOOL_REVISION
        assert result["workspace_id"] == "expected"
        assert result["data_directory"] == str(tmp_path / "mysql-data")
        assert result["purpose"] == backend.RUNTIME_PURPOSE_APPLICATION
        assert result["scope"] == backend.APPLICATION_CURRENT_REVISION
        assert reads == ["runtime.private.dpapi", "school-auth.private.dpapi"]
        assert all(environment[key] == value for key,value in private.items())
        assert environment["KEEP"] == "preserved"
        assert not {"DATABASE_URL", "MYSQL_PWD", "SMHAI_IDENTITY_PROFILE"} & environment.keys()
        assert environment["DATABASE_KEY_FILE"] == str(tmp_path / "database-keys.private.dpapi")


def test_backup_purpose_allows_one_known_old_revision_without_claiming_application_ready(
    tmp_path, monkeypatch
):
    old_revision = _known_old_snapshot_revision()
    reads, environment = _configure_runtime_preflight(
        monkeypatch, tmp_path, ((old_revision,),)
    )

    result = backend.load_runtime(
        tmp_path, tmp_path / "repo", purpose=backend.RUNTIME_PURPOSE_BACKUP
    )

    assert result["schema_revision"] == old_revision
    assert result["purpose"] == backend.RUNTIME_PURPOSE_BACKUP
    assert result["scope"] == backend.BACKUP_NOT_APPLICATION_READY
    assert reads == ["runtime.private.dpapi", "school-auth.private.dpapi"]
    assert environment["KEEP"] == "preserved"


@pytest.mark.parametrize(
    "revision_rows",
    [
        (("future_revision",),),
        ((_known_old_snapshot_revision(),), (backend.CURRENT_SCHOOL_REVISION,)),
    ],
    ids=["unknown-revision", "multiple-revisions"],
)
def test_backup_purpose_rejects_unknown_or_multiple_revisions_before_auth_load(
    tmp_path, monkeypatch, revision_rows
):
    reads, environment = _configure_runtime_preflight(
        monkeypatch, tmp_path, revision_rows
    )

    with pytest.raises(backend.PreparationError, match="Required school revision unavailable"):
        backend.load_runtime(tmp_path, tmp_path / "repo", purpose=backend.RUNTIME_PURPOSE_BACKUP)

    assert reads == ["runtime.private.dpapi"]
    assert environment["DATABASE_URL"] == "preserved-on-failure"


def test_runtime_preflight_rejects_invalid_purpose_before_workspace_access(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        backend,
        "validate_marker",
        lambda *_: pytest.fail("invalid purpose must fail before workspace validation"),
    )

    with pytest.raises(
        backend.PreparationError, match="Unsupported runtime preflight purpose"
    ):
        backend.load_runtime(tmp_path, tmp_path / "repo", purpose="backup-ish")


def test_application_cli_does_not_expose_backup_purpose_override():
    with pytest.raises(SystemExit):
        backend.build_parser().parse_args(
            ["--workspace", "C:/synthetic/workspace", "--purpose", "backup"]
        )


@pytest.mark.parametrize(
    "purpose", [backend.RUNTIME_PURPOSE_APPLICATION, backend.RUNTIME_PURPOSE_BACKUP]
)
def test_backup_and_application_purpose_both_require_exact_runtime_grants(
    tmp_path, monkeypatch, purpose
):
    reads, environment = _configure_runtime_preflight(
        monkeypatch,
        tmp_path,
        ((backend.CURRENT_SCHOOL_REVISION,),),
        grants=(("GRANT USAGE ON *.* TO 'runtime'",),),
    )

    with pytest.raises(
        backend.PreparationError, match="Unexpected runtime privileges or active roles"
    ):
        backend.load_runtime(tmp_path, tmp_path / "repo", purpose=purpose)

    assert reads == ["runtime.private.dpapi"]
    assert environment["DATABASE_URL"] == "preserved-on-failure"
