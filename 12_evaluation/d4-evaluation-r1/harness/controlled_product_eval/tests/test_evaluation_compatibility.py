from __future__ import annotations

import json
import inspect
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
ASSESSMENT_ADAPTER_SRC = REPO_ROOT / "03_assessment-adapter" / "src"
if str(ASSESSMENT_ADAPTER_SRC) not in sys.path:
    sys.path.insert(0, str(ASSESSMENT_ADAPTER_SRC))

import assessment_adapter as adapter
from assessment_adapter import adapter as adapter_module

from harness.controlled_product_eval.evaluation_compatibility import (
    APPROVAL_REFERENCE,
    FIXTURE_ID,
    FIXTURE_VERSION,
    POLICY_ID,
    SOURCE_IDENTITY,
    TARGET_IDENTITY,
    CompatibilityFixtureError,
    FIXTURE_DOCUMENT,
    _build_fixture_activation_record,
    build_d3_2_observation,
    canonical_json_bytes,
    create_injected_backend_app,
    parse_fixture_bytes,
    _correlated_evidence_path,
)


def _approved_document():
    return {
        "fixture_id": FIXTURE_ID,
        "fixture_version": FIXTURE_VERSION,
        "source": SOURCE_IDENTITY,
        "target": TARGET_IDENTITY,
        "policy_id": POLICY_ID,
        "approved": True,
        "approval_reference": APPROVAL_REFERENCE,
        "dimension_map": {},
    }


def test_controller_fixture_requires_exact_identity_and_empty_dimension_map():
    document = _approved_document()
    parsed, digest = parse_fixture_bytes(canonical_json_bytes(document))
    assert parsed == document
    assert digest.startswith("sha256:")

    document["dimension_map"] = {"demo_trait": "demo_trait"}
    with pytest.raises(CompatibilityFixtureError, match="must remain empty"):
        parse_fixture_bytes(canonical_json_bytes(document))


def test_runtime_fixture_is_harness_fixed_and_evidence_is_request_correlated(tmp_path):
    parsed, _ = parse_fixture_bytes(canonical_json_bytes(FIXTURE_DOCUMENT))
    assert parsed == _approved_document()
    assert "fixture_path" not in inspect.signature(create_injected_backend_app).parameters
    first = _correlated_evidence_path(tmp_path, "binding-audit", "REQ_1", "TRACE_1")
    second = _correlated_evidence_path(tmp_path, "binding-audit", "REQ_2", "TRACE_2")
    assert first != second
    with pytest.raises(CompatibilityFixtureError, match="request and trace"):
        _correlated_evidence_path(tmp_path, "binding-audit", "", "TRACE_1")


def test_activation_record_binds_exact_fixture_identity_to_formal_run():
    fixture_bytes = canonical_json_bytes(FIXTURE_DOCUMENT)
    record = _build_fixture_activation_record(
        run_id="D4RUN-ACTIVATION000001",
        fixture_path=Path("approved-cat-d3-compatibility-fixture.json"),
        document=FIXTURE_DOCUMENT,
        fixture_bytes=fixture_bytes,
        activated_at="2026-10-02T00:00:00Z",
        process_pid=1234,
        fixture_instance_count=1,
        d3_policy_version="1.0.0",
        d3_policy_hash="sha256:" + "a" * 64,
    )

    assert record["run_id"] == "D4RUN-ACTIVATION000001"
    assert record["fixture_id"] == FIXTURE_ID
    assert record["fixture_version"] == FIXTURE_VERSION
    assert record["fixture_instantiated"] is True
    assert record["fixture_injected"] is True
    assert record["fixture_canonical_json"] == _approved_document()


def test_fixture_rejects_noncanonical_json_and_duplicate_keys():
    document = _approved_document()
    noncanonical = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    with pytest.raises(CompatibilityFixtureError, match="canonical JSON"):
        parse_fixture_bytes(noncanonical)

    duplicate = canonical_json_bytes(document).replace(
        b'"fixture_id":"d4-3b-cat-v0_1-to-d3-synthetic",',
        b'"fixture_id":"d4-3b-cat-v0_1-to-d3-synthetic","fixture_id":"duplicate",',
    )
    with pytest.raises(CompatibilityFixtureError, match="duplicate JSON key"):
        parse_fixture_bytes(duplicate)


def test_fixture_rejects_changed_source_or_policy():
    document = _approved_document()
    document["source"] = {**SOURCE_IDENTITY, "population_scope": "university_freshman"}
    with pytest.raises(CompatibilityFixtureError, match="source or target"):
        parse_fixture_bytes(canonical_json_bytes(document))

    document = _approved_document()
    document["policy_id"] = "POLICY_other"
    with pytest.raises(CompatibilityFixtureError, match="frozen D3 policy"):
        parse_fixture_bytes(canonical_json_bytes(document))


def test_d3_2_observer_reads_frozen_fixture_interpretation_result():
    fixture_path = (
        REPO_ROOT
        / "03_assessment-adapter"
        / "fixtures"
        / "synthetic_assessment.v1.json"
    )
    assessment = json.loads(fixture_path.read_text(encoding="utf-8"))
    registry = adapter_module.load_shipped_registry()
    policy = registry.policies[0]
    request = adapter.InterpretationRequest(
        assessment=assessment,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        request_id="REQ_d3_2_observer_fixture",
        trace_id="TRACE_d3_2_observer_fixture",
    )
    trusted_context = adapter_module._build_trusted_interpretation_context(
        {
            "execution_mode": "SYNTHETIC_DEMO",
            "assessment_population": assessment["population_scope"],
            "context_id": "CTX_d3_2_observer_fixture",
            "context_version": "1.0.0",
            "safety_action": "PROCEED",
            "request_id": request.request_id,
            "trace_id": request.trace_id,
        }
    )
    interpretation = adapter.InterpretationAdapter(registry).interpret(
        request, trusted_context
    )

    observed = build_d3_2_observation(
        interpretation,
        source_dimension_keys=assessment["dimensions"].keys(),
        request_id=request.request_id,
        trace_id=request.trace_id,
        fixture_id="d3-2-frozen-fixture-validation",
    )

    assert observed["status"] == "MEASUREMENT_ONLY"
    assert observed["reason_codes"] == ["POLICY_CONSERVATIVE_MEASUREMENT_ONLY"]
    assert observed["policy_id"] == POLICY_ID
    assert observed["policy_version"] == "1.0.0"
    assert observed["policy_hash"] == "sha256:7c61cf80dc68561c78618c2d6e3859295b0dc53a291a1805c9bb623c5b7714a4"
    assert observed["claim_count"] == 0
    assert observed["source_dimension_keys"] == ["demo_trait"]
    assert observed["construct_identifiers"] == {
        "status": "NOT_EXPOSED_BY_INTERPRETATION_RESULT",
        "values": None,
    }
    assert observed["limitations_status"] == "EXPOSED_BY_INTERPRETATION_RESULT"
    assert observed["limitations"] == [
        "SYNTHETIC_ONLY",
        "NOT_DIAGNOSTIC",
        "NO_VALIDATED_CUTOFF",
        "NO_CLINICAL_INFERENCE",
        "NO_CRISIS_INFERENCE",
    ]
