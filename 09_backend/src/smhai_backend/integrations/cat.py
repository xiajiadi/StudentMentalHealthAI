"""CAT integration port and explicit contract-faithful fallback."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from smhai_backend.core.errors import ErrorCode, error
from smhai_backend.core.request_context import RequestContext
from smhai_backend.integrations.contracts import validate_frozen

from .common_http import LongLivedHttpClient, UpstreamError, translate_upstream_error


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class CatStart:
    assessment_id: str
    subject_id: str
    instrument_id: str
    instrument_version: str
    started_at: str
    session_id: str | None = None
    current_item: dict[str, Any] | None = None
    current_index: int = 0
    answered_count: int = 0
    administered_count: int = 0
    can_complete: bool = False
    max_items: int | None = None
    item_bank_version: str | None = None
    config_version: str | None = None
    provider_version: str | None = None
    cat_binding_mode: str = field(default="FIXTURE", repr=False)
    saved_binding: dict[str, str] | None = field(default=None, repr=False)


class CatClient(Protocol):
    label: str

    async def start(
        self,
        *,
        assessment_id: str,
        subject_id: str,
        instrument_id: str,
        instrument_version: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart: ...

    async def start_saved_session(
        self,
        *,
        assessment_id: str,
        subject_id: str,
        instrument_id: str,
        instrument_version: str,
        binding: Mapping[str, str],
        bank_document: Mapping[str, Any],
        config_document: Mapping[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart: ...

    async def submit_response(
        self,
        session: CatStart,
        *,
        item_id: str,
        response: Any,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]: ...

    async def complete(
        self,
        session: CatStart,
        *,
        responses: Mapping[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
        manual: bool = False,
    ) -> dict[str, Any]: ...

    async def state(
        self,
        session: CatStart,
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart: ...

    async def health(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class ContractFakeCatClient:
    label: str = "CONTRACT_FAKE"
    call_count: int = 0
    _sessions: dict[str, CatStart] = field(default_factory=dict)

    async def start(
        self,
        *,
        assessment_id: str,
        subject_id: str,
        instrument_id: str,
        instrument_version: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart:
        session = CatStart(
            assessment_id=assessment_id,
            subject_id=subject_id,
            instrument_id=instrument_id,
            instrument_version=instrument_version,
            started_at=_timestamp(),
            cat_binding_mode="FIXTURE",
            saved_binding=None,
        )
        self._sessions[assessment_id] = session
        self.call_count += 1
        return session

    async def submit_response(
        self,
        session: CatStart,
        *,
        item_id: str,
        response: Any,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        if session.assessment_id not in self._sessions:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        self.call_count += 1
        return {"assessment_id": session.assessment_id, "status": "in_progress"}

    async def complete(
        self,
        session: CatStart,
        *,
        responses: Mapping[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
        manual: bool = False,
    ) -> dict[str, Any]:
        if session.assessment_id not in self._sessions:
            raise error(ErrorCode.RESOURCE_NOT_FOUND, detail="assessment not found")
        completed_at = _timestamp()
        dimensions = {
            "wellbeing": {
                "theta": None,
                "se": None,
                "score": None,
                "band": "unknown",
                "interpretation_status": "insufficient_data",
                "items_answered": len(responses),
            }
        }
        assessment = {
            "schema_version": "assessment.v1",
            "assessment_id": session.assessment_id,
            "subject_id": session.subject_id,
            "instrument": {
                "instrument_id": session.instrument_id,
                "version": session.instrument_version,
            },
            "population_scope": "synthetic_demo",
            "status": "completed",
            "dimensions": dimensions,
            "risk": {
                "level": "normal",
                "need_human_review": False,
                "reason_codes": ["SYNTHETIC_FIXTURE"],
                "ruleset_id": "RULESET_backend_contract_fake",
            },
            "response_summary": {
                "items_answered": len(responses),
                "duration_seconds": None,
            },
            "provenance": {
                "source_adapter": "backend-contract-fake-cat",
                "adapter_version": "1.0",
                "cat_engine_version": "CONTRACT_FAKE",
                "item_bank_version": "ITEMBANK_synthetic_v1",
            },
            "timestamps": {
                "started_at": session.started_at,
                "completed_at": completed_at,
            },
        }
        validate_frozen("assessment.v1.schema.json", assessment)
        self.call_count += 1
        return assessment

    async def state(
        self,
        session: CatStart,
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart:
        return self._sessions.get(session.assessment_id, session)

    async def health(self) -> dict[str, Any]:
        return {"status": "READY", "mode": self.label}


class HttpCatClient(LongLivedHttpClient):
    """Thin Backend transport for the real CAT service."""

    label = "REAL_HTTP"

    async def start(
        self,
        *,
        assessment_id: str,
        subject_id: str,
        instrument_id: str,
        instrument_version: str,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart:
        context = _context(request_id, trace_id, "cat_start")
        try:
            value = await self.post_json(
                "/internal/cat/sessions",
                {
                    "assessment_id": assessment_id,
                    "subject_id": subject_id,
                    "instrument_id": instrument_id,
                    "instrument_version": instrument_version,
                },
                context=context,
            )
            return _state_to_start(
                value,
                assessment_id=assessment_id,
                subject_id=subject_id,
                instrument_id=instrument_id,
                instrument_version=instrument_version,
                expected_binding_mode="FIXTURE",
                expected_saved_binding=None,
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except (TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="CAT returned an invalid session projection",
            ) from exc

    async def start_saved_session(
        self,
        *,
        assessment_id: str,
        subject_id: str,
        instrument_id: str,
        instrument_version: str,
        binding: Mapping[str, str],
        bank_document: Mapping[str, Any],
        config_document: Mapping[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart:
        expected_keys = {
            "binding_ref", "activation_ref", "plan_version_ref", "bank_version_ref"
        }
        bank_metadata = (
            bank_document.get("metadata")
            if isinstance(bank_document, Mapping)
            else None
        )
        if isinstance(bank_metadata, Mapping):
            saved_instrument_version = bank_metadata.get(
                "instrument_version", bank_document.get("version")
            )
        elif isinstance(bank_document, Mapping):
            saved_instrument_version = bank_document.get("version")
        else:
            saved_instrument_version = None
        if (
            not isinstance(binding, Mapping)
            or set(binding) != expected_keys
            or not isinstance(bank_document, Mapping)
            or not isinstance(config_document, Mapping)
            or bank_document.get("instrument_id") != instrument_id
            or saved_instrument_version != instrument_version
            or not isinstance(config_document.get("config_version"), str)
        ):
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                detail="saved CAT binding is invalid",
            )
        saved_binding = dict(binding)
        context = _context(request_id, trace_id, "cat_saved_session_start")
        try:
            value = await self.post_json(
                "/internal/cat/saved-sessions",
                {
                    "assessment_id": assessment_id,
                    "subject_id": subject_id,
                    "instrument_id": instrument_id,
                    "instrument_version": instrument_version,
                    **saved_binding,
                    "bank_document": dict(bank_document),
                    "config_document": dict(config_document),
                },
                context=context,
            )
            return _state_to_start(
                value,
                assessment_id=assessment_id,
                subject_id=subject_id,
                instrument_id=instrument_id,
                instrument_version=instrument_version,
                expected_binding_mode="SAVED_VERSION",
                expected_saved_binding=saved_binding,
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except (TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="CAT returned an invalid saved-session projection",
            ) from exc

    async def submit_response(
        self,
        session: CatStart,
        *,
        item_id: str,
        response: Any,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        context = _context(request_id, trace_id, "cat_response")
        try:
            return await self.post_json(
                f"/internal/cat/sessions/{session.assessment_id}/responses",
                {"item_id": item_id, "response": response},
                context=context,
            )
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc

    async def complete(
        self,
        session: CatStart,
        *,
        responses: Mapping[str, Any],
        request_id: str | None = None,
        trace_id: str | None = None,
        manual: bool = False,
    ) -> dict[str, Any]:
        context = _context(request_id, trace_id, "cat_complete")
        try:
            value = await self.post_json(
                f"/internal/cat/sessions/{session.assessment_id}/complete",
                {"manual": manual},
                context=context,
            )
            assessment = value.get("assessment")
            if not isinstance(assessment, dict):
                raise ValueError("CAT response has no assessment")
            validate_frozen("assessment.v1.schema.json", assessment)
            if (
                assessment.get("assessment_id") != session.assessment_id
                or assessment.get("subject_id") != session.subject_id
            ):
                raise ValueError("CAT assessment identity does not match the session")
            return assessment
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc
        except ValueError as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="CAT returned an invalid assessment projection",
            ) from exc

    async def state(
        self,
        session: CatStart,
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> CatStart:
        context = _context(request_id, trace_id, "cat_state")
        try:
            value = await self.get_json(
                f"/internal/cat/sessions/{session.assessment_id}", context=context
            )
            return _state_to_start(
                value,
                assessment_id=session.assessment_id,
                subject_id=session.subject_id,
                instrument_id=session.instrument_id,
                instrument_version=session.instrument_version,
                expected_binding_mode=session.cat_binding_mode,
                expected_saved_binding=session.saved_binding,
            )
        except UpstreamError as exc:
            if exc.status_code == 404:
                raise error(
                    ErrorCode.RESOURCE_NOT_FOUND,
                    status_code=404,
                    detail="CAT session not found",
                ) from exc
            raise translate_upstream_error(exc) from exc
        except (TypeError, ValueError) as exc:
            raise error(
                ErrorCode.DEPENDENCY_INVALID_RESPONSE,
                status_code=502,
                detail="CAT returned an invalid state projection",
            ) from exc

    async def health(self) -> dict[str, Any]:
        try:
            return await self.get_json("/health/ready", context=_context(None, None, "cat_health"))
        except UpstreamError as exc:
            raise translate_upstream_error(exc) from exc


def _context(request_id: str | None, trace_id: str | None, suffix: str) -> RequestContext:
    return RequestContext(
        request_id=request_id or f"REQ_{suffix}",
        trace_id=trace_id or f"TRACE_{suffix}",
    )


def _state_to_start(
    value: Mapping[str, Any],
    *,
    assessment_id: str,
    subject_id: str,
    instrument_id: str,
    instrument_version: str,
    expected_binding_mode: str,
    expected_saved_binding: Mapping[str, str] | None,
) -> CatStart:
    if (
        value.get("assessment_id") != assessment_id
        or value.get("subject_id") != subject_id
        or value.get("cat_binding_mode") != expected_binding_mode
        or value.get("saved_binding")
        != (dict(expected_saved_binding) if expected_saved_binding is not None else None)
    ):
        raise ValueError("CAT session identity does not match the request")
    return CatStart(
        assessment_id=assessment_id,
        subject_id=subject_id,
        instrument_id=instrument_id,
        instrument_version=instrument_version,
        started_at=str(value.get("started_at") or _timestamp()),
        session_id=str(value.get("session_id") or value["assessment_id"]),
        current_item=dict(value["current_item"])
        if isinstance(value.get("current_item"), Mapping)
        else None,
        current_index=int(value.get("current_index", value.get("administered_count", 0))),
        answered_count=int(value.get("answered_count", 0)),
        administered_count=int(value.get("administered_count", 0)),
        can_complete=bool(value.get("can_complete", False)),
        max_items=int(value["max_items"]) if value.get("max_items") is not None else None,
        item_bank_version=str(value["item_bank_version"])
        if value.get("item_bank_version")
        else None,
        config_version=str(value["config_version"]) if value.get("config_version") else None,
        provider_version=str(value["provider_version"]) if value.get("provider_version") else None,
        cat_binding_mode=expected_binding_mode,
        saved_binding=dict(expected_saved_binding) if expected_saved_binding is not None else None,
    )
