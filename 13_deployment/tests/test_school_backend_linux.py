"""Offline checks for the fixed school-backend configuration."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "09_backend" / "src"))

import school_backend_linux
import verify_school_http_linux
from smhai_backend.domains.models import BackendRole


def test_school_backend_builds_valid_mysql_settings_for_all_http_clients():
    settings = school_backend_linux._build_school_backend_settings("a" * 64)

    assert settings.identity_profile == "school_tenant"
    assert settings.persistence_mode == "mysql"
    assert settings.host == "127.0.0.1"
    assert settings.port == 8088
    assert settings.docs_enabled is False
    assert settings.llm.mode == "http"
    assert settings.llm.base_url == "http://127.0.0.1:8160"
    assert settings.llm.logical_model_id == "qwen2.5-0.5b-engineering"
    assert settings.llm.context_length is None
    assert settings.cat.base_url == "http://127.0.0.1:8180"
    assert settings.rag.base_url == "http://127.0.0.1:8170"
    assert settings.safety.base_url == "http://127.0.0.1:8190"


def test_http_verifier_role_projection_matches_backend_role_contract():
    assert verify_school_http_linux.ROLE_PROJECTION["admin"] == (
        BackendRole.ADMIN.value,
        BackendRole.ADMIN.value,
    )
