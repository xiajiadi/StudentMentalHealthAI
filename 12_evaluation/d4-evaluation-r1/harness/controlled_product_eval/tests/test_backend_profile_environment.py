from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.engine import make_url
import pytest

from harness.controlled_product_eval import cli
from harness.controlled_product_eval.credential_provider import DatabaseCredential
from harness.controlled_product_eval.service_profiles import HF_CACHE


def test_backend_profile_uses_fixed_python_and_neutral_process_username(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    for relative in (
        Path("12_evaluation/d4-evaluation-r1"),
        Path("09_backend/src"),
        Path("11_database"),
    ):
        (repo_root / relative).mkdir(parents=True)

    monkeypatch.setattr(cli, "_python_version", lambda _path: "3.12.13")

    def lock_identity(_path, role):
        if role == "backend":
            return {
                "python_version": "3.12.13",
                "backend_lock_sha256": "a" * 64,
                "database_lock_sha256": "b" * 64,
                "installed_freeze_sha256": "c" * 64,
            }
        return {"accepted_uv_lock_sha256": "d" * 64}

    monkeypatch.setattr(cli, "_environment_lock_identity", lock_identity)
    credential = DatabaseCredential(
        host="127.0.0.1",
        port=3307,
        database="smhai_d4_evaluation",
        username="smhai_eval_app",
        password="pw",
    )
    shared = dict(
        repo_root=repo_root,
        service_root=tmp_path / "services",
        corpus_manifest_path=tmp_path / "corpus.json",
        runtime=None,
        rag_events=tmp_path / "events/rag.jsonl",
        llm_events=tmp_path / "events/llm.jsonl",
        safety_events=tmp_path / "events/safety.jsonl",
        database_credential=credential,
    )
    specs = cli._managed_specs(
        args=argparse.Namespace(
            command="run",
            run_id="D4RUN-TEST00000001",
            backend_python=str(cli.BACKEND_PYTHON),
            rag_python=str(cli.RAG_PYTHON),
        ),
        safety_observer_run_id="D4RUN-TEST00000001",
        **shared,
    )

    backend = next(spec for spec in specs if spec.name == "d4-backend")
    assert backend.executable == cli.BACKEND_PYTHON.resolve()
    assert backend.arguments[:2] == ("-m", "harness.controlled_product_eval.evaluation_compatibility")
    assert "--harness-command" in backend.arguments and "run" in backend.arguments
    assert "--fixture-json" not in backend.arguments
    assert "--run-id" in backend.arguments and "D4RUN-TEST00000001" in backend.arguments
    assert backend.environment["USERNAME"] == "d4-evaluation"
    assert backend.environment["SMHAI_SAFETY__BASE_URL"] == "http://127.0.0.1:8273"
    assert "USERNAME" in backend.environment_allowlist
    assert "DB_PASSWORD" not in backend.environment
    database_url = make_url(backend.environment["DATABASE_URL"])
    assert database_url.host == "127.0.0.1"
    assert database_url.port == 3307
    assert database_url.username == "smhai_eval_app"
    assert database_url.database == "smhai_d4_evaluation"
    assert database_url.password == "pw"

    safety_observer = next(spec for spec in specs if spec.name == "d4-safety-observer")
    assert "--run-id" in safety_observer.arguments
    assert "D4RUN-TEST00000001" in safety_observer.arguments
    assert safety_observer.readiness_url == "http://127.0.0.1:8273/health"

    rag = next(spec for spec in specs if spec.name == "d4-rag")
    rag_home = (tmp_path / "services" / "isolated-rag-user-profile").resolve()
    assert Path(rag.environment["USERPROFILE"]) == rag_home
    assert Path(rag.environment["HOME"]) == rag_home
    assert rag_home.is_dir()
    assert Path(rag.environment["HF_HOME"]) == HF_CACHE.resolve()
    assert rag.environment["HF_HUB_OFFLINE"] == "1"
    assert rag.environment["TRANSFORMERS_OFFLINE"] == "1"

    smoke_specs = cli._managed_specs(
        args=argparse.Namespace(
            command="smoke-product",
            run_id="D4SMOKE-TEST00000001",
            backend_python=str(cli.BACKEND_PYTHON),
            rag_python=str(cli.RAG_PYTHON),
        ),
        service_root=tmp_path / "smoke-services",
        safety_observer_run_id="D4SMOKE-TEST00000001",
        **{key: value for key, value in shared.items() if key != "service_root"},
    )
    smoke_backend = next(spec for spec in smoke_specs if spec.name == "d4-backend")
    assert smoke_backend.arguments[:2] == ("-m", "harness.controlled_product_eval.evaluation_compatibility")
    assert "D4SMOKE-TEST00000001" in smoke_backend.arguments
    assert "--harness-command" in smoke_backend.arguments and "smoke-product" in smoke_backend.arguments

    ordinary_specs = cli._managed_specs(
        args=argparse.Namespace(
            command="smoke-lifecycle",
            run_id="D4SMOKE-TEST00000001",
            backend_python=str(cli.BACKEND_PYTHON),
            rag_python=str(cli.RAG_PYTHON),
        ),
        service_root=tmp_path / "ordinary-services",
        safety_observer_run_id="D4SMOKE-TEST00000001",
        **{key: value for key, value in shared.items() if key != "service_root"},
    )
    ordinary_backend = next(spec for spec in ordinary_specs if spec.name == "d4-backend")
    assert ordinary_backend.arguments == ("-m", "smhai_backend.main")

    default_specs = cli._managed_specs(
        args=argparse.Namespace(
            run_id="D4SMOKE-TEST00000001",
            backend_python=str(cli.BACKEND_PYTHON),
            rag_python=str(cli.RAG_PYTHON),
        ),
        service_root=tmp_path / "default-services",
        safety_observer_run_id="D4SMOKE-TEST00000001",
        **{key: value for key, value in shared.items() if key != "service_root"},
    )
    default_backend = next(spec for spec in default_specs if spec.name == "d4-backend")
    assert default_backend.arguments == ("-m", "smhai_backend.main")

    with pytest.raises(cli.RunnerError, match="approved D4SMOKE context ID"):
        cli._managed_specs(
            args=argparse.Namespace(
                command="smoke-product",
                run_id="D4RUN-TEST00000001",
                backend_python=str(cli.BACKEND_PYTHON),
                rag_python=str(cli.RAG_PYTHON),
            ),
            service_root=tmp_path / "rejected-services",
            safety_observer_run_id="D4SMOKE-TEST00000001",
            **{key: value for key, value in shared.items() if key != "service_root"},
        )
