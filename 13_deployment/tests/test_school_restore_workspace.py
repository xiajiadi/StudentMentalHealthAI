from __future__ import annotations

import base64
import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_school_runtime
import restore_school_workspace as restore_module


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "workspace.json").write_text('{"workspace_id":"source-id"}')
    backups = source / "backups"
    backups.mkdir()
    backup_file = backups / "sealed.private.dpapi"
    backup_file.write_bytes(b"synthetic-sealed-fixture")
    target = tmp_path / "new-target"
    package = {"workspace_id": "source-id", "port": 3308,
               "database_key_container_b64": base64.b64encode(b"original-sealed-key").decode()}
    calls = []

    def read_private(path):
        if path == backup_file:
            return package
        return {"DB_USER": "synthetic", "DB_PASSWORD": "synthetic"}

    def create(target, _vendor, _repo, port):
        calls.append("create")
        target.mkdir()
        marker = {"workspace_id": "new-id", "database": "smhai_school_demo",
                  "port": port, "data_directory": str(target / "mysql-data")}
        (target / "workspace.json").write_text(json.dumps(marker))
        (target / "database-keys.private.dpapi").write_bytes(b"generated-sealed-key")
        return marker

    class Connection:
        def close(self):
            calls.append("close")

    monkeypatch.setattr(restore_module, "read_private", read_private)
    monkeypatch.setattr(restore_module, "plan_restore", lambda *_a, **_kw: calls.append("preflight"))
    monkeypatch.setattr(restore_module, "validate_target", lambda *_a: calls.append("validate-target"))
    monkeypatch.setattr(restore_module, "create", create)
    monkeypatch.setattr(prepare_school_runtime, "verify_process", lambda *_a: calls.append("verify-process"))
    monkeypatch.setattr(prepare_school_runtime, "prepare", lambda *_a: calls.append("prepare-runtime"))
    monkeypatch.setattr(restore_module, "_migrate", lambda *_a: calls.append("migrate"))
    monkeypatch.setattr(restore_module, "import_snapshot", lambda *_a, **_kw: {"row_count": 3})
    monkeypatch.setattr(restore_module, "_verify_ciphertexts", lambda *_a: 2)
    monkeypatch.setitem(sys.modules, "pymysql", types.SimpleNamespace(connect=lambda **_kw: Connection()))
    return backup_file, source, target, tmp_path / "vendor", tmp_path / "repo", package, calls


def run(scenario, port=3309):
    return restore_module.restore(*scenario[:5], port)


def test_full_fake_restore_preserves_source_and_unused_generated_keys(scenario):
    backup, source, target, *_rest = scenario
    before = backup.read_bytes()
    result = run(scenario)
    assert result["ready"] is False
    assert result["ciphertext_count"] == 2
    assert (target / "database-keys.private.dpapi").read_bytes() == b"original-sealed-key"
    assert (target / "generated-unused-keys.private.dpapi").read_bytes() == b"generated-sealed-key"
    assert backup.read_bytes() == before
    assert not (source / "restore-state.json").exists()
    assert scenario[-1].index("preflight") < scenario[-1].index("create")
    assert scenario[-1].index("verify-process") < scenario[-1].index("migrate")


def test_source_port_rejected_before_target_creation(scenario):
    with pytest.raises(ValueError, match="different isolated port"):
        run(scenario, 3308)
    assert "create" not in scenario[-1]


def test_overlap_rejected_before_target_creation(scenario):
    overlap = (*scenario[:2], scenario[1] / "nested-target", *scenario[3:])
    with pytest.raises(ValueError, match="must not overlap"):
        run(overlap)
    assert "create" not in scenario[-1]


def test_preflight_failure_does_not_create_target(scenario, monkeypatch):
    def reject(*_a, **_kw):
        raise ValueError("invalid snapshot")

    monkeypatch.setattr(restore_module, "plan_restore", reject)
    with pytest.raises(ValueError, match="invalid snapshot"):
        run(scenario)
    assert not scenario[2].exists()


def test_failed_import_preserves_target_and_records_only_error_type(scenario, monkeypatch):
    def reject(*_a, **_kw):
        raise RuntimeError("synthetic sensitive row must not be persisted")

    monkeypatch.setattr(restore_module, "import_snapshot", reject)
    with pytest.raises(RuntimeError) as error:
        run(scenario)
    state = (scenario[2] / "restore-state.json").read_text()
    assert "FAILED_PRESERVED" in state and "SCHEMA_READY" in state
    assert "sensitive row" not in state and "sensitive row" not in str(error.value)
    assert (scenario[2] / "database-keys.private.dpapi").read_bytes() == b"generated-sealed-key"
    assert "close" in scenario[-1]
    assert "prepare-runtime" not in scenario[-1]
