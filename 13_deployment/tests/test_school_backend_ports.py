import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "09_backend" / "src"))
import school_backend as backend
from smhai_backend.core.config import BackendSettings


def test_cli_defaults_and_selected_ports():
    defaults = backend.build_parser().parse_args(["--workspace", "C:/synthetic/workspace"])
    selected = backend.build_parser().parse_args(
        ["--workspace", "C:/synthetic/workspace", "--port", "8089", "--frontend-port", "4179"]
    )
    gpu = backend.build_parser().parse_args(
        ["--workspace", "C:/synthetic/workspace", "--llm-profile", "school-gpu-7b"]
    )

    assert defaults.port == 8088
    assert defaults.frontend_port == 4178
    assert defaults.llm_profile == "default"
    assert selected.port == 8089
    assert selected.frontend_port == 4179
    assert gpu.llm_profile == "school-gpu-7b"


def test_settings_follow_cli_ports_and_keep_loopback_module_endpoints():
    settings = backend.build_school_settings_kwargs(8089, 4179)

    assert settings["host"] == "127.0.0.1"
    assert settings["port"] == 8089
    assert settings["allowed_origins"] == ["http://127.0.0.1:4179"]
    assert settings["cat"] == {"mode": "http", "base_url": "http://127.0.0.1:8180"}
    assert settings["rag"] == {"mode": "http", "base_url": "http://127.0.0.1:8170"}
    assert settings["llm"] == {"mode": "http", "base_url": "http://127.0.0.1:8160"}
    assert settings["safety"] == {"mode": "http", "base_url": "http://127.0.0.1:8190"}


def test_school_gpu_profile_uses_fixed_loopback_and_explicit_model_settings():
    settings = backend.build_school_settings_kwargs(8088, 4178, "school-gpu-7b")

    assert settings["llm"] == {
        "mode": "http",
        "base_url": "http://127.0.0.1:8160",
        "logical_model_id": "qwen2.5-7b-instruct-school-demo",
        "context_length": 8192,
    }
    assert all(
        endpoint["base_url"].startswith("http://127.0.0.1:")
        for key, endpoint in settings.items()
        if key in {"cat", "rag", "llm", "safety"}
    )

    backend_settings = BackendSettings(
        _env_file=None, school_csrf_secret="a" * 64, **settings
    )
    assert backend_settings.llm.logical_model_id == "qwen2.5-7b-instruct-school-demo"
    assert backend_settings.llm.context_length == 8192


def test_default_profile_preserves_0_5b_and_unset_context_length():
    settings = backend.build_school_settings_kwargs(8088, 4178)
    backend_settings = BackendSettings(
        _env_file=None, school_csrf_secret="a" * 64, **settings
    )

    assert backend_settings.llm.logical_model_id == "qwen2.5-0.5b-engineering"
    assert backend_settings.llm.context_length is None


def test_unknown_llm_profile_is_rejected_by_cli_and_settings_builder():
    with pytest.raises(SystemExit):
        backend.build_parser().parse_args(
            ["--workspace", "C:/synthetic/workspace", "--llm-profile", "external"]
        )
    with pytest.raises(ValueError, match="unsupported LLM profile"):
        backend.build_school_settings_kwargs(8088, 4178, "external")


@pytest.mark.parametrize(
    ("port", "frontend_port"),
    [
        (1023, 4178),
        (8088, 65536),
        (0, 4178),
        (8088, -1),
        (True, 4178),
        (8088, False),
    ],
)
def test_service_ports_outside_tcp_range_are_rejected(port, frontend_port):
    with pytest.raises(ValueError, match="between 1024 and 65535"):
        backend.build_school_settings_kwargs(port, frontend_port)


def test_generated_origin_cannot_select_an_arbitrary_host_or_scheme():
    settings = backend.build_school_settings_kwargs(8088, 4178)

    assert settings["allowed_origins"] == ["http://127.0.0.1:4178"]
    assert all(origin.startswith("http://127.0.0.1:") for origin in settings["allowed_origins"])
