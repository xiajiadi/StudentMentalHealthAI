"""Read-only local Prompt and policy registries for D3-1.

The registry is a reviewed source asset shipped with this module. Callers can
select an exact ID and version, but cannot provide a path, template body, or
``approved`` flag that changes the trusted registry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import PromptRefusal

_ASSET_ROOT = Path(__file__).resolve().parents[2] / "assets"
_TEMPLATE_REGISTRY_PATH = _ASSET_ROOT / "template_registry.v1.json"
_POLICY_REGISTRY_PATH = _ASSET_ROOT / "policy_registry.v1.json"


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PromptRefusal("REGISTRY_ASSET_INVALID") from exc


def _safe_relative_asset(path_text: object) -> Path:
    if not isinstance(path_text, str) or not path_text or Path(path_text).is_absolute():
        raise PromptRefusal("REGISTRY_ASSET_PATH_INVALID")
    path = Path(path_text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise PromptRefusal("REGISTRY_ASSET_PATH_INVALID")
    resolved = (_ASSET_ROOT / path).resolve()
    try:
        resolved.relative_to(_ASSET_ROOT.resolve())
    except ValueError as exc:
        raise PromptRefusal("REGISTRY_ASSET_PATH_INVALID") from exc
    return resolved


def _normalise_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read_template_text(record: Mapping[str, Any]) -> str:
    path = _safe_relative_asset(record.get("template_path"))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PromptRefusal("REGISTRY_ASSET_INVALID") from exc
    text = _normalise_newlines(text)
    expected = record.get("content_hash")
    actual = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not isinstance(expected, str) or expected != actual:
        raise PromptRefusal("REGISTRY_ASSET_HASH_MISMATCH")
    return text


@dataclass(frozen=True)
class TemplateRecord(Mapping[str, Any]):
    """An exact, active template resolved from the local registry."""

    prompt_id: str
    prompt_version: str
    role: str
    purpose: str
    language: str
    status: str
    approval_status: str
    engineering_activation_scope: str
    change_summary: str
    content_hash: str
    template_text: str
    allowed_placeholders: tuple[str, ...]

    @property
    def template_content(self) -> str:
        return self.template_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_id": self.prompt_id,
            "prompt_version": self.prompt_version,
            "role": self.role,
            "purpose": self.purpose,
            "language": self.language,
            "status": self.status,
            "approval_status": self.approval_status,
            "engineering_activation_scope": self.engineering_activation_scope,
            "change_summary": self.change_summary,
            "content_hash": self.content_hash,
            "template_text": self.template_text,
            "allowed_placeholders": list(self.allowed_placeholders),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True)
class PolicyRecord(Mapping[str, Any]):
    """An exact policy entry resolved from the local registry."""

    data: Mapping[str, Any]

    @property
    def policy_id(self) -> str:
        return str(self.data["policy_id"])

    @property
    def policy_version(self) -> str:
        return str(self.data["policy_version"])

    def to_dict(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data, ensure_ascii=False))

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.data)

    def __len__(self) -> int:
        return len(self.data)


def _records(path: Path, key: str) -> list[Mapping[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or not isinstance(payload.get(key), list):
        raise PromptRefusal("REGISTRY_ASSET_INVALID")
    return [record for record in payload[key] if isinstance(record, dict)]


def resolve_template(prompt_id: object, prompt_version: object, role: object) -> TemplateRecord:
    """Resolve one exact active template; never choose ``latest`` or a path."""

    if not all(isinstance(value, str) and value for value in (prompt_id, prompt_version, role)):
        raise PromptRefusal("TEMPLATE_REF_INVALID")
    matching = [
        record
        for record in _records(_TEMPLATE_REGISTRY_PATH, "templates")
        if record.get("prompt_id") == prompt_id and record.get("prompt_version") == prompt_version
    ]
    if not matching:
        raise PromptRefusal("TEMPLATE_NOT_FOUND")
    record = matching[0]
    if record.get("role") != role:
        raise PromptRefusal("TEMPLATE_ROLE_MISMATCH")
    if record.get("status") != "active":
        raise PromptRefusal("TEMPLATE_NOT_ACTIVE")
    if record.get("approval_status") != "ENGINEERING_REVIEWED_SYNTHETIC_ONLY":
        raise PromptRefusal("TEMPLATE_NOT_APPROVED")
    required = record.get("required_placeholders")
    allowed = record.get("allowed_placeholders")
    if not isinstance(required, list) or not isinstance(allowed, list) or not all(
        isinstance(item, str) for item in (*required, *allowed)
    ):
        raise PromptRefusal("REGISTRY_ASSET_INVALID")
    template_text = _read_template_text(record)
    return TemplateRecord(
        prompt_id=str(record["prompt_id"]),
        prompt_version=str(record["prompt_version"]),
        role=str(record["role"]),
        purpose=str(record["purpose"]),
        language=str(record["language"]),
        status=str(record["status"]),
        approval_status=str(record["approval_status"]),
        engineering_activation_scope=str(record["engineering_activation_scope"]),
        change_summary=str(record["change_summary"]),
        content_hash=str(record["content_hash"]),
        template_text=template_text,
        allowed_placeholders=tuple(allowed),
    )


def resolve_policy(policy_id: object, policy_version: object) -> PolicyRecord:
    """Resolve an exact policy version from the reviewed local registry."""

    if not all(isinstance(value, str) and value for value in (policy_id, policy_version)):
        raise PromptRefusal("POLICY_REF_INVALID")
    matching = [
        record
        for record in _records(_POLICY_REGISTRY_PATH, "policies")
        if record.get("policy_id") == policy_id and record.get("policy_version") == policy_version
    ]
    if not matching:
        raise PromptRefusal("POLICY_NOT_FOUND")
    record = matching[0]
    if record.get("status") != "active":
        raise PromptRefusal("POLICY_NOT_ACTIVE")
    return PolicyRecord(record)


def resolve_policy_ref(policy_ref: object) -> PolicyRecord:
    if not isinstance(policy_ref, Mapping):
        raise PromptRefusal("POLICY_REF_INVALID")
    allowed = {"policy_id", "policy_version", "mapping_id", "mapping_version"}
    if set(policy_ref) - allowed or not {"policy_id", "policy_version"}.issubset(policy_ref):
        raise PromptRefusal("POLICY_REF_INVALID")
    policy = resolve_policy(policy_ref["policy_id"], policy_ref["policy_version"])
    mapping = policy.get("mapping")
    if not isinstance(mapping, Mapping):
        raise PromptRefusal("POLICY_MAPPING_INVALID")
    for key in ("mapping_id", "mapping_version"):
        if key in policy_ref and policy_ref[key] != mapping.get(key):
            raise PromptRefusal("POLICY_MAPPING_MISMATCH")
    return policy
