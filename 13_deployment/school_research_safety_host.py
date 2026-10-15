"""Default-off, loopback-only Safety host for one student research source package."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationError,
    field_validator,
)
from safety_engine.domain import ActorRole, SafetyContext
from safety_engine.retrieval.research_student import (
    PINNED_CONSUMER_AGE_SCOPE,
    STUDY_END_UTC,
    ResearchStudentQualificationError,
    ResearchStudentRetrievalSafetyAdapter,
    ResearchStudentSourceRegistry,
)
from safety_engine.service import SafetyService
from safety_engine.service.result import SafetyCheckResult

HOST = "127.0.0.1"
PORT = 8191
HEALTH_PATH = "/health"
ROUTE_PATH = "/_research/safety/check-retrieval"
REQUEST_SCHEMA = "psynova.school-student-research-safety.v1"
MAX_REQUEST_BYTES = 256 * 1024


class ResearchSafetyHostError(RuntimeError):
    """Safe CLI error without argument, path, network, or request detail."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DuplicateJSONKeyError(ValueError):
    pass


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKeyError()
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise _DuplicateJSONKeyError()


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ResearchSafetyHostError("INVALID_ARGUMENTS")


class _ChunkMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source_id: StrictStr = Field(min_length=1, max_length=160)
    record_id: StrictStr = Field(min_length=1, max_length=160)
    content_hash: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    rights_scope_note: StrictStr = Field(min_length=1, max_length=2000)
    review_status: Literal["pending"]
    rights_status: Literal["verified"]
    role_scope: list[Literal["student"]]
    population_scope: list[Literal["secondary_school_student"]]
    risk_scope: list[Literal["normal"]]

    @field_validator("role_scope", "population_scope", "risk_scope")
    @classmethod
    def _single_scope_value(cls, value: list[str]) -> list[str]:
        if len(value) != 1:
            raise ValueError("scope must contain exactly one value")
        return value


class _ResearchChunk(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    chunk_id: StrictStr = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9_-]+$"
    )
    content: StrictStr = Field(min_length=1, max_length=4000)
    metadata: _ChunkMetadata


class _ResearchSafetyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["psynova.school-student-research-safety.v1"]
    request_id: StrictStr = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )
    trace_id: StrictStr = Field(
        min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"
    )
    study_ref: StrictStr = Field(min_length=1, max_length=160)
    package_id: StrictStr = Field(min_length=1, max_length=160)
    manifest_sha256: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")
    purpose: Literal["RESEARCH_SIMULATION"]
    consumer_age_scope: Literal["14-17"]
    chunks: list[_ResearchChunk] = Field(min_length=1, max_length=32)


def _require_active(
    clock: Callable[[], datetime], registry: ResearchStudentSourceRegistry
) -> None:
    if not registry.is_active():
        raise ResearchSafetyHostError("RESEARCH_STUDY_EXPIRED")
    try:
        now = clock()
    except Exception as exc:
        raise ResearchSafetyHostError("CLOCK_UNAVAILABLE") from exc
    if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
        raise ResearchSafetyHostError("CLOCK_INVALID")
    if now.astimezone(UTC) > STUDY_END_UTC:
        raise ResearchSafetyHostError("RESEARCH_STUDY_EXPIRED")


def _require_loopback_opa_environment() -> None:
    if os.environ.get("SMHAI_MANAGE_OPA", "0") == "1":
        raise ResearchSafetyHostError("SHARED_OPA_MUST_NOT_BE_MANAGED_BY_RESEARCH_HOST")
    value = os.environ.get("SMHAI_OPA_URL", "http://127.0.0.1:8181")
    try:
        parsed = urlsplit(value)
        address = ipaddress.ip_address(parsed.hostname or "")
        valid = (
            parsed.scheme == "http"
            and address.is_loopback
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
            and parsed.port is not None
        )
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ResearchSafetyHostError("SHARED_OPA_ENDPOINT_INVALID")


def _require_port_available(host: str = HOST, port: int = PORT) -> None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            probe.bind((host, port))
    except OSError as exc:
        raise ResearchSafetyHostError("RESEARCH_SAFETY_PORT_UNAVAILABLE") from exc


