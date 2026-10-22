from __future__ import annotations

from pathlib import Path

from safety_engine.api.factory import build_default_bundle

ROOT = Path(__file__).resolve().parents[2]


def test_default_bundle_uses_dedicated_opa_runtime_directory(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "state" / "opa-runtime"
    monkeypatch.setenv("SMHAI_MANAGE_OPA", "1")
    monkeypatch.setenv("SMHAI_OPA_BINARY", str(tmp_path / "opa"))
    monkeypatch.setenv("SMHAI_OPA_URL", "http://127.0.0.1:8181")
    monkeypatch.setenv("SMHAI_OPA_RUNTIME_DIR", str(runtime_dir))

    bundle = build_default_bundle(root=ROOT)

    assert bundle.opa_manager is not None
    assert bundle.opa_manager.runtime_dir == runtime_dir
    assert bundle.opa_manager.stdout_path == runtime_dir / "opa.stdout.log"
    assert bundle.opa_manager.stderr_path == runtime_dir / "opa.stderr.log"


def test_default_bundle_preserves_module_runtime_directory_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("SMHAI_MANAGE_OPA", "1")
    monkeypatch.setenv("SMHAI_OPA_BINARY", str(tmp_path / "opa"))
    monkeypatch.setenv("SMHAI_OPA_URL", "http://127.0.0.1:8181")
    monkeypatch.delenv("SMHAI_OPA_RUNTIME_DIR", raising=False)

    bundle = build_default_bundle(root=ROOT)

    assert bundle.opa_manager is not None
    assert bundle.opa_manager.runtime_dir == ROOT / "runtime"
