"""Async transaction boundary for database use cases."""

from __future__ import annotations

from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .crypto import FernetDataProtectionProvider
from .errors import ConfigurationError
from .repositories import (
    AccountRepository,
    AssessmentRepository,
    AuditRepository,
    AuthSessionStore,
    ConsentRepository,
    IdempotencyStore,
    ReviewRepository,
    SchoolMembershipRepository,
    SchoolOperationsRepository,
    SubjectRepository,
    SupportRepository,
)
from .school_post_assessment_jobs import SchoolPostAssessmentJobRepository
from .school_research_cat import SchoolResearchCatRepository


class SqlAlchemyUnitOfWork:
    """One AsyncSession and one transaction per application use case."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        protection: FernetDataProtectionProvider,
    ) -> None:
        self.session_factory = session_factory
        self.protection = protection
        self.session: AsyncSession | None = None
        self.accounts: AccountRepository | None = None
        self.subjects: SubjectRepository | None = None
        self.memberships: SchoolMembershipRepository | None = None
        self.school_operations: SchoolOperationsRepository | None = None
        self.consents: ConsentRepository | None = None
        self.auth_sessions: AuthSessionStore | None = None
        self.assessments: AssessmentRepository | None = None
        self.support: SupportRepository | None = None
        self.reviews: ReviewRepository | None = None
        self.idempotency: IdempotencyStore | None = None
        self.audit: AuditRepository | None = None
        self.post_assessment_jobs: SchoolPostAssessmentJobRepository | None = None
        self.research_cat: SchoolResearchCatRepository | None = None

    async def __aenter__(self) -> Self:
        self.session = self.session_factory()
        await self.session.begin()
        self.accounts = AccountRepository(self.session)
        self.subjects = SubjectRepository(self.session)
        self.memberships = SchoolMembershipRepository(self.session)
        self.school_operations = SchoolOperationsRepository(self.session)
        self.consents = ConsentRepository(self.session)
        self.auth_sessions = AuthSessionStore(self.session)
        self.assessments = AssessmentRepository(self.session, self.protection)
        self.support = SupportRepository(self.session, self.protection)
        self.reviews = ReviewRepository(self.session, self.protection)
        self.idempotency = IdempotencyStore(self.session)
        self.audit = AuditRepository(self.session)
        self.post_assessment_jobs = SchoolPostAssessmentJobRepository(self.session)
        self.research_cat = SchoolResearchCatRepository(self.session, self.protection)
        return self

    def _require_session(self) -> AsyncSession:
        if self.session is None:
            raise ConfigurationError("unit of work is not active")
        return self.session

    async def commit(self) -> None:
        await self._require_session().commit()

    async def rollback(self) -> None:
        await self._require_session().rollback()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        session = self._require_session()
        try:
            if exc_type is None:
                await session.commit()
            else:
                await session.rollback()
        finally:
            await session.close()
            self.session = None