def preflight(
    *,
    manifest_file: Path,
    manifest_sha256: str,
    study_ref: str,
    consumer_age_scope: str,
    clock: Callable[[], datetime] | None = None,
    check_port: bool = True,
) -> ResearchStudentSourceRegistry:
    selected_clock = clock or (lambda: datetime.now(UTC))
    _require_loopback_opa_environment()
    try:
        registry = ResearchStudentSourceRegistry.load(
            manifest_file,
            expected_manifest_sha256=manifest_sha256,
            study_ref=study_ref,
            consumer_age_scope=consumer_age_scope,
            clock=selected_clock,
        )
    except ResearchStudentQualificationError as exc:
        raise ResearchSafetyHostError(exc.code) from exc
    _require_active(selected_clock, registry)
    if check_port:
        _require_port_available()
    return registry


def create_app(
    service: SafetyService,
    registry: ResearchStudentSourceRegistry,
    *,
    clock: Callable[[], datetime] | None = None,
) -> Any:
    """Create an app exposing only health and the isolated research retrieval route."""
    from fastapi.responses import JSONResponse

    selected_clock = clock or (lambda: datetime.now(UTC))
    retrieval_adapter = getattr(service, "retrieval", None)
    if not isinstance(retrieval_adapter, ResearchStudentRetrievalSafetyAdapter):
        raise ResearchSafetyHostError("RESEARCH_SAFETY_COMPOSITION_INVALID")
    if retrieval_adapter.registry is not registry:
        raise ResearchSafetyHostError("RESEARCH_SAFETY_COMPOSITION_INVALID")

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.research_only = True
    app.state.package_id = registry.package_id
    app.state.manifest_sha256 = registry.manifest_sha256
    app.state.study_ref = registry.study_ref
    app.state.consumer_age_scope = PINNED_CONSUMER_AGE_SCOPE
    app.state.professional_approval = False
    app.state.publication_eligible = False
    app.state.production_use = False

    @app.middleware("http")
    async def closed_private_surface(request: Request, call_next):
        if request.url.query:
            return JSONResponse(
                status_code=422, content={"detail": {"code": "QUERY_NOT_ALLOWED"}}
            )
        if request.url.path != HEALTH_PATH:
            try:
                _require_active(selected_clock, registry)
            except ResearchSafetyHostError as exc:
                status = 410 if exc.code == "RESEARCH_STUDY_EXPIRED" else 503
                return JSONResponse(
                    status_code=status, content={"detail": {"code": exc.code}}
                )
        return await call_next(request)

    @app.get(HEALTH_PATH, include_in_schema=False)
    async def health() -> Any:
        try:
            _require_active(selected_clock, registry)
        except ResearchSafetyHostError as exc:
            status = 410 if exc.code == "RESEARCH_STUDY_EXPIRED" else 503
            return JSONResponse(
                status_code=status,
                content={"status": "EXPIRED" if status == 410 else "NOT_READY"},
            )
        try:
            health_state = service.health()
            ready = all(health_state[name].ready for name in ("opa", "presidio"))
        except Exception:  # noqa: BLE001 - readiness must fail closed without detail
            ready = False
        if not ready:
            return JSONResponse(status_code=503, content={"status": "NOT_READY"})
        return {"status": "READY", "research_only": True, "port": PORT}

    @app.post(ROUTE_PATH, response_model=SafetyCheckResult, include_in_schema=False)
    async def check_retrieval(request: Request) -> Any:
        body = bytearray()
        try:
            async for part in request.stream():
                body.extend(part)
                if len(body) > MAX_REQUEST_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": {"code": "RESEARCH_SAFETY_REQUEST_TOO_LARGE"}
                        },
                    )
            raw_payload = json.loads(
                bytes(body).decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
            payload = _ResearchSafetyRequest.model_validate(raw_payload, strict=True)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            _DuplicateJSONKeyError,
            ValidationError,
        ):
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "RESEARCH_SAFETY_REQUEST_INVALID"}},
            )
        if (
            payload.study_ref != registry.study_ref
            or payload.package_id != registry.package_id
            or payload.manifest_sha256 != registry.manifest_sha256
            or payload.consumer_age_scope != PINNED_CONSUMER_AGE_SCOPE
            or payload.purpose != "RESEARCH_SIMULATION"
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": {"code": "RESEARCH_SAFETY_SCOPE_DENIED"}},
            )
        chunk_ids = [item.chunk_id for item in payload.chunks]
        record_ids = [item.metadata.record_id for item in payload.chunks]
        if len(set(chunk_ids)) != len(chunk_ids) or len(set(record_ids)) != len(
            record_ids
        ):
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "RESEARCH_SAFETY_REQUEST_INVALID"}},
            )
        context = SafetyContext(
            trace_id=payload.trace_id,
            request_id=payload.request_id,
            actor_role=ActorRole.STUDENT,
            age_group="ADOLESCENT",
        )
        chunks = [
            {
                "chunk_id": item.chunk_id,
                "content": item.content,
                "metadata": item.metadata.model_dump(mode="json"),
            }
            for item in payload.chunks
        ]
        try:
            result = await service.check_retrieval(context, chunks)
        except Exception:  # noqa: BLE001 - response is intentionally content-free
            return JSONResponse(
                status_code=503,
                content={"detail": {"code": "RESEARCH_SAFETY_UNAVAILABLE"}},
            )
        return result.model_dump(mode="json")

    return app


