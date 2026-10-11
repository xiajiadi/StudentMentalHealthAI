"""Validated, domain-scoped Backend configuration."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "demo", "research", "production"]
ClientMode = Literal["http", "contract_fake"]
PersistenceMode = Literal["memory", "mysql"]
IdentityProfile = Literal["legacy_demo", "school_tenant"]


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

    timeout: TimeoutSettings = Field(default_factory=lambda: TimeoutSettings(read=65.0))


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_ttl_seconds: int = Field(default=1800, ge=60, le=86_400)
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


class BackendSettings(BaseSettings):
    """Backend-local settings; the frozen config.v1 remains unchanged."""

    model_config = SettingsConfigDict(
        env_prefix="SMHAI_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    environment: Environment = "local"
    api_prefix: str = "/api/v1"
    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1, le=65_535)
    docs_enabled: bool = True
    persistence_mode: PersistenceMode = "memory"
    identity_profile: IdentityProfile = "legacy_demo"
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
    m0_claim_boundary_observer_enabled: bool = False
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
