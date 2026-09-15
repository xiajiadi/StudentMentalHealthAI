from __future__ import annotations

import ast
import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import assessment_adapter as adapter
from assessment_adapter import adapter as adapter_module
from assessment_adapter.policy import PolicyRegistry, canonical_policy_hash

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "fixtures" / "synthetic_assessment.v1.json"
REGISTRY_PATH = ROOT / "assets" / "interpretation_policy_registry.v1.json"


def _assessment() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _registry_payload() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _policy() -> dict[str, Any]:
    return _registry_payload()["policies"][0]


def _context(
    *,
    mode: str = "SYNTHETIC_DEMO",
    population: str = "SYNTHETIC_STUDENT_DEMO",
    safety_action: str = "PROCEED",
) -> adapter.TrustedInterpretationContext:
    return adapter_module._build_trusted_interpretation_context(
        {
            "execution_mode": mode,
            "assessment_population": population,
            "context_id": "CTX_d3_2_test",
            "context_version": "1.0.0",
            "safety_action": safety_action,
            "request_id": "REQ_d3_2_test",
            "trace_id": "TRACE_d3_2_test",
        }
    )


def _request(
    assessment: dict[str, Any] | None = None,
    *,
    policy: dict[str, Any] | None = None,
) -> adapter.InterpretationRequest:
    selected = _policy() if policy is None else policy
    return adapter.InterpretationRequest(
        assessment=_assessment() if assessment is None else assessment,
        policy_id=selected["policy_id"],
        policy_version=selected["policy_version"],
        policy_hash=selected["policy_hash"],
        request_id="REQ_d3_2_test",
        trace_id="TRACE_d3_2_test",
    )


def _result(
    *,
    assessment: dict[str, Any] | None = None,
    context: adapter.TrustedInterpretationContext | object | None = None,
    registry: PolicyRegistry | None = None,
    policy: dict[str, Any] | None = None,
) -> adapter.InterpretationResult:
    selected_context = _context() if context is None else context
    return adapter.interpret(
        _request(assessment, policy=policy),
        selected_context,
        registry,
    )


def test_shipped_policy_is_conservative_measurement_only() -> None:
    result = _result()

    assert result.status is adapter.InterpretationStatus.MEASUREMENT_ONLY
    assert result.reason_codes == ("POLICY_CONSERVATIVE_MEASUREMENT_ONLY",)
    assert result.claims == ()
    assert result.limitations == (
        "SYNTHETIC_ONLY",
        "NOT_DIAGNOSTIC",
        "NO_VALIDATED_CUTOFF",
        "NO_CLINICAL_INFERENCE",
        "NO_CRISIS_INFERENCE",
    )
    assert result.policy["psychology_review_status"] == "REVISIONS_REQUIRED"
    assert result.audit["safety_action"] == "PROCEED"


def test_canonical_status_vocabulary_is_typed_and_schema_aligned() -> None:
    canonical = {
        "READY_FOR_RENDERING",
        "MEASUREMENT_ONLY",
        "ABSTAIN_POLICY_MISSING",
        "ABSTAIN_POLICY_NOT_APPROVED",
        "ABSTAIN_INSTRUMENT_MISMATCH",
        "ABSTAIN_POPULATION_MISMATCH",
        "ABSTAIN_PRECISION_INSUFFICIENT",
        "ABSTAIN_CONSTRUCT_UNAPPROVED",
        "BYPASS_SAFETY",
    }
    status_values = {status.value for status in adapter.InterpretationStatus}
    schema = json.loads(
        (ROOT / "schemas" / "interpretation_result.v1.schema.json").read_text(encoding="utf-8")
    )
    schema_values = set(schema["properties"]["status"]["enum"])

    assert canonical <= status_values
    assert canonical <= schema_values
    assert "ABSTAIN_SAFETY_BYPASS" not in status_values
    assert "ABSTAIN_SAFETY_BYPASS" not in schema_values


@pytest.mark.parametrize("se", [0, 0.42, 100])
def test_precision_status_is_reserved_without_an_se_cutoff(se: int | float) -> None:
    assessment = _assessment()
    assessment["dimensions"]["demo_trait"]["se"] = se

    result = _result(assessment=assessment)

    assert adapter.InterpretationStatus.ABSTAIN_PRECISION_INSUFFICIENT.value in {
        status.value for status in adapter.InterpretationStatus
    }
    assert result.status is adapter.InterpretationStatus.MEASUREMENT_ONLY


