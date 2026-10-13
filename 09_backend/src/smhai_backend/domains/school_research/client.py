"""Strict private Backend client for the research CAT HTTP v1 bridge.

This client handles transport and metadata-only projections. Signed snapshots
remain Backend-private opaque state; the client does not expose CAT estimates,
scores, or an ``assessment.v1`` conversion.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

WIRE_SCHEMA = "psynova.research-http.v1"
SNAPSHOT_SCHEMA = "psynova.research-cat-snapshot.v1"
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SIGNATURE = re.compile(r"(?:[0-9a-f]{64}|rk1\.[A-Za-z0-9_-]{1,64}\.[0-9a-f]{64})\Z")
_TOKEN = re.compile(r"[\x21-\x7e]{32,512}\Z")
_PUBLICATION_STATUSES = frozenset(
    {"not_approved", "not_approved_for_publication_or_operational_use"}
)
_STOP_REASONS = frozenset(
    {
        "se_threshold_reached",
        "max_items_reached",
        "item_bank_exhausted",
        "item_bank_exhausted_before_minimum",
    }
)
_MAX_RESPONSE_BYTES = 1_048_576

_RESPONSE_FIELDS = frozenset(
    {
        "schema",
        "binding_ref",
        "session_ref",
        "profile_id",
        "profile_sha256",
        "config_sha256",
        "research_only",
        "human_curated",
        "publication_status",
        "psychological_interpretation_allowed",
        "status",
        "items_answered",
        "signed_snapshot",
        "question",
        "completion",
    }
)
_SNAPSHOT_FIELDS = frozenset({"payload", "payload_sha256", "signature"})
_SNAPSHOT_PAYLOAD_FIELDS = frozenset(
    {
        "schema",
        "session_id",
        "profile_id",
        "profile_sha256",
        "config_version",
        "config_sha256",
        "step",
        "status",
        "stop_reason",
        "pending_item_id",
        "answers",
    }
)


class ResearchCATClientError(Exception):
    """Stable client failure with no response body, URL, token, or raw exception."""

    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class ResearchCATResponseOption:
    value: int
    label: str | None = field(repr=False)


@dataclass(frozen=True, slots=True)
class ResearchCATQuestion:
    item_id: str
    qid: str
    stem: str = field(repr=False)
    step: int
    response_options: tuple[ResearchCATResponseOption, ...]


@dataclass(frozen=True, slots=True)
class ResearchCATCompletion:
    status: str
    items_administered: int
    items_answered: int
    stop_reason: str


@dataclass(frozen=True, slots=True)
class _SignedResearchSnapshot:
    """Opaque signed CAT state; raw answers stay out of repr and public DTOs."""

    binding_ref: str
    session_ref: str
    profile_sha256: str
    config_sha256: str
    status: str
    items_answered: int
    document_json: bytes = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class ResearchCATSessionState:
    """Strict metadata projection plus a private snapshot for trusted callers."""

    binding_ref: str = field(repr=False)
    session_ref: str = field(repr=False)
    profile_id: str = field(repr=False)
    profile_sha256: str
    config_sha256: str
    research_only: bool
    human_curated: bool
    publication_status: str
    psychological_interpretation_allowed: bool
    status: str
    items_answered: int
    question: ResearchCATQuestion | None
    completion: ResearchCATCompletion | None
    _snapshot: _SignedResearchSnapshot = field(repr=False, compare=False)


class ResearchCATHttpClient:
    """One-attempt loopback HTTP client with caller-pinned CAT identity."""

    def __init__(
        self,
        *,
        base_url: str,
        service_bearer_token: bytes,
        binding_ref: str,
        expected_profile_sha256: str,
        expected_config_sha256: str,
        timeout: float = 5.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = _validate_loopback_url(base_url)
        self._token = _validate_token(service_bearer_token)
        self._binding_ref = _validate_ref(binding_ref, "binding_ref_invalid")
        self._profile_sha256 = _validate_digest(
            expected_profile_sha256, "profile_hash_invalid"
        )
        self._config_sha256 = _validate_digest(
            expected_config_sha256, "config_hash_invalid"
        )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ResearchCATClientError("timeout_invalid")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ResearchCATClientError("timeout_invalid")
        if transport is not None and not isinstance(transport, httpx.AsyncBaseTransport):
            raise ResearchCATClientError("transport_invalid")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(float(timeout)),
            transport=transport,
            trust_env=False,
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token.decode('ascii')}",
            },
        )

    async def start(self) -> ResearchCATSessionState:
        value = await self._post(
            "/v1/sessions/start",
            {"schema": WIRE_SCHEMA, "binding_ref": self._binding_ref},
        )
        state = self._parse_state(value)
        if state.status != "ACTIVE" or state.items_answered != 0:
            raise ResearchCATClientError("response_operation_invalid")
        return state

    async def resume(self, state: ResearchCATSessionState) -> ResearchCATSessionState:
        snapshot = self._snapshot_for_state(state)
        value = await self._post(
            "/v1/sessions/resume",
            {
                "schema": WIRE_SCHEMA,
                "binding_ref": self._binding_ref,
                "session_ref": state.session_ref,
                "signed_snapshot": _decode_snapshot(snapshot.document_json),
            },
        )
        resumed = self._parse_state(value)
        if (
            resumed.session_ref != state.session_ref
            or resumed.profile_id != state.profile_id
            or resumed.status != state.status
            or resumed.items_answered != state.items_answered
            or resumed.publication_status != state.publication_status
            or resumed.question != state.question
            or resumed.completion != state.completion
        ):
            raise ResearchCATClientError("response_operation_invalid")
        return resumed

    async def answer(
        self, state: ResearchCATSessionState, *, item_id: str, raw_value: int
    ) -> ResearchCATSessionState:
        snapshot = self._snapshot_for_state(state)
        if (
            state.status != "ACTIVE"
            or state.question is None
            or type(item_id) is not str
            or item_id != state.question.item_id
            or type(raw_value) is not int
            or raw_value not in {option.value for option in state.question.response_options}
        ):
            raise ResearchCATClientError("answer_invalid")
        value = await self._post(
            "/v1/sessions/answer",
            {
                "schema": WIRE_SCHEMA,
                "binding_ref": self._binding_ref,
                "session_ref": state.session_ref,
                "signed_snapshot": _decode_snapshot(snapshot.document_json),
                "item_id": item_id,
                "raw_value": raw_value,
            },
        )
        advanced = self._parse_state(value)
        if (
            advanced.session_ref != state.session_ref
            or advanced.profile_id != state.profile_id
            or advanced.items_answered != state.items_answered + 1
            or advanced.publication_status != state.publication_status
        ):
            raise ResearchCATClientError("response_operation_invalid")
        return advanced

    async def aclose(self) -> None:
        await self._client.aclose()

    def _snapshot_for_state(self, state: ResearchCATSessionState) -> _SignedResearchSnapshot:
        if type(state) is not ResearchCATSessionState:
            raise ResearchCATClientError("session_state_invalid")
        snapshot = state._snapshot
        if (
            type(snapshot) is not _SignedResearchSnapshot
            or state.binding_ref != self._binding_ref
            or state.profile_sha256 != self._profile_sha256
            or state.config_sha256 != self._config_sha256
            or snapshot.binding_ref != self._binding_ref
            or snapshot.session_ref != state.session_ref
            or snapshot.profile_sha256 != self._profile_sha256
            or snapshot.config_sha256 != self._config_sha256
            or snapshot.status != state.status
            or snapshot.items_answered != state.items_answered
        ):
            raise ResearchCATClientError("session_state_invalid")
        return snapshot

    async def _post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        try:
            async with self._client.stream("POST", path, json=payload) as response:
                if response.status_code != 200:
                    raise ResearchCATClientError(
                        "upstream_rejected", status_code=response.status_code
                    )
                media_type = response.headers.get("content-type", "").split(";", 1)[0]
                if media_type.strip().lower() != "application/json":
                    raise ResearchCATClientError("response_invalid")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                        raise ResearchCATClientError("response_invalid")
                    content.extend(chunk)
        except httpx.TimeoutException:
            raise ResearchCATClientError("dependency_timeout") from None
        except httpx.HTTPError:
            raise ResearchCATClientError("dependency_unavailable") from None
        try:
            value = json.loads(
                bytes(content).decode("utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=_reject_nonfinite,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise ResearchCATClientError("response_invalid") from None
        if type(value) is not dict:
            raise ResearchCATClientError("response_invalid")
        return value

    def _parse_state(self, value: dict[str, Any]) -> ResearchCATSessionState:
        if type(value) is not dict or set(value) != _RESPONSE_FIELDS:
            raise ResearchCATClientError("response_schema_invalid")
        if (
            value.get("schema") != WIRE_SCHEMA
            or value.get("binding_ref") != self._binding_ref
            or type(value.get("session_ref")) is not str
            or _REF.fullmatch(value["session_ref"]) is None
            or type(value.get("profile_id")) is not str
            or _REF.fullmatch(value["profile_id"]) is None
            or value.get("profile_sha256") != self._profile_sha256
            or value.get("config_sha256") != self._config_sha256
            or type(value.get("research_only")) is not bool
            or value["research_only"] is not True
            or type(value.get("human_curated")) is not bool
            or value["human_curated"] is not False
            or type(value.get("publication_status")) is not str
            or value["publication_status"] not in _PUBLICATION_STATUSES
            or type(value.get("psychological_interpretation_allowed")) is not bool
            or value["psychological_interpretation_allowed"] is not False
            or type(value.get("status")) is not str
            or value["status"] not in {"ACTIVE", "COMPLETED"}
            or not _is_nonnegative_int(value.get("items_answered"))
        ):
            raise ResearchCATClientError("response_binding_invalid")
        question = _parse_question(value.get("question"))
        completion = _parse_completion(value.get("completion"))
        snapshot = _parse_snapshot(
            value.get("signed_snapshot"),
            binding_ref=self._binding_ref,
            session_ref=value["session_ref"],
            profile_id=value["profile_id"],
            profile_sha256=self._profile_sha256,
            config_sha256=self._config_sha256,
            status=value["status"],
            items_answered=value["items_answered"],
            expected_pending_item_id=(question.item_id if question is not None else None),
            expected_stop_reason=(completion.stop_reason if completion is not None else None),
        )
        if value["status"] == "ACTIVE":
            if (
                question is None
                or completion is not None
                or question.step != value["items_answered"]
            ):
                raise ResearchCATClientError("response_state_invalid")
        elif (
            question is not None
            or completion is None
            or completion.status != "COMPLETED"
            or completion.items_answered != value["items_answered"]
            or completion.items_administered != value["items_answered"]
        ):
            raise ResearchCATClientError("response_state_invalid")
        return ResearchCATSessionState(
            binding_ref=self._binding_ref,
            session_ref=value["session_ref"],
            profile_id=value["profile_id"],
            profile_sha256=self._profile_sha256,
            config_sha256=self._config_sha256,
            research_only=True,
            human_curated=False,
            publication_status=value["publication_status"],
            psychological_interpretation_allowed=False,
            status=value["status"],
            items_answered=value["items_answered"],
            question=question,
            completion=completion,
            _snapshot=snapshot,
        )


def _validate_loopback_url(value: object) -> str:
    if type(value) is not str or not value or len(value) > 512:
        raise ResearchCATClientError("base_url_invalid")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        address = ipaddress.ip_address(host) if host is not None else None
    except (ValueError, UnicodeError):
        raise ResearchCATClientError("base_url_invalid") from None
    expected_host = (
        f"[{address.compressed}]" if address is not None and address.version == 6
        else address.compressed if address is not None
        else ""
    )
    expected_netloc = (
        f"{expected_host}:{port}" if port is not None else expected_host
    )
    if (
        parsed.scheme != "http"
        or not parsed.netloc
        or "?" in value
        or "#" in value
        or parsed.netloc.casefold() != expected_netloc.casefold()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or address is None
        or not address.is_loopback
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ResearchCATClientError("base_url_must_be_loopback_http")
    return f"http://{parsed.netloc.rstrip('/')}"


def _validate_token(value: object) -> bytes:
    if type(value) is not bytes:
        raise ResearchCATClientError("service_token_invalid")
    try:
        decoded = value.decode("ascii")
    except UnicodeDecodeError:
        raise ResearchCATClientError("service_token_invalid") from None
    if _TOKEN.fullmatch(decoded) is None:
        raise ResearchCATClientError("service_token_invalid")
    return value


def _validate_ref(value: object, code: str) -> str:
    if type(value) is not str or _REF.fullmatch(value) is None:
        raise ResearchCATClientError(code)
    return value


def _validate_digest(value: object, code: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise ResearchCATClientError(code)
    return value


def _parse_question(value: object) -> ResearchCATQuestion | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != {
        "item_id", "qid", "stem", "step", "response_options"
    }:
        raise ResearchCATClientError("response_question_invalid")
    item_id = _validate_ref(value.get("item_id"), "response_question_invalid")
    qid = _validate_ref(value.get("qid"), "response_question_invalid")
    stem = value.get("stem")
    step = value.get("step")
    options = value.get("response_options")
    if (
        type(stem) is not str
        or not stem.strip()
        or len(stem) > 20_000
        or not _is_nonnegative_int(step)
        or type(options) is not list
        or not options
        or len(options) > 20
    ):
        raise ResearchCATClientError("response_question_invalid")
    parsed_options = []
    values = set()
    for option in options:
        if type(option) is not dict or set(option) != {"value", "label"}:
            raise ResearchCATClientError("response_question_invalid")
        raw_value = option.get("value")
        label = option.get("label")
        if (
            type(raw_value) is not int
            or (label is not None and (type(label) is not str or len(label) > 1000))
            or raw_value in values
        ):
            raise ResearchCATClientError("response_question_invalid")
        values.add(raw_value)
        parsed_options.append(ResearchCATResponseOption(value=raw_value, label=label))
    return ResearchCATQuestion(
        item_id=item_id,
        qid=qid,
        stem=stem,
        step=step,
        response_options=tuple(parsed_options),
    )


def _parse_completion(value: object) -> ResearchCATCompletion | None:
    if value is None:
        return None
    if type(value) is not dict or set(value) != {
        "status", "items_administered", "items_answered", "stop_reason"
    }:
        raise ResearchCATClientError("response_completion_invalid")
    status = value.get("status")
    administered = value.get("items_administered")
    answered = value.get("items_answered")
    reason = value.get("stop_reason")
    if (
        status != "COMPLETED"
        or not _is_nonnegative_int(administered)
        or not _is_nonnegative_int(answered)
        or type(reason) is not str
        or reason not in _STOP_REASONS
    ):
        raise ResearchCATClientError("response_completion_invalid")
    return ResearchCATCompletion(status, administered, answered, reason)


def _parse_snapshot(
    value: object,
    *,
    binding_ref: str,
    session_ref: str,
    profile_id: str,
    profile_sha256: str,
    config_sha256: str,
    status: str,
    items_answered: int,
    expected_pending_item_id: str | None,
    expected_stop_reason: str | None,
) -> _SignedResearchSnapshot:
    if type(value) is not dict or set(value) != _SNAPSHOT_FIELDS:
        raise ResearchCATClientError("response_snapshot_invalid")
    if (
        type(value.get("payload_sha256")) is not str
        or _SHA256.fullmatch(value["payload_sha256"]) is None
        or type(value.get("signature")) is not str
        or _SIGNATURE.fullmatch(value["signature"]) is None
    ):
        raise ResearchCATClientError("response_snapshot_invalid")
    payload = value.get("payload")
    if type(payload) is not dict or set(payload) != _SNAPSHOT_PAYLOAD_FIELDS:
        raise ResearchCATClientError("response_snapshot_invalid")
    answers = payload.get("answers")
    stop_reason = payload.get("stop_reason")
    pending_item_id = payload.get("pending_item_id")
    if type(answers) is not list or len(answers) != items_answered:
        raise ResearchCATClientError("response_snapshot_invalid")
    answer_ids: list[str] = []
    for answer in answers:
        if (
            type(answer) is not dict
            or set(answer) != {"item_id", "raw_value"}
            or type(answer.get("item_id")) is not str
            or _REF.fullmatch(answer["item_id"]) is None
            or type(answer.get("raw_value")) is not int
        ):
            raise ResearchCATClientError("response_snapshot_invalid")
        answer_ids.append(answer["item_id"])
    if (
        payload.get("schema") != SNAPSHOT_SCHEMA
        or payload.get("session_id") != session_ref
        or payload.get("profile_id") != profile_id
        or payload.get("profile_sha256") != profile_sha256
        or payload.get("config_sha256") != config_sha256
        or type(payload.get("config_version")) is not str
        or not payload["config_version"].strip()
        or payload.get("step") != items_answered
        or type(payload.get("step")) is not int
        or payload.get("status") != status
        or len(set(answer_ids)) != len(answer_ids)
    ):
        raise ResearchCATClientError("response_snapshot_invalid")
    if status == "ACTIVE":
        if (
            stop_reason is not None
            or type(pending_item_id) is not str
            or _REF.fullmatch(pending_item_id) is None
            or pending_item_id != expected_pending_item_id
        ):
            raise ResearchCATClientError("response_snapshot_invalid")
    elif (
        type(stop_reason) is not str
        or stop_reason not in _STOP_REASONS
        or pending_item_id is not None
        or stop_reason != expected_stop_reason
    ):
        raise ResearchCATClientError("response_snapshot_invalid")
    try:
        payload_bytes = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ResearchCATClientError("response_snapshot_invalid") from None
    if not hmac.compare_digest(
        hashlib.sha256(payload_bytes).hexdigest(), value["payload_sha256"]
    ):
        raise ResearchCATClientError("response_snapshot_invalid")
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise ResearchCATClientError("response_snapshot_invalid") from None
    return _SignedResearchSnapshot(
        binding_ref=binding_ref,
        session_ref=session_ref,
        profile_sha256=profile_sha256,
        config_sha256=config_sha256,
        status=status,
        items_answered=items_answered,
        document_json=encoded,
    )


def _decode_snapshot(value: bytes) -> dict[str, object]:
    try:
        decoded = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ResearchCATClientError("session_state_invalid") from None
    if type(decoded) is not dict:
        raise ResearchCATClientError("session_state_invalid")
    return decoded


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> Any:
    raise ValueError("non-finite JSON number")
