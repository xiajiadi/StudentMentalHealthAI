"""Application dependency graph for the Backend vertical slices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
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
from smhai_backend.adapters.school_cat_assets import SchoolCatAssetsPersistenceAdapter
from smhai_backend.adapters.school_cat_management import SchoolCatManagementPersistenceAdapter
from smhai_backend.adapters.school_conversations import SchoolConversationsPersistenceAdapter
from smhai_backend.adapters.school_directory import SchoolDirectoryPersistenceAdapter
from smhai_backend.adapters.school_feedback import SchoolFeedbackPersistenceAdapter
from smhai_backend.adapters.school_post_assessment import (
    SchoolPostAssessmentPersistenceAdapter,
    SchoolPostAssessmentWorkerManager,
)
from smhai_backend.adapters.school_professional_reviews import (
    SchoolProfessionalReviewPersistenceAdapter,
)
from smhai_backend.core.async_utils import maybe_await
from smhai_backend.core.config import BackendSettings
from smhai_backend.core.rate_limit import InMemoryRateLimiter
from smhai_backend.domains.assessment.service import AssessmentService
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.auth.service import AuthService
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.cat_assets.service import SchoolCatAssetService
from smhai_backend.domains.cat_management.service import SchoolCatManagementService
from smhai_backend.domains.conversations.service import IndependentConversationService
from smhai_backend.domains.professional_reviews.service import SchoolProfessionalReviewService
from smhai_backend.domains.school_directory.service import SchoolDirectoryService
from smhai_backend.domains.school_feedback.service import SchoolFeedbackService
from smhai_backend.domains.school_tasks.service import SchoolTaskService
from smhai_backend.domains.support.service import SupportOrchestrator
from smhai_backend.domains.teacher.service import TeacherDashboardService
from smhai_backend.integrations.cat import ContractFakeCatClient, HttpCatClient
from smhai_backend.integrations.cat_assets import (
    HttpCatAssetsClient,
    HttpCatSavedSimulationClient,
)
from smhai_backend.integrations.cat_management import HttpCatManagementClient
from smhai_backend.integrations.independent import IndependentLLMRuntimeClient, IndependentRagClient
from smhai_backend.integrations.llm import ContractFakeLLMRuntimeClient, HttpLLMRuntimeClient
from smhai_backend.integrations.rag import ContractFakeRagClient, HttpRagClient
from smhai_backend.integrations.safety import (
    ContractFakeSafetyClient,
    HttpSafetyClient,
    SafetyClient,
)

_LOGGER = logging.getLogger(__name__)


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
    professional_reviews: SchoolProfessionalReviewService | None = None
    school_feedback: SchoolFeedbackService | None = None
    independent_conversations: IndependentConversationService | None = None
    independent_rag: IndependentRagClient | None = None
    independent_llm: IndependentLLMRuntimeClient | None = None
    cat_management: SchoolCatManagementService | None = None
    cat_management_client: HttpCatManagementClient | None = None
    cat_assets: SchoolCatAssetService | None = None
    cat_assets_client: HttpCatAssetsClient | None = None
    cat_saved_simulation_client: HttpCatSavedSimulationClient | None = None
    post_assessment_worker_manager: SchoolPostAssessmentWorkerManager | None = None
    school_research: Any | None = None
    school_research_profiles: Any | None = None
    school_research_process: Any | None = None
    school_research_process_factory: Callable[[], Any] | None = None

    async def start(self) -> None:
        try:
            if self.persistence is not None:
                await self.persistence.start()
            if self.school_research_process_factory is not None:
                self.school_research_process = self.school_research_process_factory()
                await self.school_research_process.start()
            await self.safety.start()
            if self.post_assessment_worker_manager is not None:
                await self.post_assessment_worker_manager.start()
        except (Exception, asyncio.CancelledError):
            research_shutdown_failed = await self._close_research_process()
            worker_shutdown_failed = False
            if self.post_assessment_worker_manager is not None:
                try:
                    await self.post_assessment_worker_manager.close()
                except Exception:
                    worker_shutdown_failed = True
                    _LOGGER.error(
                        "post-assessment worker cleanup failed during startup",
                        extra={"failure_code": "WORKER_CLEANUP_FAILURE"},
                    )
            await self._close_clients()
            if (
                self.persistence is not None
                and not worker_shutdown_failed and not research_shutdown_failed
            ):
                await self.persistence.close()
            raise

    async def close(self) -> None:
        research_shutdown_failed = await self._close_research_process()
        worker_shutdown_failed = False
        if self.post_assessment_worker_manager is not None:
            try:
                await self.post_assessment_worker_manager.close()
            except Exception:
                worker_shutdown_failed = True
                _LOGGER.error(
                    "post-assessment worker cleanup failed during shutdown",
                    extra={"failure_code": "WORKER_CLEANUP_FAILURE"},
                )
        clients_failed = await self._close_clients()
        if (
            self.persistence is not None
            and not worker_shutdown_failed and not research_shutdown_failed
        ):
            await self.persistence.close()
        if research_shutdown_failed:
            raise RuntimeError("research CAT process shutdown did not complete")
        if worker_shutdown_failed:
            raise RuntimeError("post-assessment worker shutdown did not complete")
        if clients_failed:
            raise RuntimeError("Backend dependency shutdown did not complete")

    async def _close_research_process(self) -> bool:
        if self.school_research_process is None:
            return False
        try:
            await self.school_research_process.close()
        except Exception:
            _LOGGER.error(
                "research CAT process cleanup failed",
                extra={"failure_code": "RESEARCH_PROCESS_CLEANUP_FAILURE"},
            )
            return True
        return False

    async def research_process_ready(self) -> bool:
        if self.school_research_process_factory is None:
            return True
        if self.school_research_process is None:
            return False
        try:
            return (await self.school_research_process.health()).status == "READY"
        except Exception:
            return False

    async def _close_clients(self) -> bool:
        failures: list[str] = []
        clients = (
            ("safety", self.safety),
            ("cat", self.cat),
            ("cat_management", self.cat_management_client),
            ("cat_assets", self.cat_assets_client),
            ("cat_saved_simulation", self.cat_saved_simulation_client),
            ("rag", self.rag),
            ("llm", self.llm),
            ("independent_rag", self.independent_rag),
            ("independent_llm", self.independent_llm),
        )
        for name, client in clients:
            if client is None:
                continue
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await maybe_await(close())
                except Exception:
                    failures.append(name)
        if failures:
            _LOGGER.error(
                "Backend dependency cleanup failed",
                extra={
                    "failure_code": "CLIENT_CLOSE_FAILURE",
                    "dependencies": failures,
                },
            )
        return bool(failures)

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
        statuses["post_assessment_worker"] = (
            self.post_assessment_worker_manager.dependency_status()
            if self.post_assessment_worker_manager is not None
            else {"status": "DISABLED", "integration": "LOCAL_OUTBOX"}
        )
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
    from smhai_backend.domains.school_research.bootstrap import (
        build_school_research_profiles_service,
        build_school_research_service,
    )

    school_research = build_school_research_service(settings, persistence)
    school_research_profiles = build_school_research_profiles_service(settings, persistence)
    from smhai_backend.domains.school_research.lifecycle import (
        build_school_research_process_factory,
    )

    research_process_factory = build_school_research_process_factory(settings, persistence)
    audit = AuditService(audits)
    auth = AuthService(
        users=users,
        sessions=sessions,
        auth_settings=settings.auth,
        audit=audit,
    )
    cat = HttpCatClient(settings.cat) if settings.cat.mode == "http" else ContractFakeCatClient()
    cat_management_client = (
        HttpCatManagementClient(settings.cat) if settings.cat.mode == "http" else None
    )
    cat_assets_client = HttpCatAssetsClient(settings.cat) if settings.cat.mode == "http" else None
    cat_saved_simulation_client = (
        HttpCatSavedSimulationClient(settings.cat) if settings.cat.mode == "http" else None
    )
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
    professional_reviews = SchoolProfessionalReviewService(
        persistence=SchoolProfessionalReviewPersistenceAdapter(persistence)
        if persistence is not None and settings.identity_profile == "school_tenant"
        else None
    )
    school_feedback = SchoolFeedbackService(
        persistence=SchoolFeedbackPersistenceAdapter(persistence)
        if persistence is not None and settings.identity_profile == "school_tenant"
        else None
    )
    cat_management = SchoolCatManagementService(
        persistence=(
            SchoolCatManagementPersistenceAdapter(persistence, cat_management_client)
            if persistence is not None and settings.identity_profile == "school_tenant"
            else None
        )
    )
    cat_assets = SchoolCatAssetService(
        persistence=(
            SchoolCatAssetsPersistenceAdapter(
                persistence, cat_assets_client, cat_saved_simulation_client
            )
            if persistence is not None and settings.identity_profile == "school_tenant"
            else None
        )
    )
    post_assessment_worker_manager = (
        SchoolPostAssessmentWorkerManager(
            SchoolPostAssessmentPersistenceAdapter(persistence),
            settings.post_assessment_worker,
        )
        if settings.post_assessment_worker_enabled and persistence is not None
        else None
    )
    independent_rag = independent_llm = independent_conversations = None
    if (
        persistence is not None
        and settings.identity_profile == "school_tenant"
        and settings.rag.mode == "http"
        and settings.llm.mode == "http"
        and settings.safety.mode == "http"
    ):
        if settings.safety.base_url != "http://127.0.0.1:8190":
            raise ValueError("independent conversation Safety must use the local school endpoint")
        independent_rag = IndependentRagClient(settings.rag)
        independent_llm = IndependentLLMRuntimeClient(settings.llm)
        independent_conversations = IndependentConversationService(
            persistence=SchoolConversationsPersistenceAdapter(persistence),
            safety=safety,
            rag=independent_rag,
            llm=independent_llm,
        )
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
        school_research=school_research,
        school_research_profiles=school_research_profiles,
        school_research_process_factory=research_process_factory,
        professional_reviews=professional_reviews,
        school_feedback=school_feedback,
        cat_management=cat_management,
        cat_management_client=cat_management_client,
        cat_assets=cat_assets,
        cat_assets_client=cat_assets_client,
        cat_saved_simulation_client=cat_saved_simulation_client,
        post_assessment_worker_manager=post_assessment_worker_manager,
        independent_conversations=independent_conversations,
        independent_rag=independent_rag,
        independent_llm=independent_llm,
        support=support,
        rate_limiter=rate_limiter,
    )