def test_policy_not_approved_status_is_reserved() -> None:
    schema = json.loads(
        (ROOT / "schemas" / "interpretation_result.v1.schema.json").read_text(encoding="utf-8")
    )

    assert adapter.InterpretationStatus.ABSTAIN_POLICY_NOT_APPROVED.value in {
        status.value for status in adapter.InterpretationStatus
    }
    assert "ABSTAIN_POLICY_NOT_APPROVED" in schema["properties"]["status"]["enum"]
    # The shipped policy remains the conservative measurement-only path until
    # a separately approved interpretation policy is supplied.
    assert _result().status is adapter.InterpretationStatus.MEASUREMENT_ONLY


def test_repeated_run_is_deterministic_and_does_not_mutate_input() -> None:
    assessment = _assessment()
    before = copy.deepcopy(assessment)
    first = _result(assessment=assessment)
    second = _result(assessment=assessment)

    assert first.to_dict() == second.to_dict()
    assert assessment == before
    first_dict = first.to_dict()
    first_dict["audit"]["context_id"] = "CTX_mutated_copy"
    assert first.audit["context_id"] == "CTX_d3_2_test"


def test_assessment_is_validated_read_only_and_incomplete_input_abstains() -> None:
    assessment = _assessment()
    assessment["dimensions"]["demo_trait"]["se"] = -1
    result = _result(assessment=assessment)
    assert result.status is adapter.InterpretationStatus.ABSTAIN_INPUT_INVALID
    assert result.reason_codes == ("ASSESSMENT_SCHEMA_INVALID",)

    incomplete = _assessment()
    incomplete.pop("provenance")
    result = _result(assessment=incomplete)
    assert result.status is adapter.InterpretationStatus.ABSTAIN_INPUT_INVALID


def test_exact_policy_hash_and_identity_fail_closed() -> None:
    policy = _policy()
    assert canonical_policy_hash(policy) == policy["policy_hash"]

    wrong_hash = copy.deepcopy(policy)
    wrong_hash["policy_hash"] = "sha256:" + "0" * 64
    request = _request(policy=wrong_hash)
    result = adapter.interpret(request, _context())
    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_HASH_MISMATCH
    assert result.reason_codes == ("POLICY_HASH_MISMATCH",)

    missing = copy.deepcopy(policy)
    missing.pop("policy_hash")
    missing_request = {
        "assessment": _assessment(),
        "policy_ref": {
            "policy_id": missing["policy_id"],
            "policy_version": missing["policy_version"],
        },
    }
    result = adapter.interpret(missing_request, _context())
    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_MISSING
    assert result.reason_codes == ("POLICY_REFERENCE_MISSING",)


def test_missing_and_duplicate_policy_entries_fail_closed() -> None:
    missing = copy.deepcopy(_policy())
    missing["policy_id"] = "POLICY_missing"
    missing["policy_hash"] = canonical_policy_hash(missing)
    registry = PolicyRegistry.from_payload(
        {
            "schema_version": "interpretation-policy-registry.v1",
            "registry_version": "1",
            "policies": [_policy()],
        }
    )
    assert (
        _result(registry=registry, policy=missing).status
        is adapter.InterpretationStatus.ABSTAIN_POLICY_MISSING
    )

    duplicated = _registry_payload()
    duplicated["policies"].append(copy.deepcopy(duplicated["policies"][0]))
    duplicate_registry = PolicyRegistry.from_payload(duplicated)
    result = _result(registry=duplicate_registry)
    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_MISMATCH
    assert result.reason_codes == ("POLICY_DUPLICATE",)


def test_invalid_policy_asset_is_retained_as_fail_closed_entry() -> None:
    payload = _registry_payload()
    payload["policies"][0]["engineering_scope"] = "changed_without_hash"
    registry = PolicyRegistry.from_payload(payload)
    result = _result(registry=registry)
    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_HASH_MISMATCH
    assert result.reason_codes == ("POLICY_HASH_MISMATCH",)


