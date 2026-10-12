from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import school_llm_runtime as host
from llm_runtime.api import app as runtime_api
from llm_runtime.domain.models import Compatibility, ModelStatus


class FakeRuntimeService:
    def __init__(self) -> None:
        self.process_started = 0
        self.shutdown_count = 0
        self.startup_count = 0
        self.provider_registry = SimpleNamespace(start_managed=self._start_managed)

    def _start_managed(self):
        self.process_started += 1
        return {"ollama": {"owned": True}}

    def startup(self):
        self.startup_count += 1
        return {"state": "READY"}

    def ready(self):
        return True

    def shutdown(self):
        self.shutdown_count += 1


def _stub_run_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service: FakeRuntimeService
) -> host.HostSettings:
    settings = host.HostSettings(logs_root=tmp_path)
    monkeypatch.setattr(host, "preflight", lambda *_args, **_kwargs: SimpleNamespace(gpu_present=True))
    monkeypatch.setattr(
        host,
        "build_service",
        lambda *_args, **_kwargs: service,
    )
    return settings


def _write_model_fixture(root: Path) -> tuple[str, int]:
    (root / "manifests" / "registry.ollama.ai" / "library" / "qwen2.5").mkdir(
        parents=True
    )
    (root / "blobs").mkdir()
    config_bytes = b"config fixture"
    layer_bytes = b"model fixture"
    config_digest = hashlib.sha256(config_bytes).hexdigest()
    layer_digest = hashlib.sha256(layer_bytes).hexdigest()
    (root / "blobs" / f"sha256-{config_digest}").write_bytes(config_bytes)
    (root / "blobs" / f"sha256-{layer_digest}").write_bytes(layer_bytes)
    manifest = root / "manifests" / "registry.ollama.ai" / "library" / "qwen2.5" / (
        "7b-instruct-q4_K_M"
    )
    manifest_bytes = json.dumps(
        {
            "config": {"digest": f"sha256:{config_digest}", "size": len(config_bytes)},
            "layers": [{"digest": f"sha256:{layer_digest}", "size": len(layer_bytes)}],
        },
        separators=(",", ":"),
    ).encode()
    manifest.write_bytes(manifest_bytes)
    return hashlib.sha256(manifest_bytes).hexdigest(), len(config_bytes) + len(layer_bytes)


def test_model_asset_validation_checks_manifest_and_every_blob(tmp_path: Path) -> None:
    expected_digest, expected_size = _write_model_fixture(tmp_path)
    host._validate_model_assets(
        tmp_path,
        expected_digest=expected_digest,
        expected_size=expected_size,
    )

    blob = next((tmp_path / "blobs").iterdir())
    blob.write_bytes(b"tampered")
    with pytest.raises(host.HostError, match="MODEL_BLOB_IDENTITY_MISMATCH"):
        host._validate_model_assets(
            tmp_path,
            expected_digest=expected_digest,
            expected_size=expected_size,
        )


def test_model_asset_validation_rejects_manifest_digest_mismatch(tmp_path: Path) -> None:
    expected_digest, expected_size = _write_model_fixture(tmp_path)
    with pytest.raises(host.HostError, match="MODEL_MANIFEST_DIGEST_MISMATCH"):
        host._validate_model_assets(
            tmp_path,
            expected_digest="0" * 64,
            expected_size=expected_size,
        )
    assert len(expected_digest) == 64


def test_preflight_checks_ports_and_gpu_without_starting_services(monkeypatch) -> None:
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(host, "_reject_reparse_components", lambda _path: None)
    monkeypatch.setattr(host, "_require_directory", lambda _path: None)
    monkeypatch.setattr(host, "_require_file", lambda _path: SimpleNamespace(st_mode=0o100000))
    monkeypatch.setattr(host, "_validate_model_assets", lambda _path: None)
    monkeypatch.setattr(host, "_require_port_available", lambda address, port: calls.append((address, port)))
    gpu = SimpleNamespace(gpu_present=True)

    assert host.preflight(host.HostSettings(), hardware=gpu) is gpu
    assert calls == [("127.0.0.1", host.OLLAMA_PORT), ("127.0.0.1", host.RUNTIME_PORT)]


