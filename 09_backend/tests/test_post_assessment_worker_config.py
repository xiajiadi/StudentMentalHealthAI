import pytest
from pydantic import ValidationError

from smhai_backend.core.config import BackendSettings, PostAssessmentWorkerSettings


def test_worker_defaults_on_only_for_persistent_school_tenant():
    legacy = BackendSettings(_env_file=None)
    school = BackendSettings(
        _env_file=None,
        identity_profile="school_tenant",
        persistence_mode="mysql",
        school_csrf_secret="a" * 64,
    )
    school_memory = BackendSettings(
        _env_file=None,
        identity_profile="school_tenant",
        persistence_mode="memory",
        school_csrf_secret="a" * 64,
    )

    assert legacy.post_assessment_worker_enabled is False
    assert school.post_assessment_worker_enabled is True
    assert school_memory.post_assessment_worker_enabled is False
    assert school.post_assessment_worker.policy_version == "NO_PERSONALIZED_POLICY_V1"


@pytest.mark.parametrize(
    "values",
    [
        {"enabled": True, "heartbeat_interval_seconds": 60, "lease_seconds": 60},
        {"enabled": True, "poll_interval_seconds": 0},
        {"enabled": True, "poll_interval_seconds": 0.001},
        {"enabled": True, "max_attempts": 21},
        {"enabled": "yes"},
        {"enabled": True, "unrecognized": True},
        {"enabled": True, "policy_version": "contains whitespace"},
        {"poll_interval_seconds": True},
        {"lease_seconds": True},
        {"heartbeat_interval_seconds": True},
        {"max_attempts": True},
        {"shutdown_drain_seconds": True},
        {"poll_interval_seconds": "1.0"},
        {"lease_seconds": "60"},
        {"poll_interval_seconds": float("nan")},
        {"poll_interval_seconds": float("inf")},
        {"heartbeat_interval_seconds": float("-inf")},
        {"shutdown_drain_seconds": float("nan")},
    ],
)
def test_worker_settings_reject_invalid_values(values):
    with pytest.raises(ValidationError):
        PostAssessmentWorkerSettings.model_validate(values)


def test_explicit_enablement_rejects_legacy_and_memory_profiles():
    with pytest.raises(ValidationError, match="requires school_tenant MySQL"):
        BackendSettings(_env_file=None, post_assessment_worker={"enabled": True})
    with pytest.raises(ValidationError, match="requires school_tenant MySQL"):
        BackendSettings(
            _env_file=None,
            identity_profile="school_tenant",
            persistence_mode="memory",
            school_csrf_secret="a" * 64,
            post_assessment_worker={"enabled": True},
        )