@pytest.mark.parametrize(
    ("field", "value", "status", "reason"),
    [
        (
            "instrument_id",
            "UNAPPROVED_INSTRUMENT",
            adapter.InterpretationStatus.ABSTAIN_INSTRUMENT_MISMATCH,
            "POLICY_INSTRUMENT_MISMATCH",
        ),
        (
            "instrument_version",
            "9.9.9",
            adapter.InterpretationStatus.ABSTAIN_VERSION_MISMATCH,
            "POLICY_VERSION_MISMATCH",
        ),
        (
            "population_scope",
            "OTHER_POPULATION",
            adapter.InterpretationStatus.ABSTAIN_POPULATION_MISMATCH,
            "POPULATION_CONTEXT_MISMATCH",
        ),
    ],
)
def test_identity_dimensions_abstain(
    field: str,
    value: str,
    status: adapter.InterpretationStatus,
    reason: str,
) -> None:
    assessment = _assessment()
    if field.startswith("instrument"):
        key = "instrument_id" if field == "instrument_id" else "version"
        assessment["instrument"][key] = value
        result = _result(assessment=assessment)
    else:
        assessment[field] = value
        result = _result(assessment=assessment)
    assert result.status is status
    assert result.reason_codes == (reason,)


def test_unapproved_construct_abstains_without_old_domain_semantics() -> None:
    assessment = _assessment()
    assessment["dimensions"]["unapproved_construct"] = assessment["dimensions"].pop("demo_trait")
    result = _result(assessment=assessment)
    assert result.status is adapter.InterpretationStatus.ABSTAIN_CONSTRUCT_UNAPPROVED
    assert result.reason_codes == ("CONSTRUCT_UNAPPROVED",)


def test_trusted_context_is_required_and_mode_is_fail_closed() -> None:
    result = _result(context={"execution_mode": "SYNTHETIC_DEMO"})
    assert result.status is adapter.InterpretationStatus.ABSTAIN_INPUT_INVALID
    assert result.reason_codes == ("TRUSTED_CONTEXT_REQUIRED",)

    assert (
        _result(context=_context(mode="REAL_USER")).status
        is adapter.InterpretationStatus.ABSTAIN_REAL_USER_BLOCKED
    )
    assert (
        _result(context=_context(mode="RESEARCH_ONLY")).status
        is adapter.InterpretationStatus.ABSTAIN_MODE_NOT_ALLOWED
    )
    assert (
        _result(context=_context(population="OTHER_POPULATION")).status
        is adapter.InterpretationStatus.ABSTAIN_POPULATION_MISMATCH
    )


@pytest.mark.parametrize("action", ["CRISIS_ROUTE", "REVIEW_REQUIRED", "BLOCK"])
def test_each_trusted_safety_bypass_is_preserved_without_change(action: str) -> None:
    result = _result(context=_context(safety_action=action))
    assert result.status is adapter.InterpretationStatus.BYPASS_SAFETY
    assert result.reason_codes == (action,)
    assert adapter.ReasonCode(action).value == action
    assert result.audit["safety_action"] == action


def test_test_only_neutral_policy_has_ready_status_and_is_not_shipped() -> None:
    policy = copy.deepcopy(_policy())
    policy["policy_id"] = "POLICY_test_neutral"
    policy["policy_kind"] = "SYNTHETIC_TEST_ONLY"
    policy["psychology_review_status"] = "SIGNATURE_BLANK"
    policy["allowed_claims"] = ["SYNTHETIC_TEST_CLAIM"]
    policy["limitations"] = ["SYNTHETIC_ONLY", "NOT_DIAGNOSTIC"]
    policy["construct_policies"]["demo_trait"]["status"] = "TEST_ONLY"
    policy["construct_policies"]["demo_trait"]["allowed_claim_codes"] = [
        "SYNTHETIC_TEST_CLAIM"
    ]
    policy["policy_hash"] = canonical_policy_hash(policy)
    payload = {
        "schema_version": "interpretation-policy-registry.v1",
        "registry_version": "test-only",
        "policies": [policy],
    }
    registry = PolicyRegistry.from_payload(payload, allow_test_only=True)
    result = _result(registry=registry, policy=policy)
    assert result.status is adapter.InterpretationStatus.READY_FOR_RENDERING
    assert result.reason_codes == ("SYNTHETIC_TEST_ONLY_POLICY",)
    assert [claim.claim_code for claim in result.claims] == ["SYNTHETIC_TEST_CLAIM"]
    assert adapter.load_shipped_registry().policies[0].policy_kind == "SHIPPED_CONSERVATIVE"


