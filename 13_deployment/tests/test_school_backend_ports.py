import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_backend as backend


def test_cli_defaults_and_selected_ports():
    defaults = backend.build_parser().parse_args(["--workspace", "C:/synthetic/workspace"])
    selected = backend.build_parser().parse_args(
        ["--workspace", "C:/synthetic/workspace", "--port", "8089", "--frontend-port", "4179"]
    )

    assert defaults.port == 8088
    assert defaults.frontend_port == 4178
    assert selected.port == 8089
    assert selected.frontend_port == 4179


def test_settings_follow_cli_ports_and_keep_loopback_module_endpoints():
    settings = backend.build_school_settings_kwargs(8089, 4179)

    assert settings["host"] == "127.0.0.1"
    assert settings["port"] == 8089
    assert settings["allowed_origins"] == ["http://127.0.0.1:4179"]
    assert settings["cat"] == {"mode": "http", "base_url": "http://127.0.0.1:8180"}
    assert settings["rag"] == {"mode": "http", "base_url": "http://127.0.0.1:8170"}
    assert settings["llm"] == {"mode": "http", "base_url": "http://127.0.0.1:8160"}
    assert settings["safety"] == {"mode": "http", "base_url": "http://127.0.0.1:8190"}


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
