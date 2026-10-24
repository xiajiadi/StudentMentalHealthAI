"""Validated, domain-scoped Backend configuration."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "demo", "research", "production"]
ClientMode = Literal["http", "contract_fake"]
PersistenceMode = Literal["memory", "mysql"]
IdentityProfile = Literal["legacy_demo", "school_tenant"]
_SCHOOL_CSRF_SECRET_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_RESEARCH_PROGRAMME_MANIFEST_SHA256 = (
    "f8af1a33487f175b02400fbfcf5f655cd93b40c7a5a35e0582dc363b11401a45"
)
_RESEARCH_PROGRAMME_SOURCE_STUDY_REF = "school-noncommercial-rag-research-2027-06"
_SCHOOL_RESEARCH_STUDENT_STUDY_REF = "school-noncommercial-rag-research-2027-06"
_SCHOOL_RESEARCH_STUDENT_R1_MANIFEST_SHA256 = (
    "70637b39cb11a34de91599a1a32e9e1a6edff6a76b19cc1b11895ee7170e9974"
)
_SCHOOL_RESEARCH_STUDENT_R3_MANIFEST_SHA256 = (
    "ac9cc1641faa565ff7a18866be1c2dbf8aaf16aff7155ea80c38bfd979429a9b"
)
_SCHOOL_RESEARCH_STUDENT_MANIFEST_SHA256 = _SCHOOL_RESEARCH_STUDENT_R1_MANIFEST_SHA256
SUPPORTED_MANIFEST_SHA256S = frozenset(
    {
        _SCHOOL_RESEARCH_STUDENT_R1_MANIFEST_SHA256,
        _SCHOOL_RESEARCH_STUDENT_R3_MANIFEST_SHA256,
    }
)
RESEARCH_PROGRAMME_PROCESSOR_POLICY_SHA256 = (
    "70a71a65a2dad7b862ba792762069ef7ed4c02152f33dc87d0689cbc5aff1689"
)


def school_csrf_secret_bytes(secret: str | SecretStr | None) -> bytes:
    """Validate and decode the deployment-provided 32-byte hex secret."""

    raw = secret.get_secret_value() if isinstance(secret, SecretStr) else secret
    if not isinstance(raw, str) or _SCHOOL_CSRF_SECRET_PATTERN.fullmatch(raw) is None:
        raise ValueError("school CSRF secret must be exactly 64 hexadecimal characters")
    return bytes.fromhex(raw)


class TimeoutSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connect: float = Field(default=1.0, gt=0)
    read: float = Field(default=8.0, gt=0)
    write: float = Field(default=8.0, gt=0)
    pool: float = Field(default=1.0, gt=0)


class ModuleClientSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: ClientMode = "contract_fake"
    base_url: str = "http://127.0.0.1:8190"
    timeout: TimeoutSettings = Field(default_factory=TimeoutSettings)
    max_connections: int = Field(default=20, ge=1, le=200)
    max_keepalive_connections: int = Field(default=10, ge=1, le=200)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("module base_url must use http or https")
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError("module base_url must have a host and no credentials or fragment")
        return value.rstrip("/")


class LLMModuleClientSettings(ModuleClientSettings):
    """Keep the Runtime request window when launcher env overrides other LLM fields."""

    internal_auth_token: SecretStr | None = Field(default=None, repr=False)
    logical_model_id: str = Field(
        default="qwen2.5-0.5b-engineering",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/+-]*$",
    )
    context_length: int | None = Field(default=None, ge=1, le=8192, strict=True)
    timeout: TimeoutSettings = Field(default_factory=lambda: TimeoutSettings(read=65.0))

    @field_validator("context_length", mode="before")
    @classmethod
    def parse_context_length_environment(cls, value: Any) -> Any:
        if isinstance(value, str) and re.fullmatch(r"[0-9]{1,4}", value):
            return int(value)
        return value


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
    reauthentication_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    login_lock_threshold: int = Field(default=5, ge=2, le=20)
    login_lock_duration_seconds: int = Field(default=900, ge=60, le=86_400)
    initial_credential_ttl_seconds: int = Field(
        default=604_800, ge=3600, le=1_209_600
    )
    staff_invitation_ttl_seconds: int = Field(
        default=604_800, ge=3600, le=1_209_600
    )
    password_reset_ttl_seconds: int = Field(default=900, ge=600, le=900)
    cookie_name: str = "smhai_dev_session"
    production_cookie_name: str = "__Host-smhai_session"
    secure_cookie: bool = False
    same_site: Literal["lax", "strict"] = "lax"
    csrf_header_name: str = "X-CSRF-Token"

    @field_validator("cookie_name", "production_cookie_name")
    @classmethod
    def validate_cookie_name(cls, value: str) -> str:
        if not value or ";" in value or "=" in value or " " in value:
            raise ValueError("invalid session cookie name")
        return value


class RateLimitSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    login_max_requests: int = Field(default=5, ge=1, le=1000)
    support_max_requests: int = Field(default=10, ge=1, le=1000)
    window_seconds: int = Field(default=60, ge=1, le=3600)


class ObservabilitySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_logs: bool = True
    enable_otel: bool = False


class PostAssessmentWorkerSettings(BaseModel):
    """Bounded local worker settings; publication and model clients are absent."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = Field(default=None, strict=True)
    policy_version: str = Field(
        default="NO_PERSONALIZED_POLICY_V1",
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    poll_interval_seconds: float = Field(default=1.0, ge=0.01, le=60, strict=True)
    lease_seconds: int = Field(default=60, ge=5, le=3600, strict=True)
    heartbeat_interval_seconds: float | None = Field(
        default=None, gt=0, le=1200, strict=True
    )
    max_attempts: int = Field(default=5, ge=1, le=20, strict=True)
    shutdown_drain_seconds: float = Field(default=10.0, gt=0, le=120, strict=True)

    @field_validator(
        "poll_interval_seconds",
        "lease_seconds",
        "heartbeat_interval_seconds",
        "max_attempts",
        "shutdown_drain_seconds",
        mode="before",
    )
    @classmethod
    def validate_finite_numeric_settings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("post-assessment numeric settings must be JSON numbers")
        if not math.isfinite(float(value)):
            raise ValueError("post-assessment numeric settings must be finite")
        return value

    @model_validator(mode="after")
    def validate_heartbeat(self) -> PostAssessmentWorkerSettings:
        if (
            self.heartbeat_interval_seconds is not None
            and self.heartbeat_interval_seconds >= self.lease_seconds
        ):
            raise ValueError("post-assessment heartbeat must be shorter than its lease")
        return self


class ResearchEducationWorkerSettings(BaseModel):
    """Explicitly enabled, single-slot research outbox consumer settings."""

    model_config = ConfigDict(extra="forbid")

    # Unlike the legacy school post-assessment worker, this lane is never
    # inferred from the presence of MySQL or a school identity profile.
    enabled: StrictBool = False
    poll_interval_seconds: float = Field(default=1.0, ge=0.01, le=60, strict=True)
    lease_seconds: int = Field(default=60, ge=5, le=3600, strict=True)
    max_attempts: int = Field(default=5, ge=1, le=20, strict=True)
    shutdown_drain_seconds: float = Field(default=10.0, gt=0, le=120, strict=True)

    @field_validator(
        "poll_interval_seconds",
        "lease_seconds",
        "max_attempts",
        "shutdown_drain_seconds",
        mode="before",
    )
    @classmethod
    def validate_finite_numeric_settings(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("research education numeric settings must be JSON numbers")
        if not math.isfinite(float(value)):
            raise ValueError("research education numeric settings must be finite")
        return value


class ResearchGeneralEducationDraftSettings(BaseModel):
    """Trusted pins, API lane and bounded worker settings for held drafts."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    worker_enabled: StrictBool = True
    input_review_continuation_enabled: StrictBool = False
    school_id: StrictInt | None = None
    school_study_ref: StrictStr | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    policy_version: Literal["RESEARCH_GENERAL_EDUCATION_DRAFT_V1"] = (
        "RESEARCH_GENERAL_EDUCATION_DRAFT_V1"
    )
    policy_hash: StrictStr | None = None
    source_study_ref: StrictStr | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    )
    source_manifest_sha256: StrictStr | None = None
    source_manifest_file: StrictStr | None = Field(default=None, repr=False)
    poll_interval_seconds: float = Field(default=1.0, ge=0.01, le=60, strict=True)
    lease_seconds: StrictInt = Field(default=300, ge=120, le=3600)
    max_attempts: Literal[1] = 1
    shutdown_drain_seconds: float = Field(default=10.0, gt=0, le=120, strict=True)

    @field_validator("max_attempts", mode="before")
    @classmethod
    def validate_single_attempt(cls, value: Any) -> Any:
        if type(value) is not int or value != 1:
            raise ValueError("research education generation allows exactly one attempt")
        return value

    @field_validator("policy_hash", "source_manifest_sha256")
    @classmethod
    def validate_hash_pins(cls, value: str | None) -> str | None:
        if value is not None and (
            type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None
        ):
            raise ValueError("research education pins must be lowercase SHA-256 values")
        return value

    @field_validator(
        "poll_interval_seconds", "shutdown_drain_seconds", mode="before"
    )
    @classmethod
    def validate_finite_worker_settings(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("research education worker settings must be JSON numbers")
        if not math.isfinite(float(value)):
            raise ValueError("research education worker settings must be finite")
        return value

    @model_validator(mode="after")
    def validate_enabled_pins(self) -> ResearchGeneralEducationDraftSettings:
        if self.input_review_continuation_enabled and not self.enabled:
            raise ValueError(
                "input-review continuation requires the general-education draft lane"
            )
        if not self.enabled:
            return self
        manifest_file = self.source_manifest_file
        if (
            isinstance(self.school_id, bool)
            or not isinstance(self.school_id, int)
            or self.school_id < 1
            or not isinstance(self.school_study_ref, str)
            or not isinstance(self.policy_hash, str)
            or _SHA256_PATTERN.fullmatch(self.policy_hash) is None
            or self.source_study_ref != _SCHOOL_RESEARCH_STUDENT_STUDY_REF
            or self.source_manifest_sha256 != _SCHOOL_RESEARCH_STUDENT_R3_MANIFEST_SHA256
            or not isinstance(manifest_file, str)
            or not manifest_file
            or not (
                Path(manifest_file).is_absolute()
                or PureWindowsPath(manifest_file).is_absolute()
            )
            or any(part == ".." for part in re.split(r"[\\/]", manifest_file))
        ):
            raise ValueError("research general-education draft requires exact server pins")
        return self


class ResearchProgrammeWorkerSettings(BaseModel):
    """Explicit, non-production staff-programme generation lane."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    package_manifest_file: str | None = Field(default=None, repr=False)
    package_manifest_sha256: str | None = None
    processor_policy_sha256: str | None = None
    model_ref: str | None = None
    model_digest_sha256: str | None = None
    prompt_ref: str | None = None
    prompt_version: str | None = None
    poll_interval_seconds: float = Field(default=1.0, ge=0.01, le=60, strict=True)
    lease_seconds: int = Field(default=180, ge=5, le=3600, strict=True)
    max_attempts: int = Field(default=5, ge=1, le=20, strict=True)
    shutdown_drain_seconds: float = Field(default=10.0, gt=0, le=120, strict=True)

    @field_validator(
        "poll_interval_seconds", "lease_seconds", "max_attempts", "shutdown_drain_seconds",
        mode="before",
    )
    @classmethod
    def validate_finite_numeric_settings(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("research programme numeric settings must be JSON numbers")
        if not math.isfinite(float(value)):
            raise ValueError("research programme numeric settings must be finite")
        return value

    @field_validator(
        "package_manifest_sha256", "processor_policy_sha256", "model_digest_sha256"
    )
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        if value is not None and (type(value) is not str or not _SHA256_PATTERN.fullmatch(value)):
            raise ValueError("research programme pins must be lowercase SHA-256 values")
        return value

    @model_validator(mode="after")
    def validate_enabled_pins(self) -> ResearchProgrammeWorkerSettings:
        if not self.enabled:
            return self
        if (
            not isinstance(self.package_manifest_file, str)
            or not self.package_manifest_file
            or not (
                Path(self.package_manifest_file).is_absolute()
                or PureWindowsPath(self.package_manifest_file).is_absolute()
            )
            or any(part == ".." for part in re.split(r"[\\/]", self.package_manifest_file))
            or not self.package_manifest_sha256
            or self.package_manifest_sha256 != _RESEARCH_PROGRAMME_MANIFEST_SHA256
            or self.processor_policy_sha256 != RESEARCH_PROGRAMME_PROCESSOR_POLICY_SHA256
            or self.model_ref != "qwen2.5-7b-instruct-school-demo"
            or self.model_digest_sha256
            != "845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e"
            or self.prompt_ref != "PROMPT_staff_school_programme_research_v1"
            or self.prompt_version != "1.2.0"
        ):
            raise ValueError("research programme generation requires explicit server pins")
        return self


class SchoolResearchStudentConversationSettings(BaseModel):
    """Server-pinned, opt-in secondary-school general-education lane."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool = False
    school_id: StrictInt | None = None
    purpose: Literal["RESEARCH_SIMULATION"] = "RESEARCH_SIMULATION"
    study_ref: str | None = None
    manifest_file: str | None = Field(default=None, repr=False)
    manifest_sha256: str | None = None
    safety_base_url: Literal["http://127.0.0.1:8191"] | None = None
    consumer_age_min: StrictInt = Field(default=14, ge=14, le=17)
    consumer_age_max: StrictInt = Field(default=17, ge=14, le=17)

    @field_validator("manifest_sha256")
    @classmethod
    def validate_student_manifest_hash(cls, value: str | None) -> str | None:
        if value is not None and (
            type(value) is not str or not _SHA256_PATTERN.fullmatch(value)
        ):
            raise ValueError("school student manifest pin must be lowercase SHA-256")
        return value

    @model_validator(mode="after")
    def validate_enabled_lane(self) -> SchoolResearchStudentConversationSettings:
        if not self.enabled:
            return self
        if (
            isinstance(self.school_id, bool)
            or not isinstance(self.school_id, int)
            or self.school_id < 1
            or self.study_ref != _SCHOOL_RESEARCH_STUDENT_STUDY_REF
            or self.manifest_sha256 not in SUPPORTED_MANIFEST_SHA256S
            or not isinstance(self.manifest_file, str)
            or not (
                Path(self.manifest_file).is_absolute()
                or PureWindowsPath(self.manifest_file).is_absolute()
            )
            or any(part == ".." for part in re.split(r"[\\/]", self.manifest_file))
            or self.purpose != "RESEARCH_SIMULATION"
            or self.safety_base_url != "http://127.0.0.1:8191"
            or self.consumer_age_min != 14
            or self.consumer_age_max != 17
        ):
            raise ValueError("school research student lane requires exact server pins")
        return self


class BackendSettings(BaseSettings):
    """Backend-local settings; the frozen config.v1 remains unchanged."""

    model_config = SettingsConfigDict(
        env_prefix="SMHAI_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    def __init__(self, **values: Any) -> None:
        try:
            super().__init__(**values)
        except ValidationError as exc:
            safe_errors = exc.errors(include_input=False)
            csrf_error = any(
                entry.get("loc") == ()
                and "SMHAI_SCHOOL_CSRF_SECRET" in str(entry.get("msg", ""))
                for entry in safe_errors
            )
            if csrf_error:
                missing = any(
                    "requires SMHAI_SCHOOL_CSRF_SECRET" in str(entry.get("msg", ""))
                    for entry in safe_errors
                )
                detail = (
                    "school_tenant requires SMHAI_SCHOOL_CSRF_SECRET"
                    if missing
                    else "SMHAI_SCHOOL_CSRF_SECRET must be exactly 64 hexadecimal characters"
                )
                raise ValueError(
                    f"{detail}; supplied values are redacted"
                ) from None
            raise

    environment: Environment = "local"
    api_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65_535)
    docs_enabled: bool = True
    persistence_mode: PersistenceMode = "memory"
    identity_profile: IdentityProfile = "legacy_demo"
    school_csrf_secret: SecretStr | None = Field(
        default=None, validate_default=True, repr=False
    )
    allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
    allowed_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver", "test"]
    )
    support_deadline_seconds: float = Field(default=80.0, gt=0, le=120)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    post_assessment_worker: PostAssessmentWorkerSettings = Field(
        default_factory=PostAssessmentWorkerSettings
    )
    research_education_worker: ResearchEducationWorkerSettings = Field(
        default_factory=ResearchEducationWorkerSettings
    )
    research_general_education_draft: ResearchGeneralEducationDraftSettings = Field(
        default_factory=ResearchGeneralEducationDraftSettings
    )
    research_programme_worker: ResearchProgrammeWorkerSettings = Field(
        default_factory=ResearchProgrammeWorkerSettings
    )
    school_research_student_conversation: SchoolResearchStudentConversationSettings = Field(
        default_factory=SchoolResearchStudentConversationSettings
    )
    m0_claim_boundary_observer_enabled: bool = False
    school_research_enabled: bool = False
    school_research_runtime_file: str | None = Field(default=None, repr=False)
    school_research_runtime_sha256: str | None = None
    school_research_base_url: str | None = Field(default=None, repr=False)
    school_research_managed_enabled: bool = False
    school_research_service_file: str | None = Field(default=None, repr=False)
    school_research_service_sha256: str | None = None
    school_research_cat_python: str | None = Field(default=None, repr=False)
    school_research_cat_source: str | None = Field(default=None, repr=False)
    school_research_cat_dependencies: str | None = Field(default=None, repr=False)
    school_research_study_use_file: str | None = Field(default=None, repr=False)
    school_research_study_use_sha256: str | None = None
    school_research_source_rights_verified: StrictBool = False
    school_research_latest_study_end: datetime | None = None
    cat: ModuleClientSettings = Field(
        default_factory=lambda: ModuleClientSettings(
            mode="contract_fake", base_url="http://127.0.0.1:8180"
        )
    )
    rag: ModuleClientSettings = Field(
        default_factory=lambda: ModuleClientSettings(
            mode="contract_fake", base_url="http://127.0.0.1:8170"
        )
    )
    llm: LLMModuleClientSettings = Field(
        default_factory=lambda: LLMModuleClientSettings(
            mode="contract_fake",
            base_url="http://127.0.0.1:8160",
        )
    )
    research_programme_runtime: LLMModuleClientSettings = Field(
        default_factory=lambda: LLMModuleClientSettings(
            mode="contract_fake", base_url="http://127.0.0.1:8161"
        ),
        repr=False,
    )
    safety: ModuleClientSettings = Field(default_factory=ModuleClientSettings)

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("api_prefix must start with / and not end with /")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, values: list[str]) -> list[str]:
        if "*" in values:
            raise ValueError("wildcard CORS origins are not allowed")
        for value in values:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("CORS origins must be absolute http(s) origins")
        return values

    @model_validator(mode="after")
    def validate_production_security(self) -> BackendSettings:
        study_configured = (
            self.school_research_study_use_file is not None
            or self.school_research_study_use_sha256 is not None
            or self.school_research_source_rights_verified
            or self.school_research_latest_study_end is not None
        )
        if study_configured:
            end = self.school_research_latest_study_end
            if (
                not self.school_research_enabled
                or not self.school_research_managed_enabled
                or not self.school_research_study_use_file
                or not self.school_research_study_use_sha256
                or not re.fullmatch(r"[0-9a-f]{64}", self.school_research_study_use_sha256)
                or self.school_research_source_rights_verified is not True
                or end is None
                or end.tzinfo is None
                or end.utcoffset() != timedelta(0)
            ):
                raise ValueError("research study use requires explicit verified UTC server pins")
        if self.school_research_managed_enabled and (
            not self.school_research_enabled
            or not self.school_research_service_file
            or not self.school_research_service_sha256
            or not self.school_research_cat_python
            or not self.school_research_cat_source
            or not self.school_research_cat_dependencies
        ):
            raise ValueError(
                "managed research CAT requires explicit isolated process configuration"
            )
        if self.school_research_enabled:
            if (
                self.environment == "production" or self.identity_profile != "school_tenant"
                or self.persistence_mode != "mysql"
                or not self.school_research_runtime_file
                or not self.school_research_runtime_sha256
                or not self.school_research_base_url
            ):
                raise ValueError(
                    "research CAT requires explicit nonproduction school configuration"
                )
        if self.identity_profile == "school_tenant":
            if self.school_csrf_secret is None:
                raise ValueError("school_tenant requires SMHAI_SCHOOL_CSRF_SECRET")
            try:
                school_csrf_secret_bytes(self.school_csrf_secret)
            except ValueError:
                raise ValueError(
                    "SMHAI_SCHOOL_CSRF_SECRET must be exactly 64 hexadecimal characters"
                ) from None
        else:
            self.school_csrf_secret = None
        if self.post_assessment_worker.enabled is True and (
            self.identity_profile != "school_tenant" or self.persistence_mode != "mysql"
        ):
            raise ValueError(
                "post-assessment worker requires school_tenant MySQL persistence"
            )
        if self.research_education_worker.enabled and (
            self.environment == "production"
            or self.identity_profile != "school_tenant"
            or self.persistence_mode != "mysql"
            or not self.school_research_enabled
            or not self.school_research_managed_enabled
            or not self.school_research_study_use_file
        ):
            raise ValueError(
                "research education worker requires nonproduction managed school research "
                "with MySQL and a pinned study-use policy"
            )
        education_draft = self.research_general_education_draft
        student_lane = self.school_research_student_conversation
        if education_draft.enabled and (
            self.environment == "production"
            or self.identity_profile != "school_tenant"
            or self.persistence_mode != "mysql"
            or not self.school_research_enabled
            or not self.school_research_managed_enabled
            or not self.school_research_study_use_file
            or self.school_research_source_rights_verified is not True
            or not student_lane.enabled
            or education_draft.school_id != student_lane.school_id
            or education_draft.source_study_ref != student_lane.study_ref
            or education_draft.source_manifest_file != student_lane.manifest_file
            or education_draft.source_manifest_sha256 != student_lane.manifest_sha256
            or self.research_programme_runtime.mode != "http"
            or self.research_programme_runtime.base_url != "http://127.0.0.1:8161"
            or self.research_programme_runtime.timeout.read < 65
        ):
            raise ValueError(
                "research general-education draft requires nonproduction school MySQL, "
                "matching R3 student package pins, and the private 8161 Runtime"
            )
        if self.research_programme_worker.enabled and (
            self.environment == "production"
            or self.identity_profile != "school_tenant"
            or self.persistence_mode != "mysql"
            or not self.school_research_enabled
            or not self.school_research_managed_enabled
            or not self.school_research_study_use_file
            or self.school_research_source_rights_verified is not True
            or self.safety.mode != "http"
            or self.research_programme_runtime.mode != "http"
            or self.research_programme_runtime.base_url != "http://127.0.0.1:8161"
            or urlparse(self.safety.base_url).scheme != "http"
            or urlparse(self.safety.base_url).hostname not in {"127.0.0.1", "localhost"}
            or urlparse(self.safety.base_url).path not in {"", "/"}
            or urlparse(self.safety.base_url).query
            or urlparse(self.safety.base_url).fragment
        ):
            raise ValueError(
                "research programme worker requires nonproduction managed school research, "
                "verified study scope and real local Safety/Runtime dependencies"
            )
        if self.research_programme_worker.enabled:
            bounded_runtime_window = (
                min(float(self.research_programme_runtime.timeout.read), 120.0)
                + 3.0 * float(self.safety.timeout.read)
                + 15.0
            )
            if self.research_programme_worker.lease_seconds < bounded_runtime_window:
                raise ValueError(
                    "research programme lease must exceed the bounded Safety and Runtime window"
                )
        if self.school_research_student_conversation.enabled and (
            self.environment == "production"
            or self.identity_profile != "school_tenant"
            or self.persistence_mode != "mysql"
            or self.safety.mode != "http"
            or self.safety.base_url != "http://127.0.0.1:8190"
            or self.llm.mode != "http"
            or self.llm.base_url != "http://127.0.0.1:8160"
        ):
            raise ValueError(
                "school research student lane requires nonproduction school MySQL "
                "and local Safety/Runtime"
            )
        if self.environment == "production":
            if self.identity_profile != "school_tenant":
                raise ValueError("production requires the school_tenant identity profile")
            if not self.auth.secure_cookie:
                raise ValueError("production sessions require Secure cookies")
            if self.auth.same_site != "lax":
                raise ValueError("production sessions use SameSite=Lax in Round 1")
            if self.auth.cookie_name != self.auth.production_cookie_name:
                raise ValueError("production sessions require the __Host- cookie name")
            if "*" in self.allowed_hosts:
                raise ValueError("production trusted hosts cannot be wildcard")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def cookie_name(self) -> str:
        return self.auth.production_cookie_name if self.is_production else self.auth.cookie_name

    @property
    def trust_env_for_local_clients(self) -> bool:
        return False

    @property
    def post_assessment_worker_enabled(self) -> bool:
        if self.post_assessment_worker.enabled is not None:
            return self.post_assessment_worker.enabled
        return self.identity_profile == "school_tenant" and self.persistence_mode == "mysql"

    @property
    def research_education_worker_enabled(self) -> bool:
        return self.research_education_worker.enabled

    def research_programme_job_policy_sha256_for(
        self, *, school_study_ref: str
    ) -> str | None:
        """Bind school-use and source-use references to the outbox policy identity."""
        worker = self.research_programme_worker
        if (
            type(school_study_ref) is not str
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", school_study_ref) is None
        ):
            return None
        values = (
            worker.processor_policy_sha256,
            worker.package_manifest_sha256,
            worker.model_ref,
            worker.model_digest_sha256,
            worker.prompt_ref,
            worker.prompt_version,
            self.school_research_study_use_sha256,
            self.research_programme_runtime.base_url,
        )
        if not worker.enabled or any(value is None for value in values):
            return None
        payload = {
            "schema": "psynova.research-staff-programme-job-policy.v1",
            "policy_version": "RESEARCH_STAFF_PROGRAMME_POLICY_V1",
            "processor_policy_sha256": worker.processor_policy_sha256,
            "source_manifest_sha256": worker.package_manifest_sha256,
            "source_study_ref": _RESEARCH_PROGRAMME_SOURCE_STUDY_REF,
            "study_policy_sha256": self.school_research_study_use_sha256,
            "school_study_ref": school_study_ref,
            "programme_runtime": self.research_programme_runtime.base_url,
            "programme_ref": "PROGRAMME_SCHOOL_CONNECTEDNESS_REFERENCE_V1",
            "model_ref": worker.model_ref,
            "model_digest_sha256": worker.model_digest_sha256,
            "prompt_ref": worker.prompt_ref,
            "prompt_version": worker.prompt_version,
        }
        canonical = json.dumps(
            payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("ascii")
        return hashlib.sha256(canonical).hexdigest()