def test_synthetic_demo_rejects_policy_without_synthetic_only_marker() -> None:
    policy = copy.deepcopy(_policy())
    policy["policy_id"] = "POLICY_test_not_synthetic_only"
    policy["policy_kind"] = "SYNTHETIC_TEST_ONLY"
    policy["synthetic_only"] = False
    policy["allowed_claims"] = ["SYNTHETIC_TEST_CLAIM"]
    policy["construct_policies"]["demo_trait"]["status"] = "TEST_ONLY"
    policy["construct_policies"]["demo_trait"]["allowed_claim_codes"] = [
        "SYNTHETIC_TEST_CLAIM"
    ]
    policy["policy_hash"] = canonical_policy_hash(policy)
    registry = PolicyRegistry.from_payload(
        {
            "schema_version": "interpretation-policy-registry.v1",
            "registry_version": "test-not-synthetic-only",
            "policies": [policy],
        },
        allow_test_only=True,
    )

    result = _result(registry=registry, policy=policy)

    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_MISMATCH
    assert result.reason_codes == ("POLICY_INVALID",)
    assert result.claims == ()


def test_research_only_rejects_policy_without_synthetic_only_marker() -> None:
    policy = copy.deepcopy(_policy())
    policy["policy_id"] = "POLICY_test_research_not_synthetic_only"
    policy["allowed_modes"] = ["RESEARCH_ONLY"]
    policy["policy_kind"] = "SYNTHETIC_TEST_ONLY"
    policy["synthetic_only"] = False
    policy["allowed_claims"] = ["SYNTHETIC_TEST_CLAIM"]
    policy["construct_policies"]["demo_trait"]["status"] = "TEST_ONLY"
    policy["construct_policies"]["demo_trait"]["allowed_claim_codes"] = [
        "SYNTHETIC_TEST_CLAIM"
    ]
    policy["policy_hash"] = canonical_policy_hash(policy)
    registry = PolicyRegistry.from_payload(
        {
            "schema_version": "interpretation-policy-registry.v1",
            "registry_version": "test-research-not-synthetic-only",
            "policies": [policy],
        },
        allow_test_only=True,
    )

    result = _result(
        context=_context(mode="RESEARCH_ONLY"),
        registry=registry,
        policy=policy,
    )

    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_MISMATCH
    assert result.reason_codes == ("POLICY_INVALID",)
    assert result.claims == ()


@pytest.mark.parametrize(
    "forbidden_code",
    [
        "DIAGNOSIS",
        "clinical-severity",
        "SUICIDE_INFERENCE",
        "SELF_HARM",
        "CRISIS_RISK",
        "TREATMENT",
        "LEVEL_1_TO_5",
        "SCORE_BAND",
        "THETA",
        "SE",
        "CONFIDENCE_INTERVAL",
        "PRECISION_AS_RISK",
    ],
)
def test_custom_registry_cannot_emit_forbidden_claim_aliases(forbidden_code: str) -> None:
    policy = copy.deepcopy(_policy())
    policy["policy_id"] = "POLICY_test_forbidden_claim"
    policy["policy_kind"] = "SYNTHETIC_TEST_ONLY"
    policy["allowed_claims"] = [forbidden_code]
    policy["construct_policies"]["demo_trait"]["status"] = "TEST_ONLY"
    policy["construct_policies"]["demo_trait"]["allowed_claim_codes"] = [forbidden_code]
    policy["policy_hash"] = canonical_policy_hash(policy)
    registry = PolicyRegistry.from_payload(
        {
            "schema_version": "interpretation-policy-registry.v1",
            "registry_version": "test-forbidden-claim",
            "policies": [policy],
        },
        allow_test_only=True,
    )

    result = _result(registry=registry, policy=policy)
    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_MISMATCH
    assert result.reason_codes == ("POLICY_INVALID",)
    assert result.claims == ()


