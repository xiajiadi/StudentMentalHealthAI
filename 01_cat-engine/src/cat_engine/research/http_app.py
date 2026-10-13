"""Private, stateless HTTP bridge for explicitly bound research CAT sessions.

This module defines an app factory only; importing it does not create or start
an app. It does not authorize students, persist state, configure CORS/cookies,
or expose the ordinary CAT API. Callers must keep this service loopback-only
and keep signed snapshots on Backend-private paths.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from cat_engine.domain.config import CATConfig
from cat_engine.research.research_session import (
    PROFILE_STATUS,
    RESEARCH_PUBLICATION_STATUS,
    ResearchCATProfile,
    ResearchCATQuestion,
    ResearchCATSession,
    ResearchSessionError,
    SnapshotAuthenticator,
    _config_sha256,
    _validate_config,
)

WIRE_SCHEMA = "psynova.research-http.v1"
MAX_REQUEST_BODY_BYTES = 64 * 1024
MAX_JSON_DEPTH = 32
MAX_JSON_NODES = 4096
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PROTECTED_POST_PATHS = frozenset(
    {
        "/v1/sessions/start",
        "/v1/sessions/resume",
        "/v1/sessions/answer",
    }
)

_BindingRef = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=_SAFE_REF.pattern)
]
_SessionRef = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=_SAFE_REF.pattern)
]
_ItemRef = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=_SAFE_REF.pattern)
]


class _WireRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    wire_schema: Literal["psynova.research-http.v1"] = Field(alias="schema")


class _StartRequest(_WireRequest):
    binding_ref: _BindingRef


class _ResumeRequest(_WireRequest):
    binding_ref: _BindingRef
    session_ref: _SessionRef
    signed_snapshot: dict[str, object]


class _AnswerRequest(_ResumeRequest):
    item_id: _ItemRef
    raw_value: StrictInt


@dataclass(frozen=True, slots=True)
class ResearchCATBinding:
    """Trusted immutable profile/config binding injected by the Backend owner."""

    binding_ref: str
    profile: ResearchCATProfile
    config: CATConfig

    def __post_init__(self) -> None:
        if type(self.binding_ref) is not str or not _SAFE_REF.fullmatch(self.binding_ref):
            raise ValueError("research binding reference is invalid")
        if not isinstance(self.profile, ResearchCATProfile):
            raise TypeError("research binding requires a validated profile")
        if not isinstance(self.config, CATConfig):
            raise TypeError("research binding requires a validated CAT config")
        if (
            self.profile.profile_type != PROFILE_STATUS
            or self.profile.research_only is not True
            or self.profile.human_curated is not False
            or self.profile.psychological_interpretation_allowed is not False
            or self.profile.publication_status
            not in {"not_approved", RESEARCH_PUBLICATION_STATUS}
        ):
            raise ValueError("research binding must remain a nonapproved research candidate")
        _validate_config(self.config, len(self.profile.items))

    @property
    def config_sha256(self) -> str:
        return _config_sha256(self.config)


class _BridgeError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code


class _PrivateRequestGuard:
    """Authenticate and bound private JSON bodies before FastAPI reads them."""

    def __init__(self, app: ASGIApp, service_bearer_token: bytes) -> None:
        self.app = app
        self.service_bearer_token = service_bearer_token

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] not in _PROTECTED_POST_PATHS
        ):
            await self.app(scope, receive, send)
            return

        headers = scope.get("headers", [])
        if not _authorized_headers(headers, self.service_bearer_token):
            await _send_wire_error(
                scope, receive, send, 401, "bearer_authentication_required"
            )
            return

        content_lengths = [value for name, value in headers if name == b"content-length"]
        transfer_encodings = [
            value for name, value in headers if name == b"transfer-encoding"
        ]
        if len(content_lengths) > 1 or (content_lengths and transfer_encodings):
            await _send_wire_error(scope, receive, send, 400, "request_invalid")
            return
        expected_length: int | None = None
        if content_lengths:
            try:
                length_text = content_lengths[0].decode("ascii")
                if not length_text.isdecimal():
                    raise ValueError
                expected_length = int(length_text)
            except (UnicodeDecodeError, ValueError):
                await _send_wire_error(scope, receive, send, 400, "request_invalid")
                return
            if expected_length > MAX_REQUEST_BODY_BYTES:
                await _send_wire_error(scope, receive, send, 413, "request_too_large")
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                await _send_wire_error(scope, receive, send, 400, "request_invalid")
                return
            chunk = message.get("body", b"")
            if not isinstance(chunk, bytes):
                await _send_wire_error(scope, receive, send, 400, "request_invalid")
                return
            if len(body) + len(chunk) > MAX_REQUEST_BODY_BYTES:
                await _send_wire_error(scope, receive, send, 413, "request_too_large")
                return
            body.extend(chunk)
            if message.get("more_body") is not True:
                break

        if expected_length is not None and len(body) != expected_length:
            await _send_wire_error(scope, receive, send, 400, "request_invalid")
            return
        if not _bounded_json_document(bytes(body)):
            await _send_wire_error(scope, receive, send, 400, "request_invalid")
            return

        delivered = False

        async def replay_receive() -> dict[str, object]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return { "type": "http.request", "body": bytes(body), "more_body": False }
            return await receive()

        await self.app(scope, replay_receive, send)


def _authorized_headers(headers: list[tuple[bytes, bytes]], token: bytes) -> bool:
    authorization = [value for name, value in headers if name == b"authorization"]
    if len(authorization) != 1 or any(name == b"cookie" for name, _value in headers):
        return False
    scheme, separator, value = authorization[0].partition(b" ")
    return bool(
        separator
        and scheme.lower() == b"bearer"
        and value
        and hmac.compare_digest(value, token)
    )


def _bounded_json_document(raw_body: bytes) -> bool:
    """Reject malformed, deeply nested, or node-heavy JSON before Pydantic."""

    depth = 0
    maximum_depth = 0
    in_string = False
    escaped = False
    for byte in raw_body:
        if in_string:
            if escaped:
                escaped = False
            elif byte == ord("\\"):
                escaped = True
            elif byte == ord('"'):
                in_string = False
            continue
        if byte == ord('"'):
            in_string = True
        elif byte in (ord("{"), ord("[")):
            depth += 1
            maximum_depth = max(maximum_depth, depth)
            if maximum_depth > MAX_JSON_DEPTH:
                return False
        elif byte in (ord("}"), ord("]")):
            depth -= 1
            if depth < 0:
                return False
    if in_string or depth != 0:
        return False

    try:
        document = json.loads(
            raw_body.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        return False

    pending = [document]
    node_count = 0
    while pending:
        value = pending.pop()
        node_count += 1
        if node_count > MAX_JSON_NODES:
            return False
        if isinstance(value, dict):
            node_count += len(value)
            if node_count > MAX_JSON_NODES:
                return False
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return True


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey
        result[key] = value
    return result


class _DuplicateJSONKey(ValueError):
    pass


def _reject_json_constant(_value: str) -> None:
    raise ValueError("nonfinite JSON numbers are not allowed")


async def _send_wire_error(
    scope: Scope, receive: Receive, send: Send, status_code: int, code: str
) -> None:
    response = _error_response(status_code, code)
    await response(scope, receive, send)


def create_research_http_app(
    *,
    bindings: Mapping[str, ResearchCATBinding],
    authenticator: SnapshotAuthenticator,
    service_bearer_token: bytes,
) -> FastAPI:
    """Create a private app from trusted bindings and caller-owned secrets.

    A caller supplies the exact profile/config registry and the application
    authentication material. No profile paths, default keys, environment
    variables, public token endpoint, cookie authentication, or app-global
    configuration are read here.
    """

    if not isinstance(bindings, Mapping) or not bindings:
        raise ValueError("at least one research CAT binding is required")
    fixed_bindings: dict[str, ResearchCATBinding] = {}
    for binding_ref, binding in bindings.items():
        if (
            type(binding_ref) is not str
            or not _SAFE_REF.fullmatch(binding_ref)
            or not isinstance(binding, ResearchCATBinding)
            or binding.binding_ref != binding_ref
        ):
            raise ValueError("research CAT binding registry is invalid")
        fixed_bindings[binding_ref] = binding
    if (
        type(service_bearer_token) is not bytes
        or len(service_bearer_token) < 32
    ):
        raise ValueError("explicit service token and snapshot authenticator are required")
    if not callable(getattr(authenticator, "sign", None)) or not callable(
        getattr(authenticator, "verify", None)
    ):
        raise TypeError("snapshot authenticator must implement sign and verify")

    app = FastAPI(
        title="PsyNova private research CAT bridge",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.research_bindings = MappingProxyType(fixed_bindings)
    app.state.snapshot_authenticator = authenticator
    app.state.service_bearer_token = service_bearer_token
    app.add_middleware(_PrivateRequestGuard, service_bearer_token=service_bearer_token)

    @app.exception_handler(_BridgeError)
    async def bridge_error_handler(_request: Request, exc: _BridgeError) -> JSONResponse:
        return _error_response(exc.status_code, exc.code)

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        # Never serialize Pydantic errors: they can contain submitted answer or
        # signed snapshot values.
        return _error_response(400, "request_invalid")

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        if exc.status_code == 404:
            return _error_response(404, "route_not_found")
        if exc.status_code == 405:
            return _error_response(405, "method_not_allowed")
        return _error_response(400, "request_invalid")

    @app.exception_handler(Exception)
    async def unexpected_error_handler(_request: Request, _exc: Exception) -> JSONResponse:
        # No exception string, traceback, request body, or snapshot enters a log
        # or response here. Deployment-level diagnostic logging must also redact.
        return _error_response(500, "bridge_internal_error")

    def require_service_bearer(request: Request) -> None:
        if request.headers.get("cookie") is not None:
            raise _BridgeError(401, "bearer_authentication_required")
        values = request.headers.getlist("authorization")
        if len(values) != 1:
            raise _BridgeError(401, "bearer_authentication_required")
        scheme, separator, value = values[0].partition(" ")
        try:
            supplied = value.encode("ascii", errors="strict") if separator else b""
        except UnicodeEncodeError:
            supplied = b""
        if (
            scheme.casefold() != "bearer"
            or not separator
            or not value
            or not hmac.compare_digest(supplied, service_bearer_token)
        ):
            raise _BridgeError(401, "bearer_authentication_required")

    def get_binding(binding_ref: str) -> ResearchCATBinding:
        binding = app.state.research_bindings.get(binding_ref)
        if binding is None:
            raise _BridgeError(404, "research_binding_not_found")
        return binding

    def require_session_match(session: ResearchCATSession, session_ref: str) -> None:
        if session.status == "COMPLETED":
            session_id = session.completion().session_id
        else:
            question = session.next_item()
            if question is None:
                raise _BridgeError(400, "snapshot_invalid")
            session_id = question.session_id
        if not hmac.compare_digest(session_id, session_ref):
            raise _BridgeError(400, "session_mismatch")

    def response_payload(
        binding: ResearchCATBinding,
        session_ref: str,
        session: ResearchCATSession,
    ) -> dict[str, object]:
        question = session.next_item() if session.status == "ACTIVE" else None
        completion: dict[str, object] | None = None
        if session.status == "COMPLETED":
            value = session.completion()
            completion = {
                "status": value.status,
                "items_administered": value.items_administered,
                "items_answered": value.items_answered,
                "stop_reason": value.stop_reason,
            }
        return {
            "schema": WIRE_SCHEMA,
            "binding_ref": binding.binding_ref,
            "session_ref": session_ref,
            "profile_id": binding.profile.profile_id,
            "profile_sha256": binding.profile.file_sha256,
            "config_sha256": binding.config_sha256,
            "research_only": True,
            "human_curated": False,
            "publication_status": binding.profile.publication_status,
            "psychological_interpretation_allowed": False,
            "status": session.status,
            "items_answered": session.items_answered,
            "signed_snapshot": session.save_state(app.state.snapshot_authenticator),
            "question": _question_payload(question) if question is not None else None,
            "completion": completion,
        }

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "RESEARCH_ONLY",
            "research_only": True,
            "clinical_approval": False,
            "school_approval": False,
        }

    @app.post("/v1/sessions/start", dependencies=[Depends(require_service_bearer)])
    def start_session(body: _StartRequest) -> dict[str, object]:
        binding = get_binding(body.binding_ref)
        session_ref = f"r_{secrets.token_urlsafe(24)}"
        try:
            session = ResearchCATSession.start(
                binding.profile, binding.config, session_id=session_ref
            )
            return response_payload(binding, session_ref, session)
        except ResearchSessionError as exc:
            raise _BridgeError(400, "session_start_failed") from exc
        except _BridgeError:
            raise
        except Exception as exc:
            raise _BridgeError(500, "bridge_internal_error") from exc

    @app.post("/v1/sessions/resume", dependencies=[Depends(require_service_bearer)])
    def resume_session(body: _ResumeRequest) -> dict[str, object]:
        binding = get_binding(body.binding_ref)
        try:
            session = ResearchCATSession.restore(
                binding.profile,
                binding.config,
                body.signed_snapshot,
                authenticator=app.state.snapshot_authenticator,
            )
            require_session_match(session, body.session_ref)
            return response_payload(binding, body.session_ref, session)
        except _BridgeError:
            raise
        except ResearchSessionError as exc:
            raise _BridgeError(400, "snapshot_invalid") from exc
        except Exception as exc:
            raise _BridgeError(500, "bridge_internal_error") from exc

    @app.post("/v1/sessions/answer", dependencies=[Depends(require_service_bearer)])
    def answer_session(body: _AnswerRequest) -> dict[str, object]:
        binding = get_binding(body.binding_ref)
        try:
            session = ResearchCATSession.restore(
                binding.profile,
                binding.config,
                body.signed_snapshot,
                authenticator=app.state.snapshot_authenticator,
            )
            require_session_match(session, body.session_ref)
            pending = session.next_item()
            if pending is None or pending.item_id != body.item_id:
                raise _BridgeError(400, "answer_invalid")
            session.answer(body.item_id, body.raw_value)
            return response_payload(binding, body.session_ref, session)
        except _BridgeError:
            raise
        except ResearchSessionError as exc:
            raise _BridgeError(400, "answer_invalid") from exc
        except Exception as exc:
            raise _BridgeError(500, "bridge_internal_error") from exc

    return app


def _question_payload(question: ResearchCATQuestion) -> dict[str, object]:
    return {
        "item_id": question.item_id,
        "qid": question.qid,
        "stem": question.stem,
        "step": question.step,
        "response_options": [
            {"value": option.raw_value, "label": option.label}
            for option in question.response_options
        ],
    }


def _error_response(status_code: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"schema": WIRE_SCHEMA, "error": {"code": code}},
    )
