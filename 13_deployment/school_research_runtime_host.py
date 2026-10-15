"""Loopback-only host for staff research generation routes."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import school_llm_runtime

RUNTIME_HOST = "127.0.0.1"
RUNTIME_PORT = 8161
RUNTIME_VERSION = "0.1.0-school-demo"
STUDY_REF = "school-noncommercial-rag-research-2027-06"
STUDY_END_UTC = datetime(2027, 6, 30, 15, 59, 59, tzinfo=UTC)
ROUTE_PATH = "/internal/llm/research-programme-generations"
HEALTH_PATH = "/health"
_SCOPE = "research_programme_noncommercial_hold_only"


class ResearchRuntimeHostError(RuntimeError):
    """Stable host error that does not carry request or provider content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _now_utc(clock: Callable[[], datetime]) -> datetime:
    try:
        value = clock()
    except Exception as exc:
        raise ResearchRuntimeHostError("CLOCK_UNAVAILABLE") from exc
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ResearchRuntimeHostError("CLOCK_INVALID")
    return value.astimezone(UTC)


def _require_study_active(clock: Callable[[], datetime]) -> None:
    if _now_utc(clock) > STUDY_END_UTC:
        raise ResearchRuntimeHostError("RESEARCH_STUDY_EXPIRED")


def _settings() -> Any:
    return school_llm_runtime.HostSettings(
        runtime_host=RUNTIME_HOST,
        runtime_port=RUNTIME_PORT,
        ollama_host="127.0.0.1",
        ollama_port=school_llm_runtime.OLLAMA_PORT,
    )


def preflight(*, clock: Callable[[], datetime] | None = None) -> Any:
    selected_clock = clock or (lambda: datetime.now(UTC))
    _require_study_active(selected_clock)
    return school_llm_runtime.preflight(_settings(), check_ports=False)