def test_preflight_fails_closed_without_gpu(monkeypatch) -> None:
    monkeypatch.setattr(host, "_require_port_available", lambda *_args: None)
    monkeypatch.setattr(host, "_reject_reparse_components", lambda _path: None)
    monkeypatch.setattr(host, "_require_directory", lambda _path: None)
    monkeypatch.setattr(host, "_require_file", lambda _path: SimpleNamespace(st_mode=0o100000))
    monkeypatch.setattr(host, "_validate_model_assets", lambda _path: None)
    with pytest.raises(host.HostError, match="GPU_UNAVAILABLE"):
        host.preflight(host.HostSettings(), hardware=SimpleNamespace(gpu_present=False))


def test_preflight_rejects_non_loopback_before_touching_assets() -> None:
    settings = host.HostSettings(ollama_host="0.0.0.0")
    with pytest.raises(host.HostError, match="LOOPBACK_ONLY"):
        host.preflight(settings, hardware=SimpleNamespace(gpu_present=True))


def test_build_service_registers_one_exact_local_model(tmp_path: Path) -> None:
    service = host.build_service(
        host.HostSettings(
            ollama_root=tmp_path / "ollama",
            models_root=tmp_path / "models",
        ),
        hardware=SimpleNamespace(gpu_present=True),
        log_directory=tmp_path / "logs",
    )

    assert len(service.registry.all()) == 1
    entry = service.registry.resolve(host.EXPECTED_MODEL_ID)
    assert entry.contract_model_id == "MODEL_local_primary"
    assert entry.provider_model_id == host.EXPECTED_PROVIDER_MODEL_ID
    assert entry.digest == host.EXPECTED_MODEL_DIGEST
    assert entry.expected_digest == host.EXPECTED_MODEL_DIGEST
    assert entry.size_bytes == host.EXPECTED_MODEL_SIZE
    assert entry.context_limit == 8192
    assert entry.fallback_model_id is None
    assert service.max_attempts == 1
    assert service.backoff_seconds == ()
    definition = service.provider_registry.definition("ollama")
    assert definition.mode.value == "MANAGED"
    assert definition.local_only is True
    binding = definition.process_binding
    assert binding is not None
    assert binding.command == (str(tmp_path / "ollama" / "ollama.exe"), "serve")
    assert binding.env["OLLAMA_HOST"] == "127.0.0.1:11437"
    assert binding.env["OLLAMA_MODELS"] == str(tmp_path / "models")
    assert binding.env["OLLAMA_NUM_PARALLEL"] == "1"
    assert binding.env["OLLAMA_CONTEXT_LENGTH"] == "8192"
    assert binding.env["OLLAMA_KV_CACHE_TYPE"] == "f16"
    assert binding.env["OLLAMA_MAX_LOADED_MODELS"] == "1"
    assert binding.env["OLLAMA_NO_CLOUD"] == "1"
    assert binding.stdout_path == str(tmp_path / "logs" / "ollama.stdout.log")
    assert binding.stderr_path == str(tmp_path / "logs" / "ollama.stderr.log")
    service.shutdown()


def test_registry_reconcile_accepts_real_unprefixed_digest_and_resolves_model(
    tmp_path: Path,
) -> None:
    service = host.build_service(
        host.HostSettings(ollama_root=tmp_path / "ollama", models_root=tmp_path / "models"),
        hardware=SimpleNamespace(gpu_present=True),
    )
    updated = service.registry.reconcile_discovery(
        "ollama",
        [
            {
                "provider_model_id": host.EXPECTED_PROVIDER_MODEL_ID,
                "digest": host.EXPECTED_MODEL_DIGEST,
                "size_bytes": host.EXPECTED_MODEL_SIZE,
                "provider_version": host.EXPECTED_OLLAMA_VERSION,
            }
        ],
    )

    assert len(updated) == 1
    assert updated[0].status is ModelStatus.READY
    assert updated[0].compatibility is Compatibility.SUPPORTED
    resolved = service._resolve_request_model(
        SimpleNamespace(
            logical_model_id=host.EXPECTED_MODEL_ID,
            contract_model_id=host.EXPECTED_CONTRACT_MODEL_ID,
        )
    )
    assert resolved is updated[0]
    service.shutdown()


def test_discovery_requires_exact_model_digest_and_size() -> None:
    service = SimpleNamespace(
        discover=lambda: {
            "ollama": [
                {
                    "provider_model_id": host.EXPECTED_PROVIDER_MODEL_ID,
                    "digest": f"sha256:{host.EXPECTED_MODEL_DIGEST}",
                    "size_bytes": host.EXPECTED_MODEL_SIZE,
                }
            ]
        }
    )
    host._verify_discovery(service)

    service.discover = lambda: {
        "ollama": [
            {
                "provider_model_id": host.EXPECTED_PROVIDER_MODEL_ID,
                "digest": "sha256:" + "0" * 64,
                "size_bytes": host.EXPECTED_MODEL_SIZE,
            }
        ]
    }
    with pytest.raises(host.HostError, match="MODEL_DISCOVERY_DIGEST_MISMATCH"):
        host._verify_discovery(service)


