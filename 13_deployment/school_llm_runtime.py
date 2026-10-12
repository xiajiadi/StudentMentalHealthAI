"""Isolated, local-only Ollama host for the synthetic school demo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import stat
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUNTIME_SOURCE = Path(__file__).resolve().parents[1] / "06_llm-runtime" / "src"
if str(RUNTIME_SOURCE) not in sys.path:
    sys.path.insert(0, str(RUNTIME_SOURCE))

EXPECTED_MODEL_ID = "qwen2.5-7b-instruct-school-demo"
EXPECTED_CONTRACT_MODEL_ID = "MODEL_local_primary"
EXPECTED_PROVIDER_MODEL_ID = "qwen2.5:7b-instruct-q4_K_M"
EXPECTED_MODEL_DIGEST = "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
EXPECTED_MODEL_SIZE = 4_683_087_332
EXPECTED_OLLAMA_VERSION = "0.33.3"
OLLAMA_PORT = 11437
RUNTIME_PORT = 8160
STARTUP_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class HostSettings:
    ollama_root: Path = Path(
        r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\ollama-0.33.3"
    )
    models_root: Path = Path(r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\models")
    logs_root: Path = Path(r"D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\logs")
    ollama_host: str = "127.0.0.1"
    ollama_port: int = OLLAMA_PORT
    runtime_host: str = "127.0.0.1"
    runtime_port: int = RUNTIME_PORT
    startup_timeout_seconds: float = STARTUP_TIMEOUT_SECONDS

    @property
    def ollama_executable(self) -> Path:
        return self.ollama_root / "ollama.exe"

    @property
    def ollama_endpoint(self) -> str:
        return f"http://{self.ollama_host}:{self.ollama_port}"


class HostError(RuntimeError):
    """Safe, non-sensitive error category intended for CLI reporting."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_reparse_components(path: Path) -> None:
    absolute = Path(os.path.abspath(path))
    components = (absolute, *absolute.parents)
    for component in reversed(components):
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise HostError("PATH_CHECK_FAILED") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if component.is_symlink() or attributes & reparse_flag:
            raise HostError("REPARSE_PATH_REJECTED")


def _require_file(path: Path) -> os.stat_result:
    _reject_reparse_components(path)
    try:
        metadata = path.stat()
    except OSError as exc:
        raise HostError("REQUIRED_FILE_MISSING") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise HostError("INVALID_FILE_TYPE")
    return metadata


def _require_directory(path: Path) -> None:
    _reject_reparse_components(path)
    try:
        metadata = path.stat()
    except OSError as exc:
        raise HostError("REQUIRED_DIRECTORY_MISSING") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise HostError("INVALID_DIRECTORY_TYPE")


