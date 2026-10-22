from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = REPO_ROOT / "13_deployment" / "install_linux_school_rag_service.py"
INSTALLER_SPEC = importlib.util.spec_from_file_location("school_rag_installer", INSTALLER_PATH)
assert INSTALLER_SPEC is not None and INSTALLER_SPEC.loader is not None
INSTALLER = importlib.util.module_from_spec(INSTALLER_SPEC)
INSTALLER_SPEC.loader.exec_module(INSTALLER)


def test_school_rag_service_is_loopback_only_and_sandboxed() -> None:
    unit = (
        REPO_ROOT / "13_deployment" / "systemd" / "psynova-school-rag.service"
    ).read_text(encoding="utf-8")

    assert "User=psynova-school-demo" in unit
    assert "PYTHONPATH=/opt/psynova-school-demo/services/rag/src" in unit
    assert "SMHAI_RAG_PORT=8170" in unit
    assert "IPAddressDeny=any" in unit
    assert "IPAddressAllow=127.0.0.1/32" in unit
    assert "NoNewPrivileges=yes" in unit
    assert "ProtectSystem=strict" in unit
    assert "ProtectHome=yes" in unit
    assert "StateDirectory=psynova-school-rag" in unit
    assert "ExecStartPre=" in unit and "import bm25s" in unit
    assert "SMHAI_RAG_CORPUS=" in unit
    assert "SMHAI_RAG_DOCUMENTS=" in unit
    assert "SMHAI_RAG_REVIEW_QUEUE=" in unit
    assert "DATABASE_URL=" not in unit
    assert "API_KEY=" not in unit


def test_school_rag_config_uses_only_isolated_demo_bm25_index() -> None:
    config_path = (
        REPO_ROOT / "13_deployment" / "rag" / "school_m0_demo_bm25.v1.json"
    )
    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["environment"] == "demo"
    assert config["retrieval_mode"] == "bm25"
    index_path = config["stores"]["bm25_path"]
    assert index_path == "/var/lib/psynova-school-rag/indexes/bm25"
    assert index_path.startswith("/var/lib/")


def test_school_rag_installer_rejects_unsafe_archive_paths() -> None:
    safe_member_name = INSTALLER._safe_member_name
    allowed_payload_path = INSTALLER._allowed_payload_path

    assert safe_member_name("rag/src/rag_engine/api/app.py")
    assert not safe_member_name("/etc/systemd/system/psynova.service")
    assert not safe_member_name("rag/../../etc/passwd")
    assert not safe_member_name("rag\\src\\rag_engine\\app.py")
    assert allowed_payload_path("systemd/psynova-school-rag.service")
    assert not allowed_payload_path("systemd/other.service")