def test_defensive_claim_deny_list_covers_direct_typed_registry_objects() -> None:
    shipped = adapter.load_shipped_registry().policies[0]
    construct = shipped.construct_policies["demo_trait"]
    malicious = replace(
        shipped,
        policy_kind="SYNTHETIC_TEST_ONLY",
        allowed_claims=("DIAGNOSIS",),
        construct_policies={
            "demo_trait": replace(
                construct,
                status="TEST_ONLY",
                allowed_claim_codes=("DIAGNOSIS",),
            )
        },
    )
    registry = PolicyRegistry(policies=(malicious,))

    result = _result(registry=registry, policy=malicious.to_dict())
    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_HASH_MISMATCH
    assert result.reason_codes == ("POLICY_HASH_MISMATCH",)
    assert result.claims == ()


def test_direct_typed_policy_content_is_hash_checked_before_acceptance() -> None:
    shipped = adapter.load_shipped_registry().policies[0]
    tampered = replace(shipped, engineering_scope=f"{shipped.engineering_scope}_tampered")
    registry = PolicyRegistry(policies=(tampered,))

    result = _result(registry=registry, policy=tampered.to_dict())

    assert result.status is adapter.InterpretationStatus.ABSTAIN_POLICY_HASH_MISMATCH
    assert result.reason_codes == ("POLICY_HASH_MISMATCH",)


def test_invalid_identity_projection_does_not_echo_names_or_phone_like_values() -> None:
    assessment = _assessment()
    assessment["assessment_id"] = "Alice Zhang"
    assessment["subject_id"] = "13800138000"
    assessment["dimensions"]["demo_trait"]["se"] = -1

    result = _result(assessment=assessment)

    assert result.status is adapter.InterpretationStatus.ABSTAIN_INPUT_INVALID
    assert result.assessment_id is None
    assert result.subject_id is None
    encoded = json.dumps(result.to_dict(), ensure_ascii=False)
    assert "Alice Zhang" not in encoded
    assert "13800138000" not in encoded


def test_invalid_assessment_preserves_only_anonymous_frozen_ids() -> None:
    assessment = _assessment()
    assessment["assessment_id"] = "ASSESS_invalid_but_anonymous"
    assessment["subject_id"] = "SUBJ_invalid_but_anonymous"
    assessment["dimensions"]["demo_trait"]["se"] = -1

    result = _result(assessment=assessment)

    assert result.status is adapter.InterpretationStatus.ABSTAIN_INPUT_INVALID
    assert result.assessment_id == "ASSESS_invalid_but_anonymous"
    assert result.subject_id == "SUBJ_invalid_but_anonymous"


def test_output_schema_and_forbidden_raw_or_prose_content() -> None:
    result = _result()
    output = result.to_dict()
    schema = json.loads(
        (ROOT / "schemas" / "interpretation_result.v1.schema.json").read_text(encoding="utf-8")
    )
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator(schema).validate(output)
    forbidden = {
        "theta",
        "se",
        "score",
        "band",
        "interval",
        "diagnosis",
        "disorder",
        "severity",
        "suicide",
        "self_harm",
        "treatment",
        "level_1_to_5",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert str(key).lower() not in forbidden
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            assert value.lower() not in forbidden

    walk(output)


def test_no_forbidden_runtime_imports_or_d2_dependency() -> None:
    forbidden = {
        "cat_engine",
        "prompt_engine",
        "rag_engine",
        "safety_engine",
        "smhai_backend",
        "requests",
        "httpx",
        "ollama",
    }
    source_root = ROOT / "src"
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
        assert "knowledge-base/00_index_资料总表.xlsx" not in path.read_text(encoding="utf-8")


def test_private_context_constructor_rejects_caller_forgery() -> None:
    with pytest.raises(TypeError):
        context_type: Any = adapter.TrustedInterpretationContext
        context_type(
            execution_mode=adapter.ExecutionMode.SYNTHETIC_DEMO,
            assessment_population="SYNTHETIC_STUDENT_DEMO",
            context_id="CTX_forged",
            context_version="1.0.0",
            safety_action=adapter.SafetyAction.PROCEED,
            request_id="REQ_forged",
            trace_id="TRACE_forged",
        )