def _validate_model_assets(
    models_root: Path,
    *,
    expected_digest: str = EXPECTED_MODEL_DIGEST,
    expected_size: int = EXPECTED_MODEL_SIZE,
) -> None:
    _require_directory(models_root)
    manifest = (
        models_root
        / "manifests"
        / "registry.ollama.ai"
        / "library"
        / "qwen2.5"
        / "7b-instruct-q4_K_M"
    )
    manifest_stat = _require_file(manifest)
    if _sha256_file(manifest) != expected_digest:
        raise HostError("MODEL_MANIFEST_DIGEST_MISMATCH")
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostError("MODEL_MANIFEST_INVALID") from exc
    config = document.get("config")
    layers = document.get("layers")
    if not isinstance(config, dict) or not isinstance(layers, list) or not layers:
        raise HostError("MODEL_MANIFEST_INVALID")
    descriptors = [config, *layers]
    total_size = 0
    for descriptor in descriptors:
        digest = descriptor.get("digest")
        size = descriptor.get("size")
        if (
            not isinstance(digest, str)
            or len(digest) != 71
            or not digest.startswith("sha256:")
            or any(character not in "0123456789abcdef" for character in digest[7:])
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise HostError("MODEL_MANIFEST_INVALID")
        blob = models_root / "blobs" / f"sha256-{digest[7:]}"
        blob_stat = _require_file(blob)
        if blob_stat.st_size != size or _sha256_file(blob) != digest[7:]:
            raise HostError("MODEL_BLOB_IDENTITY_MISMATCH")
        total_size += size
    if total_size != expected_size:
        raise HostError("MODEL_SIZE_MISMATCH")
    if manifest_stat.st_size <= 0:
        raise HostError("MODEL_MANIFEST_INVALID")


def _require_port_available(host: str, port: int) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((host, port))
    except OSError as exc:
        raise HostError("PORT_UNAVAILABLE") from exc


def preflight(
    settings: HostSettings,
    *,
    hardware: Any | None = None,
    check_ports: bool = True,
) -> Any:
    if settings.ollama_host != "127.0.0.1" or settings.runtime_host != "127.0.0.1":
        raise HostError("LOOPBACK_ONLY")
    _reject_reparse_components(settings.ollama_root)
    _reject_reparse_components(settings.ollama_executable)
    _reject_reparse_components(settings.models_root)
    _require_directory(settings.ollama_root)
    _require_directory(settings.ollama_root / "lib")
    _require_directory(settings.ollama_root / "lib" / "ollama")
    _require_file(settings.ollama_executable)
    _require_directory(settings.models_root)
    _validate_model_assets(settings.models_root)
    if check_ports:
        _require_port_available(settings.ollama_host, settings.ollama_port)
        _require_port_available(settings.runtime_host, settings.runtime_port)
    if hardware is None:
        from llm_runtime.hardware.detector import HardwareDetector

        detected_hardware = HardwareDetector().detect()
    else:
        detected_hardware = hardware
    if not bool(getattr(detected_hardware, "gpu_present", False)):
        raise HostError("GPU_UNAVAILABLE")
    return detected_hardware


def build_service(
    settings: HostSettings, *, hardware: Any, log_directory: Path | None = None
) -> Any:
    from llm_runtime.domain.models import (
        Capabilities,
        Compatibility,
        HardwareProfile,
        ModelEntry,
        ModelStatus,
    )
    from llm_runtime.domain.registry import ModelRegistry
    from llm_runtime.providers.ollama import OllamaProvider
    from llm_runtime.runtime.process import ExternalProcessBinding, ProcessMode
    from llm_runtime.runtime.registry import ProviderDefinition, ProviderRegistry
    from llm_runtime.runtime.service import RuntimeService

    entry = ModelEntry(
        logical_model_id=EXPECTED_MODEL_ID,
        contract_model_id=EXPECTED_CONTRACT_MODEL_ID,
        display_name="Qwen 2.5 7B Instruct school demo",
        family="qwen2.5",
        parameters="7B",
        provider="ollama",
        provider_model_id=EXPECTED_PROVIDER_MODEL_ID,
        digest=EXPECTED_MODEL_DIGEST,
        expected_digest=EXPECTED_MODEL_DIGEST,
        format="gguf",
        quantization="Q4_K_M",
        size_bytes=EXPECTED_MODEL_SIZE,
        capabilities=Capabilities(chat=True, stream=False, structured_output=True),
        hardware_profile=HardwareProfile.CONSUMER_GPU,
        compatibility=Compatibility.SUPPORTED,
        status=ModelStatus.DISCOVERED,
        provider_version=EXPECTED_OLLAMA_VERSION,
        fallback_model_id=None,
        fallback_eligible=False,
        context_limit=8192,
        local_only=True,
    )
    registry = ModelRegistry((entry,), registry_version="school-demo-v1")
    environment = {
        "OLLAMA_HOST": f"{settings.ollama_host}:{settings.ollama_port}",
        "OLLAMA_MODELS": str(settings.models_root),
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_CONTEXT_LENGTH": "8192",
        "OLLAMA_KV_CACHE_TYPE": "f16",
        "OLLAMA_MAX_LOADED_MODELS": "1",
        "OLLAMA_NO_CLOUD": "1",
    }
    binding = ExternalProcessBinding(
        mode=ProcessMode.MANAGED,
        command=(str(settings.ollama_executable), "serve"),
        cwd=str(settings.ollama_root),
        env=environment,
        endpoint=settings.ollama_endpoint,
        stdout_path=(str(log_directory / "ollama.stdout.log") if log_directory else None),
        stderr_path=(str(log_directory / "ollama.stderr.log") if log_directory else None),
    )
    provider = OllamaProvider(settings.ollama_endpoint, timeout_seconds=3.0)
    definition = ProviderDefinition(
        provider_id="ollama",
        provider_type="OllamaProvider",
        endpoint=settings.ollama_endpoint,
        mode=ProcessMode.MANAGED,
        enabled=True,
        local_only=True,
        process_binding=binding,
    )
    providers = ProviderRegistry({"ollama": provider}, definitions={"ollama": definition})
    return RuntimeService(
        registry,
        providers,
        hardware=hardware,
        runtime_version="0.1.0-school-demo",
        max_attempts=1,
        backoff_seconds=(),
        default_model_id=EXPECTED_MODEL_ID,
        max_generation_concurrency=1,
        acquire_timeout_seconds=5.0,
        shutdown_timeout_seconds=10.0,
        preload_primary=False,
    )


def _wait_for_provider_version(service: Any, settings: HostSettings) -> None:
    deadline = time.monotonic() + settings.startup_timeout_seconds
    provider = service.provider_registry.resolve("ollama")
    while time.monotonic() < deadline:
        health = provider.health_check()
        if health.readiness == "pass":
            if health.version != EXPECTED_OLLAMA_VERSION:
                raise HostError("OLLAMA_VERSION_MISMATCH")
            return
        time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))
    raise HostError("OLLAMA_STARTUP_TIMEOUT")


