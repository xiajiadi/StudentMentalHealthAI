"""Loopback CAT service for the Round 1 integration path.

The process owns provider sessions and exposes only item presentation,
response recording, and the frozen ``assessment.v1`` projection.  Provider
objects and item parameters never cross this HTTP boundary.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from cat_engine.domain.config import CATConfig
from cat_engine.domain.item import ResponseValue
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


class ResponseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(pattern=r"^ITEM_[A-Za-z0-9][A-Za-z0-9_.-]*$")
    response: str | int | float | bool


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

    def health(self) -> dict[str, Any]:
        return {
            "status": "READY",
            "service": "cat",
            "provider": "adaptivetesting",
            "provider_version": "adaptivetesting-1.2.1",
            "item_bank_id": self.item_bank.item_bank_id,
            "item_bank_version": self.item_bank.version,
            "config_version": self.config.config_version,
            "session_count": len(self.sessions),
            "synthetic_fixture_only": True,
        }

    def start(self, request: StartRequest) -> dict[str, Any]:
        if request.instrument_id != self.item_bank.instrument_id or request.instrument_version != self.item_bank.version:
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
        else:
            if existing.subject_id != request.subject_id:
                raise HTTPException(status_code=409, detail="assessment belongs to another subject")
            session = existing
        if session.selected_item_id is None and session.status.value in {"INITIALIZED", "IN_PROGRESS"}:
            try:
                self.service.next_item(session)
            except Exception as exc:
                raise _domain_error(exc) from exc
        return self.state(session)

    def submit(self, assessment_id: str, request: ResponseRequest) -> dict[str, Any]:
        session = self._session(assessment_id)
        try:
            self.service.submit_response(session, request.response)
            if session.status.value == "IN_PROGRESS" and session.selected_item_id is None:
                if not self._should_stop(session):
                    self.service.next_item(session)
        except Exception as exc:
            raise _domain_error(exc) from exc
        return self.state(session)

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
            selected = self.item_bank.item_by_id(session.selected_item_id)
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
            "max_items": self.config.max_items,
            "item_bank_version": self.item_bank.version,
            "config_version": self.config.config_version,
            "provider_version": "adaptivetesting-1.2.1",
            "synthetic_fixture_only": True,
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
            "operations": ["start", "state", "submit_response", "complete"],
            "provider": "adaptivetesting-1.2.1",
            "synthetic_fixture_only": True,
        }

    @app.post("/internal/cat/sessions", operation_id="catCreateSession")
    async def create_session(request: StartRequest) -> dict[str, Any]:
        return runtime.start(request)

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
