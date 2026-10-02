from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy.engine import make_url

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
    specs = cli._managed_specs(
        args=argparse.Namespace(
            command="run",
            run_id="D4RUN-TEST00000001",
            backend_python=str(cli.BACKEND_PYTHON),
            rag_python=str(cli.RAG_PYTHON),
        ),
        repo_root=repo_root,
        service_root=tmp_path / "services",
        corpus_manifest_path=tmp_path / "corpus.json",
        runtime=None,
        rag_events=tmp_path / "events/rag.jsonl",
        llm_events=tmp_path / "events/llm.jsonl",
        database_credential=DatabaseCredential(
            host="127.0.0.1",
            port=3307,
            database="smhai_d4_evaluation",
            username="smhai_eval_app",
            password="pw",
        ),
    )

    backend = next(spec for spec in specs if spec.name == "d4-backend")
    assert backend.executable == cli.BACKEND_PYTHON.resolve()
    assert backend.arguments[:2] == ("-m", "harness.controlled_product_eval.evaluation_compatibility")
    assert "--fixture-json" not in backend.arguments
    assert "--run-id" in backend.arguments and "D4RUN-TEST00000001" in backend.arguments
    assert backend.environment["USERNAME"] == "d4-evaluation"
    assert "USERNAME" in backend.environment_allowlist
    assert "DB_PASSWORD" not in backend.environment
    database_url = make_url(backend.environment["DATABASE_URL"])
    assert database_url.host == "127.0.0.1"
    assert database_url.port == 3307
    assert database_url.username == "smhai_eval_app"
    assert database_url.database == "smhai_d4_evaluation"
    assert database_url.password == "pw"

    rag = next(spec for spec in specs if spec.name == "d4-rag")
    rag_home = (tmp_path / "services" / "isolated-rag-user-profile").resolve()
    assert Path(rag.environment["USERPROFILE"]) == rag_home
    assert Path(rag.environment["HOME"]) == rag_home
    assert rag_home.is_dir()
    assert Path(rag.environment["HF_HOME"]) == HF_CACHE.resolve()
    assert rag.environment["HF_HUB_OFFLINE"] == "1"
    assert rag.environment["TRANSFORMERS_OFFLINE"] == "1"