def create_app(
    runtime: Any,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Any:
    """Build an app containing health and hold-only research generation routes."""

    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    from school_research_general_education_runtime import (
        attach_research_general_education_routes,
    )
    from school_research_programme_runtime import attach_research_programme_routes

    selected_clock = clock or (lambda: datetime.now(UTC))
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.research_study_ref = STUDY_REF
    app.state.research_noncommercial = True
    app.state.research_publication_eligible = False
    app.state.research_production_use = False
    app.state.research_study_end_utc = STUDY_END_UTC

    @app.middleware("http")
    async def study_expiry_guard(request: Request, call_next):
        if request.url.path == HEALTH_PATH:
            return await call_next(request)
        try:
            _require_study_active(selected_clock)
        except ResearchRuntimeHostError as exc:
            status = 410 if exc.code == "RESEARCH_STUDY_EXPIRED" else 503
            return JSONResponse(
                status_code=status,
                content={"detail": {"code": exc.code}},
            )
        return await call_next(request)

    @app.get(HEALTH_PATH, include_in_schema=False)
    async def health() -> Any:
        try:
            _require_study_active(selected_clock)
        except ResearchRuntimeHostError as exc:
            status = 410 if exc.code == "RESEARCH_STUDY_EXPIRED" else 503
            return JSONResponse(
                status_code=status,
                content={"status": "EXPIRED" if status == 410 else "UNAVAILABLE",
                         "scope": _SCOPE,
                         "runtime_version": RUNTIME_VERSION},
            )
        service = getattr(runtime, "service", None)
        ready = getattr(service, "ready", None)
        try:
            is_ready = callable(ready) and ready() is True
        except Exception:  # noqa: BLE001 - readiness exceptions stay private and fail closed
            is_ready = False
        if not is_ready:
            return JSONResponse(
                status_code=503,
                content={"status": "NOT_READY", "scope": _SCOPE,
                         "runtime_version": RUNTIME_VERSION},
            )
        return {
            "status": "READY",
            "scope": _SCOPE,
            "runtime_version": RUNTIME_VERSION,
        }

    attach_research_programme_routes(app, runtime)
    attach_research_general_education_routes(app, runtime)
    return app


def _verify_external_service(service: Any, settings: Any) -> None:
    try:
        definition = service.provider_registry.definition("ollama")
        model = service.registry.resolve_primary(service.default_model_id)
        valid = (
            settings.runtime_host == RUNTIME_HOST
            and settings.runtime_port == RUNTIME_PORT
            and settings.ollama_host == "127.0.0.1"
            and settings.ollama_port == school_llm_runtime.OLLAMA_PORT
            and definition.mode.value == "EXTERNAL"
            and definition.process_binding is None
            and definition.endpoint == settings.ollama_endpoint
            and definition.local_only is True
            and definition.provider_type == "OllamaProvider"
            and service.default_model_id == school_llm_runtime.EXPECTED_MODEL_ID
            and model.logical_model_id == school_llm_runtime.EXPECTED_MODEL_ID
            and model.contract_model_id == school_llm_runtime.EXPECTED_CONTRACT_MODEL_ID
            and model.provider == "ollama"
            and model.provider_model_id == school_llm_runtime.EXPECTED_PROVIDER_MODEL_ID
            and model.digest == school_llm_runtime.EXPECTED_MODEL_DIGEST
            and model.expected_digest == school_llm_runtime.EXPECTED_MODEL_DIGEST
            and model.size_bytes == school_llm_runtime.EXPECTED_MODEL_SIZE
            and model.provider_version == school_llm_runtime.EXPECTED_OLLAMA_VERSION
            and model.local_only is True
            and service.registry.cloud_fallback is False
            and service.registry.fallback_chain(model.logical_model_id) == ()
            and service.max_attempts == 1
            and service.backoff_seconds == ()
            and service.preload_primary is False
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ResearchRuntimeHostError("RUNTIME_CONFIGURATION_INVALID")


def run_server(
    *,
    hardware: Any | None = None,
    clock: Callable[[], datetime] | None = None,
) -> None:
    from llm_runtime.api.app import Runtime
    from llm_runtime.runtime.process import ProcessMode
    from uvicorn import Config, Server

    selected_clock = clock or (lambda: datetime.now(UTC))
    _require_study_active(selected_clock)
    settings = _settings()
    detected_hardware = school_llm_runtime.preflight(
        settings,
        hardware=hardware,
        check_ports=False,
    )
    school_llm_runtime._require_port_available(RUNTIME_HOST, RUNTIME_PORT)
    service = school_llm_runtime.build_service(
        settings,
        hardware=detected_hardware,
        provider_mode=ProcessMode.EXTERNAL.value,
    )
    try:
        _verify_external_service(service, settings)
        _require_study_active(selected_clock)
        school_llm_runtime._wait_for_provider_version(service, settings)
        health = service.startup()
        if health.get("state") != "READY" or service.ready() is not True:
            raise ResearchRuntimeHostError("RUNTIME_NOT_READY")
        school_llm_runtime._verify_discovery(service)
        _require_study_active(selected_clock)
        app = create_app(Runtime(service), clock=selected_clock)
        server = Server(
            Config(
                app=app,
                host=RUNTIME_HOST,
                port=RUNTIME_PORT,
                log_config=None,
                access_log=False,
                server_header=False,
                date_header=False,
            )
        )
        server.run()
    finally:
        # EXTERNAL mode means close this host's client without managing Ollama.
        service.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="school-research-runtime")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the fixed loopback research-only runtime host.",
    )
    args = parser.parse_args(argv)
    try:
        if args.serve:
            run_server()
        else:
            preflight()
            print(json.dumps(
                {"status": "PREFLIGHT_OK", "scope": _SCOPE,
                 "runtime_version": RUNTIME_VERSION},
                separators=(",", ":"),
            ))
        return 0
    except ResearchRuntimeHostError as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code}, separators=(",", ":")))
        return 2
    except school_llm_runtime.HostError as exc:
        print(json.dumps({"status": "BLOCKED", "code": exc.code}, separators=(",", ":")))
        return 2
    except Exception as exc:  # noqa: BLE001 - safe type only; never print provider details
        print(
            json.dumps(
                {"status": "FAILED", "error_type": type(exc).__name__},
                separators=(",", ":"),
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
