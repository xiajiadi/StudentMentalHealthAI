"""Provider-neutral runtime domain models.

The frozen ``generation.v1`` contract remains an input/output boundary. These
objects add runtime-only fields such as the prompt body, timeout and provider
mapping without changing that contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping


class ModelStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    NOT_INSTALLED = "NOT_INSTALLED"
    DOWNLOADING = "DOWNLOADING"
    READY = "READY"
    LOADING = "LOADING"
    LOADED = "LOADED"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    UNAVAILABLE = "UNAVAILABLE"


class HardwareProfile(str, Enum):
    CPU_ONLY = "CPU_ONLY"
    CONSUMER_GPU = "CONSUMER_GPU"
    SERVER_GPU = "SERVER_GPU"
    UNKNOWN = "UNKNOWN"


class Compatibility(str, Enum):
    SUPPORTED = "SUPPORTED"
    DEGRADED = "DEGRADED"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"


class StreamEventType(str, Enum):
    START = "START"
    DELTA = "DELTA"
    USAGE = "USAGE"
    DONE = "DONE"
    ERROR = "ERROR"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class Capabilities:
    chat: bool = True
    stream: bool = False
    structured_output: bool = False
    json_schema: bool = False
    tools: bool = False
    vision: bool = False
    reasoning: bool = False
    embeddings: bool = False

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | None) -> "Capabilities":
        value = value or {}
        fields = {name: bool(value.get(name, False)) for name in cls.__dataclass_fields__}
        return cls(**fields)

    def to_dict(self) -> dict[str, bool]:
        return {name: bool(getattr(self, name)) for name in self.__dataclass_fields__}


@dataclass
class ModelEntry:
    logical_model_id: str
    contract_model_id: str
    display_name: str
    family: str
    parameters: str | int | float | None
    provider: str
    provider_model_id: str
    source: str | None = None
    source_repository: str | None = None
    revision: str | None = None
    digest: str | None = None
    format: str | None = None
    quantization: str | None = None
    license: str | None = None
    size_bytes: int | None = None
    capabilities: Capabilities = field(default_factory=Capabilities)
    hardware_profile: HardwareProfile = HardwareProfile.UNKNOWN
    compatibility: Compatibility = Compatibility.UNKNOWN
    status: ModelStatus = ModelStatus.NOT_INSTALLED
    validation_status: str | None = None
    fallback_model_id: str | None = None
    provider_version: str | None = None
    notes: str | None = None
    priority: int = 0
    enabled: bool = True
    fallback_eligible: bool = True
    context_limit: int | None = None
    structured_output_supported: bool | None = None
    local_only: bool = True
    expected_digest: str | None = None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelEntry":
        required = (
            "logical_model_id",
            "contract_model_id",
            "display_name",
            "family",
            "provider",
            "provider_model_id",
        )
        missing = [key for key in required if not value.get(key)]
        if missing:
            raise ValueError(f"model registry entry missing required fields: {', '.join(missing)}")
        return cls(
            logical_model_id=str(value["logical_model_id"]),
            contract_model_id=str(value["contract_model_id"]),
            display_name=str(value["display_name"]),
            family=str(value["family"]),
            parameters=value.get("parameters"),
            provider=str(value["provider"]),
            provider_model_id=str(value["provider_model_id"]),
            source=value.get("source"),
            source_repository=value.get("source_repository"),
            revision=value.get("revision"),
            digest=value.get("digest"),
            format=value.get("format"),
            quantization=value.get("quantization"),
            license=value.get("license"),
            size_bytes=value.get("size_bytes"),
            capabilities=Capabilities.from_dict(value.get("capabilities")),
            hardware_profile=HardwareProfile(value.get("hardware_profile", HardwareProfile.UNKNOWN)),
            compatibility=Compatibility(value.get("compatibility", Compatibility.UNKNOWN)),
            status=ModelStatus(value.get("status", ModelStatus.NOT_INSTALLED)),
            validation_status=value.get("validation_status"),
            fallback_model_id=value.get("fallback_model_id"),
            provider_version=value.get("provider_version"),
            notes=value.get("notes"),
            priority=int(value.get("priority", 0)),
            enabled=bool(value.get("enabled", True)),
            fallback_eligible=bool(value.get("fallback_eligible", True)),
            context_limit=(int(value["context_limit"]) if value.get("context_limit") is not None else None),
            structured_output_supported=(
                bool(value["structured_output_supported"])
                if value.get("structured_output_supported") is not None
                else None
            ),
            local_only=bool(value.get("local_only", True)),
            expected_digest=value.get("expected_digest") or value.get("digest"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_model_id": self.logical_model_id,
            "contract_model_id": self.contract_model_id,
            "display_name": self.display_name,
            "family": self.family,
            "parameters": self.parameters,
            "provider": self.provider,
            "provider_model_id": self.provider_model_id,
            "source": self.source,
            "source_repository": self.source_repository,
            "revision": self.revision,
            "digest": self.digest,
            "format": self.format,
            "quantization": self.quantization,
            "license": self.license,
            "size_bytes": self.size_bytes,
            "capabilities": self.capabilities.to_dict(),
            "hardware_profile": self.hardware_profile.value,
            "compatibility": self.compatibility.value,
            "status": self.status.value,
            "validation_status": self.validation_status,
            "fallback_model_id": self.fallback_model_id,
            "provider_version": self.provider_version,
            "notes": self.notes,
            "priority": self.priority,
            "enabled": self.enabled,
            "fallback_eligible": self.fallback_eligible,
            "context_limit": self.context_limit,
            "structured_output_supported": self.structured_output_supported,
            "local_only": self.local_only,
            "expected_digest": self.expected_digest,
        }

    def update_from_discovery(self, discovered: Mapping[str, Any]) -> "ModelEntry":
        """Return a copy enriched by an actual provider discovery response."""

        actual_digest = discovered.get("digest") or self.digest
        digest_matches = (
            self.expected_digest is None
            or actual_digest is None
            or str(actual_digest) == str(self.expected_digest)
        )
        return replace(
            self,
            provider_model_id=str(discovered.get("provider_model_id", self.provider_model_id)),
            revision=discovered.get("revision") or self.revision,
            digest=actual_digest,
            format=discovered.get("format") or self.format,
            quantization=discovered.get("quantization") or self.quantization,
            license=discovered.get("license") or self.license,
            size_bytes=discovered.get("size_bytes") or self.size_bytes,
            provider_version=discovered.get("provider_version") or self.provider_version,
            status=ModelStatus.READY if digest_matches else ModelStatus.DEGRADED,
            compatibility=Compatibility.SUPPORTED if digest_matches else Compatibility.DEGRADED,
        )


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    @classmethod
    def from_ollama(cls, value: Mapping[str, Any]) -> "Usage":
        prompt = value.get("prompt_eval_count")
        completion = value.get("eval_count")
        total = None
        if prompt is not None and completion is not None:
            total = int(prompt) + int(completion)
        return cls(
            prompt_tokens=int(prompt) if prompt is not None else None,
            completion_tokens=int(completion) if completion is not None else None,
            total_tokens=total,
        )

    @classmethod
    def from_openai(cls, value: Mapping[str, Any] | None) -> "Usage":
        value = value or {}
        return cls(
            prompt_tokens=_optional_int(value.get("prompt_tokens")),
            completion_tokens=_optional_int(value.get("completion_tokens")),
            total_tokens=_optional_int(value.get("total_tokens")),
        )

    def to_dict(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class GenerationConfig:
    max_output_tokens: int = 256
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int | None = None
    context_length: int | None = None
    timeout_seconds: float = 60.0
    keep_alive: str | int | float = "5m"
    seed: int | None = None
    stop: tuple[str, ...] = ()
    think: bool | str | None = None
    max_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_tokens is not None:
            if self.max_output_tokens != 256 and self.max_output_tokens != self.max_tokens:
                raise ValueError("max_tokens and max_output_tokens disagree")
            self.max_output_tokens = self.max_tokens
        else:
            self.max_tokens = self.max_output_tokens
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if not 0 <= self.temperature:
            raise ValueError("temperature must be non-negative")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
        if self.top_k is not None and self.top_k < 1:
            raise ValueError("top_k must be positive when provided")
        if self.context_length is not None and self.context_length < 1:
            raise ValueError("context_length must be positive when provided")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def to_ollama_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "num_predict": self.max_output_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }
        if self.seed is not None:
            options["seed"] = self.seed
        if self.stop:
            options["stop"] = list(self.stop)
        if self.top_k is not None:
            options["top_k"] = self.top_k
        if self.context_length is not None:
            options["num_ctx"] = self.context_length
        return options

@dataclass
class GenerationRequest:
    """Runtime request containing the frozen Contract identity plus prompt data."""

    request_id: str
    trace_id: str
    generation_id: str
    assessment_id: str
    subject_id: str
    target_role: str
    purpose: str
    language: str
    safety_mode: str
    retrieval_id: str
    chunk_ids: tuple[str, ...]
    prompt_id: str
    prompt_version: str
    contract_model_id: str
    logical_model_id: str
    prompt: str = ""
    messages: tuple[Mapping[str, str], ...] = ()
    stream: bool = False
    system_prompt: str | None = None
    structured_schema: dict[str, Any] | None = None
    config: GenerationConfig = field(default_factory=GenerationConfig)
    provider_model_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_provider_model(self, provider_model_id: str) -> "GenerationRequest":
        return replace(self, provider_model_id=provider_model_id)

    @property
    def generation_config(self) -> GenerationConfig:
        """Provider-neutral alias used by callers that prefer the contract name."""

        return self.config

    @property
    def timeout(self) -> float:
        return self.config.timeout_seconds

    @property
    def effective_messages(self) -> list[dict[str, str]]:
        if self.messages:
            return [dict(message) for message in self.messages]
        messages: list[dict[str, str]] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.append({"role": "user", "content": self.prompt})
        return messages

    @property
    def effective_provider_model_id(self) -> str:
        return self.provider_model_id or self.logical_model_id

    def to_contract_request(self) -> dict[str, Any]:
        return {
            "schema_version": "generation.v1",
            "generation_id": self.generation_id,
            "assessment_id": self.assessment_id,
            "subject_id": self.subject_id,
            "target_role": self.target_role,
            "purpose": self.purpose,
            "language": self.language,
            "safety_mode": self.safety_mode,
            "retrieval": {
                "retrieval_id": self.retrieval_id,
                "chunk_ids": list(self.chunk_ids),
            },
            "prompt_ref": {
                "prompt_id": self.prompt_id,
                "prompt_version": self.prompt_version,
            },
            "model_policy": {
                "model_id": self.contract_model_id,
                "provider_class": "mock" if self.contract_model_id.startswith("MODEL_mock") else "local",
            },
        }


@dataclass
class RuntimeStreamEvent:
    event_type: StreamEventType
    request_id: str
    trace_id: str
    delta: str = ""
    usage: Usage | None = None
    finish_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "type": self.event_type.value,
            "request_id": self.request_id,
            "trace_id": self.trace_id,
        }
        if self.delta:
            result["delta"] = self.delta
        if self.usage is not None:
            result["usage"] = self.usage.to_dict()
        if self.finish_reason is not None:
            result["finish_reason"] = self.finish_reason
        if self.error_code is not None:
            result["error_code"] = self.error_code
        if self.error_message is not None:
            result["error_message"] = self.error_message
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass
class RuntimeTrace:
    trace_id: str
    request_id: str
    logical_model: str
    provider: str
    provider_model: str
    model_revision: str | None
    digest: str | None
    quantization: str | None
    runtime_version: str
    hardware: Mapping[str, Any]
    generation_config: Mapping[str, Any]
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    ttft_ms: float | None = None
    generation_latency_ms: float | None = None
    total_latency_ms: float | None = None
    tokens_per_second: float | None = None
    retry_count: int = 0
    requested_model: str | None = None
    actual_model: str | None = None
    fallback_reason: str | None = None
    finish_reason: str | None = None
    error: Mapping[str, Any] | None = None
    requested_provider_model: str | None = None
    primary_error: Mapping[str, Any] | None = None
    primary_error_normalized_code: str | None = None
    fallback_attempted: bool = False
    fallback_model: str | None = None
    fallback_provider_model: str | None = None
    fallback_generation_success: bool | None = None
    fallback_count: int = 0
    attempts: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "request_id": self.request_id,
            "logical_model": self.logical_model,
            "provider": self.provider,
            "provider_model": self.provider_model,
            "model_revision": self.model_revision,
            "digest": self.digest,
            "quantization": self.quantization,
            "runtime_version": self.runtime_version,
            "hardware": dict(self.hardware),
            "generation_config": dict(self.generation_config),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "ttft_ms": self.ttft_ms,
            "generation_latency_ms": self.generation_latency_ms,
            "total_latency_ms": self.total_latency_ms,
            "tokens_per_second": self.tokens_per_second,
            "retry_count": self.retry_count,
            "requested_model": self.requested_model,
            "actual_model": self.actual_model,
            "fallback_reason": self.fallback_reason,
            "finish_reason": self.finish_reason,
            "error": dict(self.error) if self.error else None,
            "requested_provider_model": self.requested_provider_model,
            "primary_error": dict(self.primary_error) if self.primary_error else None,
            "primary_error_normalized_code": self.primary_error_normalized_code,
            "fallback_attempted": self.fallback_attempted,
            "fallback_model": self.fallback_model,
            "fallback_provider_model": self.fallback_provider_model,
            "fallback_generation_success": self.fallback_generation_success,
            "fallback_count": self.fallback_count,
            "attempts": [dict(attempt) for attempt in self.attempts],
        }


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    provider: str
    provider_model: str
    runtime_version: str
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None
    structured: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderHealth:
    provider: str
    liveness: str
    readiness: str
    version: str | None
    endpoint: str
    error_code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "liveness": self.liveness,
            "readiness": self.readiness,
            "version": self.version,
            "endpoint": self.endpoint,
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class ModelHealth:
    logical_model_id: str
    provider_model_id: str
    availability: str
    inference_readiness: str
    loaded: bool
    error_code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "logical_model_id": self.logical_model_id,
            "provider_model_id": self.provider_model_id,
            "availability": self.availability,
            "inference_readiness": self.inference_readiness,
            "loaded": self.loaded,
            "error_code": self.error_code,
            "message": self.message,
        }


@dataclass(frozen=True)
class GPUInfo:
    name: str
    vram_bytes: int | None
    driver: str | None
    cuda_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "vram_bytes": self.vram_bytes,
            "driver": self.driver,
            "cuda_version": self.cuda_version,
        }


@dataclass(frozen=True)
class HardwareInfo:
    os: str
    cpu: str
    threads: int
    ram_bytes: int | None
    gpu_present: bool
    gpus: tuple[GPUInfo, ...] = ()
    cuda_available: bool = False
    nvidia_smi_path: str | None = None
    detection_error: str | None = None

    @property
    def profile(self) -> HardwareProfile:
        if not self.gpu_present:
            return HardwareProfile.CPU_ONLY
        return HardwareProfile.CONSUMER_GPU if self.gpus else HardwareProfile.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": self.os,
            "cpu": self.cpu,
            "threads": self.threads,
            "ram_bytes": self.ram_bytes,
            "gpu_present": self.gpu_present,
            "gpus": [gpu.to_dict() for gpu in self.gpus],
            "cuda_available": self.cuda_available,
            "nvidia_smi_path": self.nvidia_smi_path,
            "detection_error": self.detection_error,
            "profile": self.profile.value,
        }


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None