def test_provider_version_poll_is_bounded_and_exact() -> None:
    provider = SimpleNamespace(
        health_check=lambda: SimpleNamespace(readiness="pass", version="0.33.3")
    )
    service = SimpleNamespace(
        provider_registry=SimpleNamespace(resolve=lambda _provider_id: provider)
    )
    host._wait_for_provider_version(
        service,
        host.HostSettings(startup_timeout_seconds=0.1),
    )

    provider.health_check = lambda: SimpleNamespace(readiness="pass", version="0.1.0")
    with pytest.raises(host.HostError, match="OLLAMA_VERSION_MISMATCH"):
        host._wait_for_provider_version(
            service,
            host.HostSettings(startup_timeout_seconds=0.1),
        )


def test_run_server_shuts_down_owned_process_when_version_check_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = FakeRuntimeService()
    settings = _stub_run_server(monkeypatch, tmp_path, service)

    def fail_version(_service, _settings):
        raise host.HostError("OLLAMA_VERSION_MISMATCH")

    monkeypatch.setattr(host, "_wait_for_provider_version", fail_version)
    with pytest.raises(host.HostError, match="OLLAMA_VERSION_MISMATCH"):
        host.run_server(settings, hardware=SimpleNamespace(gpu_present=True))

    assert service.process_started == 1
    assert service.startup_count == 0
    assert service.shutdown_count == 1


def test_run_server_shuts_down_owned_process_when_discovery_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = FakeRuntimeService()
    settings = _stub_run_server(monkeypatch, tmp_path, service)
    monkeypatch.setattr(host, "_wait_for_provider_version", lambda *_args: None)

    def fail_discovery(_service):
        raise host.HostError("MODEL_DISCOVERY_SIZE_MISMATCH")

    monkeypatch.setattr(host, "_verify_discovery", fail_discovery)

    with pytest.raises(host.HostError, match="MODEL_DISCOVERY_SIZE_MISMATCH"):
        host.run_server(settings, hardware=SimpleNamespace(gpu_present=True))

    assert service.process_started == 1
    assert service.startup_count == 1
    assert service.shutdown_count == 1


def test_run_server_shuts_down_owned_process_after_api_server_returns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    service = FakeRuntimeService()
    settings = _stub_run_server(monkeypatch, tmp_path, service)
    run_calls: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(host, "_wait_for_provider_version", lambda *_args: None)
    monkeypatch.setattr(host, "_verify_discovery", lambda _service: None)
    from fastapi import FastAPI

    monkeypatch.setattr(runtime_api, "create_app", lambda *, runtime: FastAPI())
    monkeypatch.setattr(
        "uvicorn.run",
        lambda app, **kwargs: run_calls.append((app, kwargs)),
    )

    host.run_server(settings, hardware=SimpleNamespace(gpu_present=True))

    assert service.process_started == 1
    assert service.startup_count == 1
    assert service.shutdown_count == 1
    assert run_calls[0][1]["host"] == "127.0.0.1"
    assert run_calls[0][1]["port"] == host.RUNTIME_PORT
    assert any(
        route.path == "/internal/llm/independent-generations"
        for route in run_calls[0][0].routes
    )


def test_preflight_only_returns_safe_status_without_server(monkeypatch, capsys) -> None:
    monkeypatch.setattr(host, "preflight", lambda _settings: SimpleNamespace(gpu_present=True))
    monkeypatch.setattr(host, "run_server", lambda _settings: pytest.fail("server must not start"))

    assert host.main(["--preflight-only"]) == 0
    assert capsys.readouterr().out == '{"status":"PREFLIGHT_OK"}\n'


def test_cli_failure_reports_type_without_exception_text(monkeypatch, capsys) -> None:
    def fail_preflight(_settings):
        raise RuntimeError("sensitive path detail")

    monkeypatch.setattr(
        host,
        "preflight",
        fail_preflight,
    )

    assert host.main(["--preflight-only"]) == 1
    output = capsys.readouterr().out
    assert output == '{"status":"FAILED","error_type":"RuntimeError"}\n'
    assert "sensitive path detail" not in output