def _parser() -> _ArgumentParser:
    parser = _ArgumentParser(prog="school-research-safety")
    parser.add_argument("--manifest-file", required=True, type=Path)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--study-ref", required=True)
    parser.add_argument(
        "--consumer-age-scope", required=True, choices=[PINNED_CONSUMER_AGE_SCOPE]
    )
    parser.add_argument("--preflight-only", action="store_true")
    return parser


def run_server(
    registry: ResearchStudentSourceRegistry, *, clock: Callable[[], datetime]
) -> None:
    from safety_engine.api.factory import build_default_bundle
    from safety_engine.service import SafetyService
    from uvicorn import Config, Server

    _require_active(clock, registry)
    base_service = build_default_bundle().service
    service = SafetyService(
        privacy=base_service.privacy,
        nemo=base_service.nemo,
        qwen=base_service.qwen,
        policy=base_service.policy,
        review=base_service.review,
        crisis_templates=base_service.crisis_templates,
        config=base_service.config,
        clinical_boundary=base_service.clinical_boundary,
        disclosure=base_service.disclosure,
        retrieval=ResearchStudentRetrievalSafetyAdapter(base_service.privacy, registry),
    )
    app = create_app(service, registry, clock=clock)
    _require_active(clock, registry)
    server = Server(
        Config(
            app=app,
            host=HOST,
            port=PORT,
            log_config=None,
            access_log=False,
            server_header=False,
            date_header=False,
        )
    )
    server.run()


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        selected_clock = lambda: datetime.now(UTC)
        registry = preflight(
            manifest_file=args.manifest_file,
            manifest_sha256=args.manifest_sha256,
            study_ref=args.study_ref,
            consumer_age_scope=args.consumer_age_scope,
            clock=selected_clock,
            check_port=not args.preflight_only,
        )
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "status": "PREFLIGHT_OK",
                        "package_id": registry.package_id,
                        "manifest_sha256": registry.manifest_sha256,
                        "study_ref": registry.study_ref,
                        "consumer_age_scope": PINNED_CONSUMER_AGE_SCOPE,
                        "research_only": True,
                        "publication_eligible": False,
                        "production_use": False,
                    },
                    sort_keys=True,
                )
            )
            return 0
        run_server(registry, clock=selected_clock)
        return 0
    except ResearchSafetyHostError as exc:
        code = exc.code
    except Exception:  # noqa: BLE001 - do not echo args or startup exception data
        code = "RESEARCH_SAFETY_START_FAILED"
    print(json.dumps({"status": "BLOCKED", "code": code}, sort_keys=True))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
