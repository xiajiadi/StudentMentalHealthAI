"""Application dependency graph for the Backend vertical slices."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
from smhai_backend.adapters.school_conversation_safety import (
    SchoolConversationSafetyPersistenceAdapter,
)
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
from smhai_backend.core.config import BackendSettings, ModuleClientSettings
from smhai_backend.core.rate_limit import InMemoryRateLimiter
from smhai_backend.domains.assessment.service import AssessmentService
from smhai_backend.domains.audit import AuditService
from smhai_backend.domains.auth.service import AuthService
from smhai_backend.domains.authorization import NativeAuthorizationProvider
from smhai_backend.domains.cat_assets.service import SchoolCatAssetService
from smhai_backend.domains.cat_management.service import SchoolCatManagementService
from smhai_backend.domains.conversations.service import (
    ConversationLanePolicy,
    IndependentConversationService,
)
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
from smhai_backend.integrations.student_research_safety import (
    SchoolResearchStudentSafetyClient,
)

_LOGGER = logging.getLogger(__name__)


def _shared_worker_concurrency_lock(
    post_assessment_worker_manager: SchoolPostAssessmentWorkerManager | None,
    research_education_worker_manager: Any | None = None,
    *,
    fallback: asyncio.Lock | None = None,
) -> asyncio.Lock:
    if post_assessment_worker_manager is not None:
        return post_assessment_worker_manager.concurrency_lock
    if research_education_worker_manager is not None:
        return research_education_worker_manager.concurrency_lock
    return fallback if fallback is not None else asyncio.Lock()


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
    school_conversation_safety: Any | None = None
    school_research_feedback: Any | None = None
    school_operations_audit: Any | None = None
    school_research_sources: Any | None = None
    school_research_education_candidates: Any | None = None
    school_research_programme_candidates: Any | None = None
    independent_conversations: IndependentConversationService | None = None
    school_research_student_conversations: IndependentConversationService | None = None
    school_research_student_safety: SafetyClient | None = None
    independent_rag: IndependentRagClient | None = None
    independent_llm: IndependentLLMRuntimeClient | None = None
    cat_management: SchoolCatManagementService | None = None
    cat_management_client: HttpCatManagementClient | None = None
    cat_assets: SchoolCatAssetService | None = None
    cat_assets_client: HttpCatAssetsClient | None = None
    cat_saved_simulation_client: HttpCatSavedSimulationClient | None = None
    post_assessment_worker_manager: SchoolPostAssessmentWorkerManager | None = None
    research_education_worker_manager: Any | None = None
    research_programme_worker_manager: Any | None = None
    research_programme_runtime_client: Any | None = None
    research_general_education_worker_manager: Any | None = None
    research_general_education_runtime_client: Any | None = None
    school_research: Any | None = None
    school_research_profiles: Any | None = None
    school_research_tasks: Any | None = None
    school_research_cohorts: Any | None = None
    school_research_discovery: Any | None = None
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
            if (
                self.school_research_student_safety is not None
                and self.school_research_student_safety is not self.safety
            ):
                await self.school_research_student_safety.start()
            if self.post_assessment_worker_manager is not None:
                await self.post_assessment_worker_manager.start()
            if self.research_education_worker_manager is not None:
                await self.research_education_worker_manager.start()
            if self.research_programme_worker_manager is not None:
                await self.research_programme_worker_manager.start()
            if self.research_general_education_worker_manager is not None:
                await self.research_general_education_worker_manager.start()
        except (Exception, asyncio.CancelledError):
            research_shutdown_failed = await self._close_research_process()
            research_general_education_shutdown_failed = False
            if self.research_general_education_worker_manager is not None:
                try:
                    await self.research_general_education_worker_manager.close()
                except Exception:
                    research_general_education_shutdown_failed = True
                    _LOGGER.error(
                        "general-education worker cleanup failed during startup",
                        extra={"failure_code": "RESEARCH_GENERAL_EDUCATION_WORKER_CLEANUP_FAILURE"},
                    )
            research_programme_shutdown_failed = False
            if self.research_programme_worker_manager is not None:
                try:
                    await self.research_programme_worker_manager.close()
                except Exception:
                    research_programme_shutdown_failed = True
                    _LOGGER.error(
                        "staff programme worker cleanup failed during startup",
                        extra={"failure_code": "RESEARCH_PROGRAMME_WORKER_CLEANUP_FAILURE"},
                    )
            research_education_shutdown_failed = False
            if self.research_education_worker_manager is not None:
                try:
                    await self.research_education_worker_manager.close()
                except Exception:
                    research_education_shutdown_failed = True
                    _LOGGER.error(
                        "research education worker cleanup failed during startup",
                        extra={"failure_code": "RESEARCH_EDUCATION_WORKER_CLEANUP_FAILURE"},
                    )
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
                and not worker_shutdown_failed
                and not research_education_shutdown_failed
                and not research_programme_shutdown_failed
                and not research_general_education_shutdown_failed
                and not research_shutdown_failed
            ):
                await self.persistence.close()
            raise

    async def close(self) -> None:
        research_shutdown_failed = await self._close_research_process()
        research_general_education_shutdown_failed = False
        if self.research_general_education_worker_manager is not None:
            try:
                await self.research_general_education_worker_manager.close()
            except Exception:
                research_general_education_shutdown_failed = True
                _LOGGER.error(
                    "general-education worker cleanup failed during shutdown",
                    extra={"failure_code": "RESEARCH_GENERAL_EDUCATION_WORKER_CLEANUP_FAILURE"},
                )
        research_programme_shutdown_failed = False
        if self.research_programme_worker_manager is not None:
            try:
                await self.research_programme_worker_manager.close()
            except Exception:
                research_programme_shutdown_failed = True
                _LOGGER.error(
                    "staff programme worker cleanup failed during shutdown",
                    extra={"failure_code": "RESEARCH_PROGRAMME_WORKER_CLEANUP_FAILURE"},
                )
        research_education_shutdown_failed = False
        if self.research_education_worker_manager is not None:
            try:
                await self.research_education_worker_manager.close()
            except Exception:
                research_education_shutdown_failed = True
                _LOGGER.error(
                    "research education worker cleanup failed during shutdown",
                    extra={"failure_code": "RESEARCH_EDUCATION_WORKER_CLEANUP_FAILURE"},
                )
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
            and not worker_shutdown_failed
            and not research_education_shutdown_failed
            and not research_programme_shutdown_failed
            and not research_general_education_shutdown_failed
            and not research_shutdown_failed
        ):
            await self.persistence.close()
        if research_shutdown_failed:
            raise RuntimeError("research CAT process shutdown did not complete")
        if research_education_shutdown_failed:
            raise RuntimeError("research education worker shutdown did not complete")
        if research_programme_shutdown_failed:
            raise RuntimeError("staff programme worker shutdown did not complete")
        if research_general_education_shutdown_failed:
            raise RuntimeError("general-education worker shutdown did not complete")
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
        seen: set[int] = set()
        clients = (
            ("safety", self.safety),
            ("school_research_student_safety", self.school_research_student_safety),
            ("cat", self.cat),
            ("cat_management", self.cat_management_client),
            ("cat_assets", self.cat_assets_client),
            ("cat_saved_simulation", self.cat_saved_simulation_client),
            ("rag", self.rag),
            ("llm", self.llm),
            ("independent_rag", self.independent_rag),
            ("independent_llm", self.independent_llm),
            ("research_programme_runtime", self.research_programme_runtime_client),
            ("research_general_education_runtime", self.research_general_education_runtime_client),
        )
        for name, client in clients:
            if client is None or id(client) in seen:
                continue
            seen.add(id(client))
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
        statuses["research_education_worker"] = (
            self.research_education_worker_manager.dependency_status()
            if self.research_education_worker_manager is not None
            else {"status": "DISABLED", "integration": "RESEARCH_OUTBOX"}
        )
        statuses["research_programme_worker"] = (
            self.research_programme_worker_manager.dependency_status()
            if self.research_programme_worker_manager is not None
            else {"status": "DISABLED", "integration": "RESEARCH_STAFF_PROGRAMME_OUTBOX"}
        )
        if self.research_general_education_worker_manager is not None:
            statuses["research_general_education_draft_worker"] = (
                self.research_general_education_worker_manager.dependency_status()
            )
        else:
            draft_settings = self.settings.research_general_education_draft
            worker_status = (
                "DISABLED"
                if not draft_settings.enabled or not draft_settings.worker_enabled
                else "UNAVAILABLE"
            )
            statuses["research_general_education_draft_worker"] = {
                "status": worker_status,
                "integration": "RESEARCH_GENERAL_EDUCATION_DRAFT_OUTBOX",
            }
        return statuses


def build_container(
    settings: BackendSettings | None = None,
) -> BackendContainer:
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
        build_school_research_cohorts_service,
        build_school_research_discovery_service,
        build_school_research_profiles_service,
        build_school_research_service,
        build_school_research_tasks_service,
    )

    school_research = build_school_research_service(settings, persistence)
    school_research_profiles = build_school_research_profiles_service(settings, persistence)
    school_research_tasks = build_school_research_tasks_service(settings, persistence)
    school_research_cohorts = build_school_research_cohorts_service(settings, school_research_tasks)
    school_research_discovery = build_school_research_discovery_service(settings, persistence)
    school_operations_audit = None
    if persistence is not None:
        from smhai_backend.adapters.school_operations_audit import (
            SchoolOperationsAuditPersistenceAdapter,
        )
        from smhai_backend.domains.school_operations_audit.service import (
            SchoolOperationsAuditService,
        )

        school_operations_audit = SchoolOperationsAuditService(
            persistence=SchoolOperationsAuditPersistenceAdapter(persistence)
        )
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
    from smhai_backend.domains.school_conversation_safety.service import (
        SchoolConversationSafetyService,
    )

    school_conversation_safety = SchoolConversationSafetyService(
        persistence=(
            SchoolConversationSafetyPersistenceAdapter(persistence)
            if persistence is not None and settings.identity_profile == "school_tenant"
            else None
        )
    )
    school_research_feedback = None
    school_research_feedback_adapter = None
    school_research_education_candidate_adapter = None
    school_research_education_candidates = None
    school_research_programme_candidates = None
    school_research_programme_candidate_adapter = None
    programme_study_policy = None
    programme_job_policy_sha256 = None
    if (
        persistence is not None
        and settings.identity_profile == "school_tenant"
        and settings.school_research_enabled
        and settings.environment != "production"
    ):
        from smhai_backend.adapters.school_research_feedback import (
            SchoolResearchFeedbackPersistenceAdapter,
        )
        from smhai_backend.domains.school_research.bootstrap import (
            build_school_research_study_policy,
        )
        from smhai_backend.domains.school_research_feedback.service import (
            SchoolResearchFeedbackService,
        )

        programme_study_policy = build_school_research_study_policy(settings)
        if settings.research_programme_worker.enabled:
            school_study_ref = getattr(programme_study_policy, "study_ref", None)
            if type(school_study_ref) is not str or not school_study_ref:
                raise ValueError(
                    "staff programme worker requires a pinned school/source study pair"
                )
            programme_job_policy_sha256 = settings.research_programme_job_policy_sha256_for(
                school_study_ref=school_study_ref
            )
            if programme_job_policy_sha256 is None:
                raise ValueError(
                    "staff programme worker requires a pinned school/source study pair"
                )

        school_research_feedback_adapter = SchoolResearchFeedbackPersistenceAdapter(
            persistence, study_use_policy=programme_study_policy
        )
        school_research_feedback = SchoolResearchFeedbackService(
            persistence=school_research_feedback_adapter
        )
        from smhai_backend.adapters.school_research_programme_candidates import (
            SchoolResearchProgrammeCandidatePersistenceAdapter,
        )
        from smhai_backend.domains.school_research_programme_candidates.service import (
            SchoolResearchProgrammeCandidateService,
        )

        programme_settings = settings.research_programme_worker
        school_research_programme_candidate_adapter = (
            SchoolResearchProgrammeCandidatePersistenceAdapter(
                persistence,
                study_use_policy=programme_study_policy,
                study_use_policy_sha256=settings.school_research_study_use_sha256,
                enabled=settings.school_research_enabled
                and settings.environment != "production",
                expected_source_manifest_sha256=programme_settings.package_manifest_sha256,
                expected_processor_policy_sha256=programme_job_policy_sha256,
                expected_model_ref=programme_settings.model_ref,
                expected_model_digest_sha256=programme_settings.model_digest_sha256,
                expected_prompt_ref=programme_settings.prompt_ref,
                expected_prompt_version=programme_settings.prompt_version,
            )
        )
        school_research_programme_candidate_adapter.configure_generation(
            enabled=programme_settings.enabled,
            processor_policy_sha256=programme_job_policy_sha256,
        )
        school_research_programme_candidates = SchoolResearchProgrammeCandidateService(
            persistence=school_research_programme_candidate_adapter
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
    research_worker_lock = _shared_worker_concurrency_lock(post_assessment_worker_manager)
    research_education_worker_manager = None
    if settings.research_education_worker_enabled and persistence is not None:
        from smhai_backend.adapters.school_research_education import (
            SchoolResearchEducationPersistenceAdapter,
            SchoolResearchEducationWorkerManager,
        )
        from smhai_backend.domains.school_research.bootstrap import (
            build_school_research_study_policy,
        )

        study_use_policy = build_school_research_study_policy(settings)
        research_education_worker_manager = SchoolResearchEducationWorkerManager(
            SchoolResearchEducationPersistenceAdapter(
                persistence, study_use_policy=study_use_policy
            ),
            settings=settings.research_education_worker,
            concurrency_lock=research_worker_lock,
        )
    research_programme_worker_manager = None
    research_programme_runtime_client = None
    if settings.research_programme_worker.enabled and persistence is not None:
        from rag_engine.research import ResearchOnlyRetriever

        from smhai_backend.domains.research_programme_generation.service import (
            ResearchProgrammeGenerationService,
        )
        from smhai_backend.domains.school_research_programme_generation.worker import (
            ResearchProgrammeWorkerManager,
        )
        from smhai_backend.integrations.research_programme import (
            HttpResearchProgrammeRuntimeClient,
        )
        programme_settings = settings.research_programme_worker
        retriever = ResearchOnlyRetriever.from_manifest(
            Path(programme_settings.package_manifest_file),
            expected_manifest_sha256=programme_settings.package_manifest_sha256,
        )
        research_programme_runtime_client = HttpResearchProgrammeRuntimeClient(
            settings.research_programme_runtime
        )
        generation_service = ResearchProgrammeGenerationService(
            safety=safety,
            retriever=retriever,
            runtime=research_programme_runtime_client,
            expected_manifest_sha256=programme_settings.package_manifest_sha256,
        )
        concurrency_lock = _shared_worker_concurrency_lock(
            post_assessment_worker_manager,
            research_education_worker_manager,
            fallback=research_worker_lock,
        )
        study_policy = programme_study_policy
        if study_policy is None or programme_job_policy_sha256 is None:
            raise ValueError("staff programme worker requires a pinned study-use policy")
        research_programme_worker_manager = ResearchProgrammeWorkerManager(
            persistence=persistence,
            persistence_adapter=school_research_programme_candidate_adapter,
            generation_service=generation_service,
            settings=programme_settings,
            concurrency_lock=concurrency_lock,
            study_policy_sha256=settings.school_research_study_use_sha256,
            school_study_ref=study_policy.study_ref,
            processor_policy_sha256=programme_job_policy_sha256,
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
    school_research_student_conversations = None
    active_research_student_safety = None
    research_student_package = None
    school_research_sources = None
    student_rag = None
    student_lane_settings = settings.school_research_student_conversation
    if student_lane_settings.enabled:
        if persistence is None:
            raise ValueError("school research student conversations require persistence")
        from rag_engine.research.student_education import (
            SchoolStudentEducationRetriever,
            SchoolStudentPackageError,
            load_school_student_package,
        )

        from smhai_backend.integrations.student_research import (
            SchoolResearchStudentRagAdapter,
        )

        try:
            package = load_school_student_package(
                Path(student_lane_settings.manifest_file),
                expected_manifest_sha256=student_lane_settings.manifest_sha256,
                expected_study_ref=student_lane_settings.study_ref,
            )
        except SchoolStudentPackageError as exc:
            if exc.code != "STUDENT_PACKAGE_EXPIRED":
                raise
            package = None
        if package is not None:
            research_student_package = package
            from smhai_backend.domains.school_research_sources.service import (
                SchoolResearchSourcesService,
            )

            school_research_sources = SchoolResearchSourcesService(
                package=package,
                expected_school_id=student_lane_settings.school_id,
                expected_manifest_sha256=student_lane_settings.manifest_sha256,
                expected_study_ref=student_lane_settings.study_ref,
            )
            if independent_llm is None:
                independent_llm = IndependentLLMRuntimeClient(settings.llm)
            active_research_student_safety = SchoolResearchStudentSafetyClient(
                standard_safety=safety,
                settings=ModuleClientSettings(
                    mode="http",
                    base_url=student_lane_settings.safety_base_url,
                ),
                package=package,
                expected_manifest_sha256=student_lane_settings.manifest_sha256,
                expected_package_id=package.package_id,
                expected_study_ref=student_lane_settings.study_ref,
            )
            student_retriever = SchoolStudentEducationRetriever(package)
            student_rag = SchoolResearchStudentRagAdapter(
                student_retriever,
                expected_manifest_sha256=student_lane_settings.manifest_sha256,
                expected_package_id=package.package_id,
                expected_study_ref=student_lane_settings.study_ref,
            )
            student_lane_policy = ConversationLanePolicy.school_research_student(
                school_id=student_lane_settings.school_id,
                study_ref=student_lane_settings.study_ref,
                package_id=package.package_id,
                manifest_sha256=student_lane_settings.manifest_sha256,
                valid_through=package.valid_through,
            )
            school_research_student_conversations = IndependentConversationService(
                persistence=SchoolConversationsPersistenceAdapter(
                    persistence, target_role="student_research"
                ),
                safety=active_research_student_safety,
                rag=student_rag,
                llm=independent_llm,
                lane_policy=student_lane_policy,
            )
    research_general_education_worker_manager = None
    research_general_education_runtime_client = None
    education_draft_settings = settings.research_general_education_draft
    if education_draft_settings.enabled and persistence is not None:
        if (
            research_student_package is not None
            and student_rag is not None
            and active_research_student_safety is not None
            and programme_study_policy is not None
        ):
            from smhai_backend.adapters.school_research_education_candidates import (
                SchoolResearchEducationCandidatePersistenceAdapter,
            )
            from smhai_backend.domains.research_general_education.service import (
                ResearchGeneralEducationDraftService,
                ResearchGeneralEducationPolicyPins,
                source_cards_from_package,
            )
            from smhai_backend.domains.school_research_education_candidates.service import (
                SchoolResearchEducationCandidateService,
            )
            from smhai_backend.domains.school_research_general_education_generation.manager import (
                ResearchGeneralEducationWorkerManager,
            )
            from smhai_backend.integrations.research_general_education import (
                ResearchGeneralEducationRuntimeClient,
            )

            package = research_student_package
            if datetime.now(UTC) <= package.valid_through:
                policy_pins = ResearchGeneralEducationPolicyPins(
                    policy_hash=education_draft_settings.policy_hash,
                    source_package_ref=package.package_id,
                    source_study_ref=education_draft_settings.source_study_ref,
                    source_manifest_sha256=education_draft_settings.source_manifest_sha256,
                )
                source_cards = source_cards_from_package(package, policy_pins=policy_pins)
                research_general_education_runtime_client = (
                    ResearchGeneralEducationRuntimeClient(settings.research_programme_runtime)
                )
                generation_service = ResearchGeneralEducationDraftService(
                    safety=active_research_student_safety,
                    retriever=student_rag,
                    runtime=research_general_education_runtime_client,
                    policy_pins=policy_pins,
                    source_cards=source_cards,
                )
                school_research_education_candidate_adapter = (
                    SchoolResearchEducationCandidatePersistenceAdapter(
                        persistence,
                        enabled=True,
                        school_id=education_draft_settings.school_id,
                        school_study_ref=education_draft_settings.school_study_ref,
                        policy_hash=education_draft_settings.policy_hash,
                        source_manifest_sha256=education_draft_settings.source_manifest_sha256,
                        source_package_ref=package.package_id,
                        source_study_ref=education_draft_settings.source_study_ref,
                        study_use_policy=programme_study_policy,
                        input_review_continuation_enabled=(
                            education_draft_settings.input_review_continuation_enabled
                        ),
                        source_cards=source_cards,
                        source_valid_through=package.valid_through,
                    )
                )
                school_research_education_candidates = (
                    SchoolResearchEducationCandidateService(
                        persistence=school_research_education_candidate_adapter
                    )
                )
                if school_research_feedback_adapter is not None:
                    school_research_feedback_adapter.education_candidate_validator = (
                        school_research_education_candidate_adapter
                        .validate_feedback_candidate_in_uow
                    )
                    school_research_feedback_adapter.education_candidate_lineage_validator = (
                        school_research_education_candidate_adapter
                        .verify_candidate_input_lineage_in_uow
                    )
                concurrency_lock = (
                    research_programme_worker_manager.concurrency_lock
                    if research_programme_worker_manager is not None
                    else _shared_worker_concurrency_lock(
                        post_assessment_worker_manager,
                        research_education_worker_manager,
                        fallback=research_worker_lock,
                    )
                )
                if education_draft_settings.worker_enabled:
                    research_general_education_worker_manager = (
                        ResearchGeneralEducationWorkerManager(
                            persistence=persistence,
                            persistence_adapter=school_research_education_candidate_adapter,
                            generation_service=generation_service,
                            settings=education_draft_settings,
                            concurrency_lock=concurrency_lock,
                            source_valid_through=package.valid_through,
                        )
                    )
            else:
                _LOGGER.warning(
                    "general-education worker disabled because its source package expired",
                    extra={"failure_code": "RESEARCH_GENERAL_EDUCATION_SOURCE_EXPIRED"},
                )
        else:
            _LOGGER.warning(
                "general-education worker disabled because pinned student sources are unavailable",
                extra={"failure_code": "RESEARCH_GENERAL_EDUCATION_SOURCE_UNAVAILABLE"},
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
        school_research_tasks=school_research_tasks,
        school_research_cohorts=school_research_cohorts,
        school_research_discovery=school_research_discovery,
        school_research_process_factory=research_process_factory,
        professional_reviews=professional_reviews,
        school_feedback=school_feedback,
        school_conversation_safety=school_conversation_safety,
        school_research_feedback=school_research_feedback,
        school_operations_audit=school_operations_audit,
        school_research_sources=school_research_sources,
        school_research_education_candidates=school_research_education_candidates,
        school_research_programme_candidates=school_research_programme_candidates,
        cat_management=cat_management,
        cat_management_client=cat_management_client,
        cat_assets=cat_assets,
        cat_assets_client=cat_assets_client,
        cat_saved_simulation_client=cat_saved_simulation_client,
        post_assessment_worker_manager=post_assessment_worker_manager,
        research_education_worker_manager=research_education_worker_manager,
        research_programme_worker_manager=research_programme_worker_manager,
        research_programme_runtime_client=research_programme_runtime_client,
        research_general_education_worker_manager=research_general_education_worker_manager,
        research_general_education_runtime_client=research_general_education_runtime_client,
        independent_conversations=independent_conversations,
        school_research_student_conversations=school_research_student_conversations,
        school_research_student_safety=active_research_student_safety,
        independent_rag=independent_rag,
        independent_llm=independent_llm,
        support=support,
        rate_limiter=rate_limiter,
    )
