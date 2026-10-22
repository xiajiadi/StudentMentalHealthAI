"""Database persistence foundation for StudentMentalHealthAI."""

from .base import Base
from .config import DatabaseSettings, create_engine, create_session_factory
from .crypto import (
    DevLocalKeyProvider,
    EncryptedPayload,
    FernetDataProtectionProvider,
    KeyProvider,
    LinuxSystemdCredentialKeyProvider,
    MappingKeyProvider,
    WindowsDpapiKeyProvider,
)
from .models import (
    SchoolCatActivation,
    SchoolCatItemBank,
    SchoolCatItemBankVersion,
    SchoolCatPlan,
    SchoolCatPlanVersion,
    SchoolCatSessionBinding,
    SchoolCatTaskBinding,
)
from .provenance import (
    PROVENANCE_REGISTRY,
    SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF,
    SYNTHETIC_SCHOOL_TEST_PROVENANCE_REF,
)
from .school_conversation_safety import (
    ConversationSafetyCaseDTO,
    ConversationSafetyEventDTO,
    SchoolConversationSafetyError,
    SchoolConversationSafetyRepository,
)
from .school_research_cohorts import (
    ResearchCohortCaseAssignment,
    ResearchCohortErrorCode,
    ResearchCohortMetadata,
    ResearchCohortRepositoryError,
    SchoolResearchCohortRepository,
)
from .school_research_education_input_reviews import (
    ResearchEducationInputReviewDTO,
    ResearchEducationInputReviewError,
    ResearchEducationInputReviewEvidence,
    ResearchEducationInputReviewScope,
    SchoolResearchEducationInputReviewRepository,
)
from .school_research_education_jobs import (
    ResearchEducationJobClaim,
    ResearchEducationJobDTO,
    ResearchEducationJobErrorCode,
    SchoolResearchEducationJobRepository,
)
from .school_research_programme_candidates import (
    ResearchProgrammeCandidateDTO,
    ResearchProgrammeCandidateError,
    ResearchProgrammeCandidateScope,
    SchoolResearchProgrammeCandidateRepository,
)
from .school_research_review_feedback import (
    ResearchFeedbackEventDTO,
    ResearchFeedbackRecordDTO,
    ResearchReviewCaseDTO,
    ResearchReviewEventDTO,
    ResearchReviewFeedbackError,
    ResearchSessionScope,
    SchoolResearchFeedbackRepository,
    SchoolResearchReviewRepository,
)
from .school_seed import (
    SCHOOL_SEED_SLOTS,
    SYNTHETIC_SCHOOL_RECIPES,
    PasswordHasher,
    SyntheticSchoolSeedConflict,
    SyntheticSchoolSeedError,
    SyntheticSchoolSeedResult,
    seed_synthetic_school_contexts,
)
from .unit_of_work import SqlAlchemyUnitOfWork

__all__ = [
    "Base",
    "DatabaseSettings",
    "DevLocalKeyProvider",
    "EncryptedPayload",
    "FernetDataProtectionProvider",
    "KeyProvider",
    "LinuxSystemdCredentialKeyProvider",
    "MappingKeyProvider",
    "PasswordHasher",
    "PROVENANCE_REGISTRY",
    "SCHOOL_SEED_SLOTS",
    "SqlAlchemyUnitOfWork",
    "SchoolCatActivation",
    "SchoolCatItemBank",
    "SchoolCatItemBankVersion",
    "SchoolCatPlan",
    "SchoolCatPlanVersion",
    "SchoolCatSessionBinding",
    "SchoolCatTaskBinding",
    "SyntheticSchoolSeedConflict",
    "SyntheticSchoolSeedError",
    "SyntheticSchoolSeedResult",
    "SYNTHETIC_SCHOOL_RECIPES",
    "SYNTHETIC_SCHOOL_SEED_PROVENANCE_REF",
    "SYNTHETIC_SCHOOL_TEST_PROVENANCE_REF",
    "ResearchCohortCaseAssignment",
    "ResearchCohortErrorCode",
    "ResearchCohortMetadata",
    "ResearchCohortRepositoryError",
    "SchoolResearchCohortRepository",
    "ResearchEducationJobClaim",
    "ResearchEducationJobDTO",
    "ResearchEducationJobErrorCode",
    "SchoolResearchEducationJobRepository",
    "ResearchEducationInputReviewDTO",
    "ResearchEducationInputReviewError",
    "ResearchEducationInputReviewEvidence",
    "ResearchEducationInputReviewScope",
    "SchoolResearchEducationInputReviewRepository",
    "ResearchFeedbackEventDTO",
    "ResearchFeedbackRecordDTO",
    "ResearchReviewCaseDTO",
    "ResearchReviewEventDTO",
    "ResearchReviewFeedbackError",
    "ResearchSessionScope",
    "SchoolResearchFeedbackRepository",
    "SchoolResearchReviewRepository",
    "ResearchProgrammeCandidateDTO",
    "ResearchProgrammeCandidateError",
    "ResearchProgrammeCandidateScope",
    "SchoolResearchProgrammeCandidateRepository",
    "ConversationSafetyCaseDTO",
    "ConversationSafetyEventDTO",
    "SchoolConversationSafetyError",
    "SchoolConversationSafetyRepository",
    "WindowsDpapiKeyProvider",
    "create_engine",
    "create_session_factory",
    "seed_synthetic_school_contexts",
]