def _verify_discovery(service: Any) -> None:
    discovered = service.discover().get("ollama", [])
    model = next(
        (
            item
            for item in discovered
            if item.get("provider_model_id") == EXPECTED_PROVIDER_MODEL_ID
        ),
        None,
    )
    if model is None:
        raise HostError("MODEL_DISCOVERY_MISSING")
    if str(model.get("digest", "")).removeprefix("sha256:") != EXPECTED_MODEL_DIGEST:
        raise HostError("MODEL_DISCOVERY_DIGEST_MISMATCH")
    if model.get("size_bytes") != EXPECTED_MODEL_SIZE:
        raise HostError("MODEL_DISCOVERY_SIZE_MISMATCH")


def _new_log_directory(root: Path) -> Path:
    _reject_reparse_components(root)
    _require_directory(root)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = root / f"school-llm-runtime-{stamp}-{uuid.uuid4().hex}"
    try:
        destination.mkdir(exist_ok=False)
    except OSError as exc:
        raise HostError("LOG_DIRECTORY_CREATE_FAILED") from exc
    return destination


def run_server(settings: HostSettings, *, hardware: Any | None = None) -> None:
    from llm_runtime.api.app import Runtime, create_app
    from uvicorn import run

    detected_hardware = preflight(settings, hardware=hardware)
    logs = _new_log_directory(settings.logs_root)
    service: Any | None = None
    try:
        service = build_service(settings, hardware=detected_hardware, log_directory=logs)
        runtime = Runtime(service)
        service.provider_registry.start_managed()
        _wait_for_provider_version(service, settings)
        health = service.startup()
        if health.get("state") != "READY" or not service.ready():
            raise HostError("RUNTIME_NOT_READY")
        _verify_discovery(service)
        app = create_app(runtime=runtime)
        run(
            app,
            host=settings.runtime_host,
            port=settings.runtime_port,
            log_config=None,
            access_log=False,
        )
    finally:
        if service is not None:
            service.shutdown()
        _write_safe_status(logs, "STOPPED")


def _write_safe_status(log_directory: Path, status: str) -> None:
    payload = {"status": status, "model_id": EXPECTED_MODEL_ID}
    try:
        (log_directory / "host-status.json").write_text(
            json.dumps(payload, separators=(",", ":")), encoding="utf-8"
        )
    except OSError as exc:
        raise HostError("STATUS_WRITE_FAILED") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="school-llm-runtime")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    settings = HostSettings()
    try:
        if args.preflight_only:
            preflight(settings)
            print(json.dumps({"status": "PREFLIGHT_OK"}, separators=(",", ":")))
            return 0
        run_server(settings)
        return 0
    except HostError as exc:
        print(json.dumps({"status": "BLOCKED", "error_type": exc.code}, separators=(",", ":")))
        return 2
    except Exception as exc:  # noqa: BLE001 - fail closed with the exception type only
        print(
            json.dumps(
                {"status": "FAILED", "error_type": type(exc).__name__}, separators=(",", ":")
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
