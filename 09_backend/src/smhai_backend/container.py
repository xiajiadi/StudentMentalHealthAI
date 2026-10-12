"""Application dependency graph for the Backend vertical slices."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smhai_backend.adapters.memory.repositories import (
    InMemoryAssessmentRepository,
    InMemoryAuditRepository,
    InMemoryConversationRepository,
    InMemoryIdempotencyStore,
    InMemoryReportRepository,
    InMemoryReviewProjectionRepository,
    InMemorySessionStore,
    InMemoryUserRepository,
)
from smhai_backend.adapters.school_directory import SchoolDirectoryPersistenceAdapter
from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.rate_limit import InMemoryRateLimiter
from smhai_backend.domains.assessment.service import AssessmentService
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.auth.service import AuthService
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.school_directory.service import SchoolDirectoryService
from smhai_backend.domains.school_tasks.service import SchoolTaskService
from smhai_backend.domains.support.service import SupportOrchestrator
from smhai_backend.domains.teacher.service import TeacherDashboardService
from smhai_backend.integrations.cat import ContractFakeCatClient, HttpCatClient
from smhai_backend.integrations.llm import ContractFakeLLMRuntimeClient, HttpLLMRuntimeClient
from smhai_backend.integrations.rag import ContractFakeRagClient, HttpRagClient
from smhai_backend.integrations.safety import (
    ContractFakeSafetyClient,
    HttpSafetyClient,
    SafetyClient,
)


@dataclass(slots=True)
class BackendContainer:
    settings: BackendSettings
    users: Any
    sessions: Any
    assessments_repo: Any
    conversations: Any
    reports: Any
    reviews: Any
    audits: Any
    idempotency: Any
    persistence: Any
    authorization: NativeAuthorizationProvider
    audit: AuditService
    auth: AuthService
    cat: Any
    rag: Any
    llm: Any
    safety: SafetyClient
    assessments: AssessmentService
    support: SupportOrchestrator
    teacher_dashboard: TeacherDashboardService
    school_tasks: SchoolTaskService
    school_directory: SchoolDirectoryService
    rate_limiter: InMemoryRateLimiter

    async def start(self) -> None:
        if self.persistence is not None:
            await self.persistence.start()
        await self.safety.start()

    async def close(self) -> None:
        await self.safety.close()
        for client in (self.cat, self.rag, self.llm):
            close = getattr(client, "close", None)
            if close is not None:
                await maybe_await(close())
        if self.persistence is not None:
            await self.persistence.close()

    async def dependency_matrix(self, context) -> dict[str, dict[str, Any]]:
        statuses: dict[str, dict[str, Any]] = {}
        for name in ("cat", "rag", "llm_runtime", "safety"):
            client = getattr(self, name if name != "llm_runtime" else "llm")
            try:
                if name == "safety":
                    value = await self.safety.health(context)
                elif name == "cat":
                    value = await self.cat.health()
                elif name == "rag":
                    value = await self.rag.health()
                else:
                    value = await self.llm.health()
                statuses[name] = {
                    "status": str(value.get("status", "UNKNOWN")),
                    "integration": getattr(client, "label", "DEFERRED"),
                }
            except Exception:
                statuses[name] = {
                    "status": "UNAVAILABLE",
                    "integration": getattr(client, "label", "DEFERRED"),
                }
        return statuses


def build_container(settings: BackendSettings | None = None) -> BackendContainer:
    settings = settings or BackendSettings()
    persistence = None
    users: Any
    sessions: Any
    assessments_repo: Any
    conversations: Any
    reports: Any
    reviews: Any
    audits: Any
    idempotency: Any
    if settings.persistence_mode == "mysql":
        from smhai_backend.adapters.database import MySqlBackendAdapter

        persistence = MySqlBackendAdapter(
            repository_root=Path(__file__).resolve().parents[3],
            identity_profile=settings.identity_profile,
            school_csrf_secret=(
                settings.school_csrf_secret.get_secret_value()
                if settings.identity_profile == "school_tenant"
                and settings.school_csrf_secret is not None
                else None
            ),
        )
        users = sessions = assessments_repo = conversations = reports = reviews = audits = (
            idempotency
        ) = persistence
    else:
        users = InMemoryUserRepository(identity_profile=settings.identity_profile)
        sessions = InMemorySessionStore()
        assessments_repo = InMemoryAssessmentRepository()
        conversations = InMemoryConversationRepository()
        reports = InMemoryReportRepository()
        reviews = InMemoryReviewProjectionRepository()
        audits = InMemoryAuditRepository()
        idempotency = InMemoryIdempotencyStore()
    authorization = NativeAuthorizationProvider()
    audit = AuditService(audits)
    auth = AuthService(
        users=users,
        sessions=sessions,
        auth_settings=settings.auth,
        audit=audit,
    )
    cat = HttpCatClient(settings.cat) if settings.cat.mode == "http" else ContractFakeCatClient()
    rag = HttpRagClient(settings.rag) if settings.rag.mode == "http" else ContractFakeRagClient()
    llm = (
        HttpLLMRuntimeClient(settings.llm)
        if settings.llm.mode == "http"
        else ContractFakeLLMRuntimeClient()
    )
    safety: SafetyClient
    if settings.safety.mode == "http":
        safety = HttpSafetyClient(settings.safety)
    else:
        safety = ContractFakeSafetyClient()
    labels = {
        "CAT": cat.label,
        "RAG": rag.label,
        "LLM_RUNTIME": llm.label,
        "SAFETY": safety.label,
    }
    assessments = AssessmentService(
        repository=assessments_repo,
        cat=cat,
        authorization=authorization,
        audit=audit,
    )
    teacher_dashboard = TeacherDashboardService(
        assessments=assessments_repo,
        reports=reports,
        authorization=authorization,
    )
    school_tasks = SchoolTaskService(
        persistence=persistence,
        assessments=assessments,
        cat=cat,
    )
    directory_persistence = (
        SchoolDirectoryPersistenceAdapter(persistence) if persistence is not None else None
    )
    school_directory = SchoolDirectoryService(persistence=directory_persistence)
    support = SupportOrchestrator(
        assessments=assessments,
        conversations=conversations,
        reports=reports,
        reviews=reviews,
        authorization=authorization,
        audit=audit,
        safety=safety,
        rag=rag,
        llm=llm,
        deadline_seconds=settings.support_deadline_seconds,
        integration_labels=labels,
        m0_claim_boundary_observer_enabled=settings.m0_claim_boundary_observer_enabled,
        environment=settings.environment,
        host=settings.host,
    )
    rate_limiter = InMemoryRateLimiter(
        limits={
            "login": settings.rate_limit.login_max_requests,
            "support": settings.rate_limit.support_max_requests,
        },
        window_seconds=settings.rate_limit.window_seconds,
    )
    return BackendContainer(
        settings=settings,
        users=users,
        sessions=sessions,
        assessments_repo=assessments_repo,
        conversations=conversations,
        reports=reports,
        reviews=reviews,
        audits=audits,
        idempotency=idempotency,
        persistence=persistence,
        authorization=authorization,
        audit=audit,
        auth=auth,
        cat=cat,
        rag=rag,
        llm=llm,
        safety=safety,
        assessments=assessments,
        teacher_dashboard=teacher_dashboard,
        school_tasks=school_tasks,
        school_directory=school_directory,
        support=support,
        rate_limiter=rate_limiter,
    )
