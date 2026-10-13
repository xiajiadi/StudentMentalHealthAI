"""Loopback CAT service for the Round 1 integration path.

The process owns provider sessions and exposes only item presentation,
response recording, and the frozen ``assessment.v1`` projection. Provider objects
remain private. Separate internal management routes expose synthetic documents
only through the authenticated school specialist gateway.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from cat_engine.api.assets import (
    BankDocument,
    ConfigDocument,
    ValidateAssetsRequest,
    create_assets_router,
    validate_documents,
)
from cat_engine.api.management import create_management_router
from cat_engine.domain.config import CATConfig
from cat_engine.domain.enums import ResponseStatus, SessionStatus
from cat_engine.domain.errors import ValidationError as CATValidationError
from cat_engine.domain.item_bank import ItemBank
from cat_engine.domain.result import RiskSnapshot
from cat_engine.domain.session import Session
from cat_engine.providers.adaptivetesting_provider import AdaptiveTestingProvider
from cat_engine.service.cat_service import CATService


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assessment_id: str = Field(pattern=r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    subject_id: str = Field(pattern=r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    instrument_id: str = Field(min_length=1, max_length=160)
    instrument_version: str = Field(min_length=1, max_length=64)


class SavedSessionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    assessment_id: str = Field(pattern=r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    subject_id: str = Field(pattern=r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    instrument_id: str = Field(min_length=1, max_length=160)
    instrument_version: str = Field(min_length=1, max_length=64)
    binding_ref: str = Field(pattern=r"^CSBIND_[A-Za-z0-9-]{36}$")
    activation_ref: str = Field(pattern=r"^CACT_[A-Za-z0-9-]{36}$")
    plan_version_ref: str = Field(pattern=r"^CPVER_[A-Za-z0-9-]{36}$")
    bank_version_ref: str = Field(pattern=r"^CBVER_[A-Za-z0-9-]{36}$")
    bank_document: BankDocument
    config_document: ConfigDocument


@dataclass(frozen=True)
class SessionExecutionBinding:
    mode: str
    binding_ref: str | None = None
    activation_ref: str | None = None
    plan_version_ref: str | None = None
    bank_version_ref: str | None = None
    bank_document_digest: str | None = None
    config_document_digest: str | None = None

    def saved_metadata(self) -> dict[str, str] | None:
        if self.mode != "SAVED_VERSION":
            return None
        assert self.binding_ref is not None
        assert self.activation_ref is not None
        assert self.plan_version_ref is not None
        assert self.bank_version_ref is not None
        return {
            "binding_ref": self.binding_ref,
            "activation_ref": self.activation_ref,
            "plan_version_ref": self.plan_version_ref,
            "bank_version_ref": self.bank_version_ref,
        }


def _document_digest(document: dict[str, Any]) -> str:
    canonical = json.dumps(
        document, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(pattern=r"^ITEM_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    response: str | int | float | bool


def _same_json_value(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int or int/float coercions."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return all(type(key) is str for key in left) and left.keys() == right.keys() and all(
            _same_json_value(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _same_json_value(a, b) for a, b in zip(left, right)
        )
    if type(left) is float:
        return math.isfinite(left) and left == right
    if left is None or type(left) in (str, int, bool):
        return left == right
    return False


class CompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manual: bool = False


class CatRuntime:
    """Process-local CAT session registry and immutable runtime assets."""

    def __init__(self) -> None:
        module_root = Path(__file__).resolve().parents[3]
        config_path = Path(
            os.environ.get(
                "SMHAI_CAT_CONFIG", module_root / "fixtures" / "demo_cat_config.v1.json"
            )
        )
        bank_path = Path(os.environ.get("SMHAI_CAT_ITEM_BANK", module_root / "fixtures" / "synthetic_item_bank.v1.json"))
        self.config_path = config_path.resolve()
        self.bank_path = bank_path.resolve()
        self.config = CATConfig.from_dict(_read_json(self.config_path))
        self.item_bank = ItemBank.from_json(self.bank_path)
        self.service = CATService(AdaptiveTestingProvider())
        self.sessions: dict[str, Session] = {}
        self.session_bindings: dict[str, SessionExecutionBinding] = {}

    def health(self) -> dict[str, Any]:
        fixture_only = all(
            self.session_bindings.get(
                assessment_id, SessionExecutionBinding(mode="FIXTURE")
            ).mode == "FIXTURE"
            for assessment_id in self.sessions
        )
        return {
            "status": "READY",
            "service": "cat",
            "provider": "adaptivetesting",
            "provider_version": "adaptivetesting-1.2.1",
            "item_bank_id": self.item_bank.item_bank_id,
            "item_bank_version": self.item_bank.version,
            "config_version": self.config.config_version,
            "session_count": len(self.sessions),
            "synthetic_fixture_only": fixture_only,
            "supports_saved_versions": True,
        }

    def start(self, request: StartRequest) -> dict[str, Any]:
        instrument_version = str(
            self.item_bank.metadata.get("instrument_version", self.item_bank.version)
        )
        if (
            request.instrument_id != self.item_bank.instrument_id
            or request.instrument_version != instrument_version
        ):
            raise HTTPException(
                status_code=422,
                detail="instrument does not match the published CAT fixture",
            )
        existing = self.sessions.get(request.assessment_id)
        if existing is None:
            session = self.service.create_session(
                request.assessment_id,
                request.subject_id,
                self.item_bank,
                self.config,
            )
            self.sessions[request.assessment_id] = session
            self.session_bindings[request.assessment_id] = SessionExecutionBinding(
                mode="FIXTURE"
            )
        else:
            binding = self.session_bindings.get(
                request.assessment_id, SessionExecutionBinding(mode="FIXTURE")
            )
            if binding.mode != "FIXTURE":
                raise HTTPException(status_code=409, detail="assessment binding does not match")
            if existing.subject_id != request.subject_id:
                raise HTTPException(status_code=409, detail="assessment belongs to another subject")
            session = existing
        return self._start_session(session)

    def start_saved(
        self,
        request: SavedSessionStartRequest,
        item_bank: ItemBank,
        config: CATConfig,
        bank_document_digest: str,
        config_document_digest: str,
    ) -> dict[str, Any]:
        requested_binding = SessionExecutionBinding(
            mode="SAVED_VERSION",
            binding_ref=request.binding_ref,
            activation_ref=request.activation_ref,
            plan_version_ref=request.plan_version_ref,
            bank_version_ref=request.bank_version_ref,
            bank_document_digest=bank_document_digest,
            config_document_digest=config_document_digest,
        )
        existing = self.sessions.get(request.assessment_id)
        if existing is None:
            session = self.service.create_session(
                request.assessment_id, request.subject_id, item_bank, config
            )
            self.sessions[request.assessment_id] = session
            self.session_bindings[request.assessment_id] = requested_binding
        else:
            binding = self.session_bindings.get(request.assessment_id)
            if (
                existing.subject_id != request.subject_id
                or binding != requested_binding
            ):
                raise HTTPException(status_code=409, detail="assessment binding does not match")
            session = existing
        return self._start_session(session)

    def _start_session(self, session: Session) -> dict[str, Any]:
        if session.selected_item_id is None and session.status.value in {"INITIALIZED", "IN_PROGRESS"}:
            try:
                self.service.next_item(session)
            except Exception as exc:
                raise _domain_error(exc) from exc
        return self.state(session)

    def submit(self, assessment_id: str, request: ResponseRequest) -> dict[str, Any]:
        session = self._session(assessment_id)
        if session.selected_item_id != request.item_id:
            if self._is_exact_last_response_retry(assessment_id, session, request):
                return self.state(session)
            raise HTTPException(
                status_code=409,
                detail="response item does not match the currently presented item",
            )
        try:
            self.service.submit_response(session, request.response)
            if session.status.value == "IN_PROGRESS" and session.selected_item_id is None:
                if not self._should_stop(session):
                    self.service.next_item(session)
        except Exception as exc:
            raise _domain_error(exc) from exc
        return self.state(session)

    def _is_exact_last_response_retry(
        self, assessment_id: str, session: Session, request: ResponseRequest
    ) -> bool:
        if (
            session.assessment_id != assessment_id
            or self.sessions.get(assessment_id) is not session
            or session.status is not SessionStatus.IN_PROGRESS
            or session.provider_session is None
            or session.selected_item_id == request.item_id
            or not session.traces
        ):
            return False

        binding = self.session_bindings.get(assessment_id)
        if binding is None:
            return False
        binding_fields = (
            binding.binding_ref,
            binding.activation_ref,
            binding.plan_version_ref,
            binding.bank_version_ref,
            binding.bank_document_digest,
            binding.config_document_digest,
        )
        if binding.mode == "FIXTURE":
            if any(value is not None for value in binding_fields):
                return False
        elif binding.mode == "SAVED_VERSION":
            if any(not isinstance(value, str) or not value for value in binding_fields):
                return False
        else:
            return False

        last_trace = session.traces[-1]
        return (
            last_trace.response_status is ResponseStatus.ANSWERED
            and last_trace.item_id == request.item_id
            and _same_json_value(last_trace.response, request.response)
        )

    def complete(self, assessment_id: str, request: CompleteRequest) -> dict[str, Any]:
        session = self._session(assessment_id)
        try:
            result = self.service.complete(session, manual=request.manual)
            assessment = self.service.assessment(
                result,
                RiskSnapshot(
                    level="normal",
                    need_human_review=False,
                    reason_codes=("SYNTHETIC_ENGINEERING_FIXTURE",),
                    ruleset_id="RULESET_synthetic_cat_v1",
                ),
            )
        except Exception as exc:
            raise _domain_error(exc) from exc
        return {
            "assessment": assessment,
            "state": self.state(session),
            "trace": [trace.to_dict() for trace in result.traces],
            "stopping_reason": result.stopping_reason.value,
            "provider": {
                "name": "adaptivetesting",
                "version": result.provider_version,
                "item_bank_version": result.item_bank_version,
                "config_version": result.config_version,
            },
        }

    def state(self, session: Session) -> dict[str, Any]:
        item: dict[str, Any] | None = None
        if session.selected_item_id is not None:
            selected = session.item_bank.item_by_id(session.selected_item_id)
            item = {
                "item_id": selected.item_id,
                "prompt": selected.stem,
                "response_type": selected.response_type,
                "options": [
                    {"value": option, "label": option}
                    for option in selected.response_options
                ],
            }
        administered = len(session.traces)
        binding = self.session_bindings.get(
            session.assessment_id, SessionExecutionBinding(mode="FIXTURE")
        )
        return {
            "assessment_id": session.assessment_id,
            "subject_id": session.subject_id,
            "started_at": session.started_at,
            "status": "completed" if session.status.value == "COMPLETED" else "in_progress",
            "current_item": item,
            "selected_item_id": session.selected_item_id,
            "current_index": administered,
            "answered_count": sum(1 for trace in session.traces if trace.response_status.value == "answered"),
            "administered_count": administered,
            "can_complete": session.status.value == "IN_PROGRESS" and session.selected_item_id is None and self._should_stop(session),
            "max_items": session.config.max_items,
            "item_bank_version": session.item_bank.version,
            "config_version": session.config.config_version,
            "provider_version": "adaptivetesting-1.2.1",
            "synthetic_fixture_only": binding.mode == "FIXTURE",
            "synthetic_engineering_only": True,
            "cat_binding_mode": binding.mode,
            "saved_binding": binding.saved_metadata(),
        }

    def _session(self, assessment_id: str) -> Session:
        session = self.sessions.get(assessment_id)
        if session is None:
            raise HTTPException(status_code=404, detail="CAT session not found")
        return session

    def _should_stop(self, session: Session) -> bool:
        if session.provider_session is None:
            return False
        return self.service.provider.should_stop(session.provider_session).should_stop


def _read_json(path: Path) -> dict[str, Any]:
    import json

    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"CAT configuration must be an object: {path}")
    return value


def _domain_error(exc: Exception) -> HTTPException:
    message = str(exc)
    status = 409 if "cannot" in message.lower() or "await" in message.lower() else 422
    return HTTPException(status_code=status, detail=message[:300])


def create_app(*, runtime: CatRuntime | None = None) -> FastAPI:
    runtime = runtime or CatRuntime()
    simulation_lock = Lock()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.cat_runtime = runtime
        yield

    app = FastAPI(
        title="StudentMentalHealthAI CAT Service",
        version="0.1.0",
        description="Loopback CAT transport over the synthetic published item bank.",
        lifespan=lifespan,
    )
    app.state.cat_runtime = runtime
    app.include_router(create_management_router(runtime, simulation_lock))
    app.include_router(create_assets_router(runtime, simulation_lock))

    @app.get("/health/live", operation_id="catLiveHealth")
    async def health_live() -> dict[str, Any]:
        return {"status": "LIVE", "service": "cat"}

    @app.get("/health/ready", operation_id="catReadyHealth")
    async def health_ready() -> dict[str, Any]:
        return runtime.health()

    @app.get("/health", operation_id="catHealth")
    async def health() -> dict[str, Any]:
        return runtime.health()

    @app.get("/capabilities", operation_id="catCapabilities")
    async def capabilities() -> dict[str, Any]:
        return {
            "service": "cat",
            "transport": "http",
            "operations": [
                "start", "state", "submit_response", "complete",
                "saved_session_start",
                "management_catalog", "management_simulation",
                "management_asset_simulation",
            ],
            "provider": "adaptivetesting-1.2.1",
            "synthetic_fixture_only": False,
            "synthetic_engineering_only": True,
            "supports_saved_versions": True,
        }

    @app.post("/internal/cat/sessions", operation_id="catCreateSession")
    async def create_session(request: StartRequest) -> dict[str, Any]:
        return runtime.start(request)

    @app.post("/internal/cat/saved-sessions", operation_id="catCreateSavedSession")
    async def create_saved_session(
        request: SavedSessionStartRequest,
        http_request: Request,
    ) -> dict[str, Any]:
        try:
            raw_payload = json.loads(await http_request.body())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=422, detail="saved CAT assets are invalid") from exc
        if not isinstance(raw_payload, dict):
            raise HTTPException(status_code=422, detail="saved CAT assets are invalid")

        validated = validate_documents(
            ValidateAssetsRequest(
                bank_document=request.bank_document,
                config_document=request.config_document,
            )
        )
        bank_document = validated["bank_document"]
        config_document = validated["config_document"]
        raw_bank_document = raw_payload.get("bank_document")
        raw_config_document = raw_payload.get("config_document")
        if not isinstance(raw_bank_document, dict) or not isinstance(raw_config_document, dict):
            raise HTTPException(status_code=422, detail="saved CAT assets are invalid")
        try:
            item_bank = ItemBank.from_dict(bank_document)
            item_bank.assert_runtime_ready()
            config = CATConfig.from_dict(config_document)
        except CATValidationError as exc:
            raise HTTPException(status_code=422, detail="saved CAT assets are invalid") from exc

        instrument_version = str(
            item_bank.metadata.get("instrument_version", item_bank.version)
        )
        if (
            request.instrument_id != item_bank.instrument_id
            or request.instrument_version != instrument_version
        ):
            raise HTTPException(status_code=422, detail="saved CAT instrument identity does not match")

        return runtime.start_saved(
            request,
            item_bank,
            config,
            _document_digest(raw_bank_document),
            _document_digest(raw_config_document),
        )

    @app.get("/internal/cat/sessions/{assessment_id}", operation_id="catGetSession")
    async def get_session(assessment_id: str) -> dict[str, Any]:
        return runtime.state(runtime._session(assessment_id))

    @app.post("/internal/cat/sessions/{assessment_id}/responses", operation_id="catSubmitResponse")
    async def submit_response(assessment_id: str, request: ResponseRequest) -> dict[str, Any]:
        return runtime.submit(assessment_id, request)

    @app.post("/internal/cat/sessions/{assessment_id}/complete", operation_id="catCompleteSession")
    async def complete_session(assessment_id: str, request: CompleteRequest) -> dict[str, Any]:
        return runtime.complete(assessment_id, request)

    return app


app = create_app()


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("SMHAI_CAT_PORT", "8180")))


if __name__ == "__main__":
    main()
