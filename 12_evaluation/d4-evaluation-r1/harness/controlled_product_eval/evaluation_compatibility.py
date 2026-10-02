"""Explicit evaluation-only CAT-to-D3 fixture injection for D4-3B R2.

This module is a Harness-owned runtime bootstrap. It loads a canonical fixture
outside the product tree and injects it through the existing Backend
assessment-compatibility seam before the Backend container is constructed.
It never edits or normalizes a stored assessment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


FIXTURE_ID = "d4-3b-cat-v0_1-to-d3-synthetic"
FIXTURE_VERSION = "1.0.0"
APPROVAL_REFERENCE = "D4-3B_CONTROLLER_CAT_COMPATIBILITY_R1"
POLICY_ID = "POLICY_assessment_synthetic_measurement_only"

SOURCE_IDENTITY = {
    "instrument_id": "instrument_demo_cat_v0_1",
    "instrument_version": "demo.v1",
    "population_scope": "pending_confirmation",
}
TARGET_IDENTITY = {
    "instrument_id": "CURRENT_SYNTHETIC_GRM",
    "instrument_version": "synthetic_item_bank.v1 / demo.v1",
    "population_scope": "SYNTHETIC_STUDENT_DEMO",
}
FIXTURE_DOCUMENT = {
    "fixture_id": FIXTURE_ID,
    "fixture_version": FIXTURE_VERSION,
    "source": SOURCE_IDENTITY,
    "target": TARGET_IDENTITY,
    "policy_id": POLICY_ID,
    "approved": True,
    "approval_reference": APPROVAL_REFERENCE,
    "dimension_map": {},
}
_FIXTURE_KEYS = {
    "fixture_id",
    "fixture_version",
    "source",
    "target",
    "policy_id",
    "approved",
    "approval_reference",
    "dimension_map",
}
_IDENTITY_KEYS = {"instrument_id", "instrument_version", "population_scope"}
_FORMAL_RUN_ID_RE = re.compile(r"^D4RUN-[A-Za-z0-9][A-Za-z0-9._-]*$")
_SMOKE_RUN_ID_RE = re.compile(r"^D4SMOKE-[A-Za-z0-9][A-Za-z0-9._-]*$")
NONFORMAL_EVIDENCE_CLASS = "NOT_FORMAL_PRODUCT_EVIDENCE"


class CompatibilityFixtureError(ValueError):
    """The external fixture does not match the Controller-approved artifact."""


def _evidence_class_for_run_id(run_id: str) -> str | None:
    if _FORMAL_RUN_ID_RE.fullmatch(run_id):
        return None
    if _SMOKE_RUN_ID_RE.fullmatch(run_id):
        return NONFORMAL_EVIDENCE_CLASS
    raise CompatibilityFixtureError("fixture injection requires an approved D4RUN or D4SMOKE context ID")


def validate_harness_activation_context(*, harness_command: str, run_id: str) -> None:
    """Bind the internal Backend bootstrap to the fixed evaluation command."""

    evidence_class = _evidence_class_for_run_id(run_id)
    if harness_command == "run" and evidence_class is None:
        return
    if harness_command == "smoke-product" and evidence_class == NONFORMAL_EVIDENCE_CLASS:
        return
    raise CompatibilityFixtureError("harness command and fixture activation context do not match")


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _unique_object(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CompatibilityFixtureError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_fixture_bytes(raw: bytes) -> tuple[dict[str, Any], str]:
    """Validate the exact approved document and return it with its file hash."""

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompatibilityFixtureError("fixture must be UTF-8 JSON") from exc
    if not isinstance(value, dict) or set(value) != _FIXTURE_KEYS:
        raise CompatibilityFixtureError("fixture fields do not match the approved shape")
    if value["fixture_id"] != FIXTURE_ID or value["fixture_version"] != FIXTURE_VERSION:
        raise CompatibilityFixtureError("fixture identity or version does not match approval")
    if value["source"] != SOURCE_IDENTITY or value["target"] != TARGET_IDENTITY:
        raise CompatibilityFixtureError("fixture source or target identity does not match approval")
    if set(value["source"]) != _IDENTITY_KEYS or set(value["target"]) != _IDENTITY_KEYS:
        raise CompatibilityFixtureError("identity objects must contain exactly three fields")
    if value["policy_id"] != POLICY_ID:
        raise CompatibilityFixtureError("fixture policy does not match the frozen D3 policy")
    if value["approved"] is not True or value["approval_reference"] != APPROVAL_REFERENCE:
        raise CompatibilityFixtureError("fixture approval fields do not match Controller decision")
    if value["dimension_map"] != {}:
        raise CompatibilityFixtureError("dimension_map must remain empty")
    if canonical_json_bytes(value) != raw:
        raise CompatibilityFixtureError("fixture file must contain canonical JSON bytes")
    return value, "sha256:" + hashlib.sha256(raw).hexdigest()


def _write_once(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        dict(value), ensure_ascii=False, sort_keys=True, indent=2
    ) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def _write_bytes_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)


def _correlated_evidence_path(directory: Path, prefix: str, request_id: Any, trace_id: Any) -> Path:
    if not isinstance(request_id, str) or not request_id or not isinstance(trace_id, str) or not trace_id:
        raise CompatibilityFixtureError("observer evidence requires request and trace correlation")
    digest = hashlib.sha256(f"{request_id}\x00{trace_id}".encode("utf-8")).hexdigest()
    return directory / f"{prefix}-{digest}.json"


def _build_fixture_activation_record(
    *,
    run_id: str,
    fixture_path: Path,
    document: Mapping[str, Any],
    fixture_bytes: bytes,
    activated_at: str,
    process_pid: int,
    fixture_instance_count: int,
    d3_policy_version: str,
    d3_policy_hash: str,
    evidence_class: str | None = None,
) -> dict[str, Any]:
    record = {
        "schema_version": "d4-3b-runtime-fixture-activation.v1",
        "run_id": run_id,
        "fixture_id": FIXTURE_ID,
        "fixture_version": FIXTURE_VERSION,
        "injection_location": "smhai_backend.domains.support.service.default_fixture_config before BackendContainer/SupportOrchestrator construction",
        "binding_audit_observer": "smhai_backend.domains.support.service.bind_assessment",
        "d3_2_policy_observer": "smhai_backend.domains.support.service.interpret_d3_chain",
        "fixture_file": str(fixture_path),
        "fixture_canonical_json": dict(document),
        "fixture_sha256": hashlib.sha256(fixture_bytes).hexdigest(),
        "source_identity": SOURCE_IDENTITY,
        "target_identity": TARGET_IDENTITY,
        "policy_id": POLICY_ID,
        "approved": True,
        "fixture_instantiated": fixture_instance_count == 1,
        "fixture_injected": fixture_instance_count == 1,
        "approval_reference": APPROVAL_REFERENCE,
        "dimension_map": {},
        "activated_at": activated_at,
        "process_pid": process_pid,
        "runtime_only": True,
        "canonical_product_default_changed": False,
        "other_d3_fixture_config_preserved": True,
        "fixture_instance_count": fixture_instance_count,
        "d3_policy_version": d3_policy_version,
        "d3_policy_hash": d3_policy_hash,
    }
    if evidence_class is not None:
        record["evidence_class"] = evidence_class
    return record


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


def _interpretation_payload(interpretation: Any) -> Mapping[str, Any]:
    """Return the D3-2 result's own serialized fields without consulting policy refs."""

    to_dict = getattr(interpretation, "to_dict", None)
    if callable(to_dict):
        payload = to_dict()
        if isinstance(payload, Mapping):
            return payload
    if isinstance(interpretation, Mapping):
        return interpretation
    return {}


def _field(payload: Mapping[str, Any], interpretation: Any, name: str) -> tuple[bool, Any]:
    if name in payload:
        return True, payload[name]
    if hasattr(interpretation, name):
        return True, getattr(interpretation, name)
    return False, None


def _string_values(value: Any) -> list[str] | None:
    if isinstance(value, str):
        return [value] if value else None
    if isinstance(value, Mapping):
        direct_id = value.get("construct_id")
        if isinstance(direct_id, str) and direct_id:
            return [direct_id]
        values = list(value.keys())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = []
        for item in value:
            if isinstance(item, str) and item:
                values.append(item)
                continue
            if isinstance(item, Mapping):
                construct_id = item.get("construct_id")
            else:
                construct_id = getattr(item, "construct_id", None)
            if not isinstance(construct_id, str) or not construct_id:
                return None
            values.append(construct_id)
    else:
        return None
    if all(isinstance(item, str) and item for item in values):
        return sorted(set(values))
    return None


def _construct_identifiers(
    payload: Mapping[str, Any], interpretation: Any
) -> dict[str, Any]:
    for field_name in ("construct_identifiers", "construct_ids", "constructs"):
        present, value = _field(payload, interpretation, field_name)
        if present:
            values = _string_values(value)
            if values is None:
                return {
                    "status": "INVALID_INTERPRETATION_RESULT_FIELD",
                    "values": None,
                }
            return {"status": "EXPOSED_BY_INTERPRETATION_RESULT", "values": values}

    claims_present, claims = _field(payload, interpretation, "claims")
    if claims_present and isinstance(claims, Sequence) and not isinstance(
        claims, (str, bytes, bytearray)
    ):
        claim_ids: list[str] = []
        for claim in claims:
            if isinstance(claim, Mapping):
                construct_id = claim.get("construct_id")
            else:
                construct_id = getattr(claim, "construct_id", None)
            if isinstance(construct_id, str) and construct_id:
                claim_ids.append(construct_id)
        if claim_ids:
            return {
                "status": "EXPOSED_BY_INTERPRETATION_RESULT_CLAIMS",
                "values": sorted(set(claim_ids)),
            }

    return {
        "status": "NOT_EXPOSED_BY_INTERPRETATION_RESULT",
        "values": None,
    }


def build_d3_2_observation(
    interpretation: Any,
    *,
    source_dimension_keys: Sequence[str],
    request_id: str,
    trace_id: str,
    fixture_id: str,
) -> dict[str, Any]:
    """Audit only fields exposed by the actual D3-2 interpretation result.

    Source dimension keys are carried separately for comparison. They are not
    promoted to interpretation construct identifiers when D3-2 emits no such
    field or claim.
    """

    payload = _interpretation_payload(interpretation)
    policy_present, policy = _field(payload, interpretation, "policy")
    if not policy_present or not isinstance(policy, Mapping):
        policy = {}

    def actual_text(field_name: str, *, nested: Mapping[str, Any] | None = None) -> str:
        present, raw = (field_name in nested, nested.get(field_name)) if nested is not None else _field(
            payload, interpretation, field_name
        )
        normalized = _value(raw) if present else None
        return normalized if isinstance(normalized, str) and normalized else "NOT_EXPOSED_BY_INTERPRETATION_RESULT"

    claims_present, claims = _field(payload, interpretation, "claims")
    if claims_present and isinstance(claims, Sequence) and not isinstance(
        claims, (str, bytes, bytearray)
    ):
        claim_count: int | str = len(claims)
    else:
        claim_count = "NOT_EXPOSED_BY_INTERPRETATION_RESULT"

    limitations_present, limitations = _field(payload, interpretation, "limitations")
    if limitations_present and isinstance(limitations, Sequence) and not isinstance(
        limitations, (str, bytes, bytearray)
    ):
        if all(isinstance(item, str) for item in limitations):
            limitation_status = "EXPOSED_BY_INTERPRETATION_RESULT"
            limitation_values: list[str] | str = list(limitations)
        else:
            limitation_status = "INVALID_INTERPRETATION_RESULT_FIELD"
            limitation_values = "INVALID_INTERPRETATION_RESULT_FIELD"
    elif limitations_present:
        limitation_status = "INVALID_INTERPRETATION_RESULT_FIELD"
        limitation_values = "INVALID_INTERPRETATION_RESULT_FIELD"
    else:
        limitation_status = "NOT_EXPOSED_BY_INTERPRETATION_RESULT"
        limitation_values = "NOT_EXPOSED_BY_INTERPRETATION_RESULT"

    reason_present, reason_codes = _field(payload, interpretation, "reason_codes")
    if reason_present and isinstance(reason_codes, Sequence) and not isinstance(
        reason_codes, (str, bytes, bytearray)
    ):
        normalized_reasons = [str(_value(item)) for item in reason_codes]
    else:
        normalized_reasons = ["NOT_EXPOSED_BY_INTERPRETATION_RESULT"]

    return {
        "schema_version": "d4-3b-d3-2-observer.v2",
        "status": actual_text("status"),
        "reason_codes": normalized_reasons,
        "policy_id": actual_text("policy_id", nested=policy),
        "policy_version": actual_text("policy_version", nested=policy),
        "policy_hash": actual_text("policy_hash", nested=policy),
        "construct_identifiers": _construct_identifiers(payload, interpretation),
        "source_dimension_keys": sorted(set(source_dimension_keys)),
        "limitations_status": limitation_status,
        "limitations": limitation_values,
        "claim_count": claim_count,
        "request_id": request_id,
        "trace_id": trace_id,
        "fixture_id": fixture_id,
    }


def build_d3_smoke_chain_observation(
    result: Any,
    bundle: Any,
    *,
    run_id: str,
    request_id: str,
    trace_id: str,
    error_type: str | None = None,
) -> dict[str, Any]:
    """Project only bounded bundle and D3-3/D3-1 identities for D4SMOKE."""

    try:
        verify = getattr(bundle, "verify", None)
        if callable(verify):
            verify()
        eligible = getattr(bundle, "eligible", False) is True
        items = getattr(bundle, "items", ())
        chunk_count = len(items) if isinstance(items, Sequence) else 0
        bundle_hash = getattr(bundle, "bundle_hash", None)
        evidence_bundle_status = (
            "PASS"
            if eligible and chunk_count > 0 and isinstance(bundle_hash, str) and bundle_hash
            else "FAIL"
        )
    except Exception as exc:
        eligible = False
        chunk_count = 0
        bundle_hash = None
        evidence_bundle_status = "FAIL"
        error_type = error_type or type(exc).__name__

    role_policy = getattr(result, "role_policy", None)
    template = getattr(result, "template", None)
    content_mapping = getattr(result, "content_population_mapping", None)

    def exposed(value: Any, name: str) -> str | None:
        candidate = getattr(value, name, None)
        return candidate if isinstance(candidate, str) and candidate else None

    d3_3_identity = {
        "policy_id": exposed(role_policy, "policy_id"),
        "policy_version": exposed(role_policy, "policy_version"),
        "policy_hash": exposed(role_policy, "policy_hash"),
    }
    d3_1_identity = {
        "prompt_id": exposed(template, "prompt_id"),
        "prompt_version": exposed(template, "prompt_version"),
        "prompt_hash": exposed(template, "content_hash"),
    }
    d3_3_reached = all(d3_3_identity.values())
    d3_1_reached = all(d3_1_identity.values())
    chain_status = "PASS" if error_type is None else "FAIL"
    status = (
        "PASS"
        if chain_status == "PASS"
        and evidence_bundle_status == "PASS"
        and d3_3_reached
        and d3_1_reached
        else "FAIL"
    )
    return {
        "schema_version": "d4-smoke-d3-chain-audit.v1",
        "run_id": run_id,
        "evidence_class": NONFORMAL_EVIDENCE_CLASS,
        "status": status,
        "evidence_bundle_status": evidence_bundle_status,
        "bundle_eligible": eligible,
        "bundle_chunk_count": chunk_count,
        "bundle_hash": bundle_hash,
        "d3_3_reached": d3_3_reached,
        "d3_3_policy_id": d3_3_identity["policy_id"],
        "d3_3_policy_version": d3_3_identity["policy_version"],
        "d3_3_policy_hash": d3_3_identity["policy_hash"],
        "d3_1_reached": d3_1_reached,
        "d3_1_prompt_id": d3_1_identity["prompt_id"],
        "d3_1_prompt_version": d3_1_identity["prompt_version"],
        "d3_1_prompt_hash": d3_1_identity["prompt_hash"],
        "content_population_mapping_id": exposed(content_mapping, "mapping_id"),
        "content_population_mapping_version": exposed(content_mapping, "mapping_version"),
        "content_population": exposed(content_mapping, "target_population"),
        "request_id": request_id,
        "trace_id": trace_id,
        "error_type": error_type,
    }


def validate_d3_smoke_chain_observation(value: Mapping[str, Any]) -> None:
    """Validate the bounded D4SMOKE D3-chain audit without product imports."""

    import jsonschema

    schema_path = Path(__file__).resolve().parents[2] / "spec" / "d4_smoke_d3_chain_audit.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        ).validate(value)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise CompatibilityFixtureError("D4SMOKE D3-chain audit failed schema validation") from exc


def create_injected_backend_app(*, evidence_dir: Path, run_id: str) -> Any:
    """Inject the fixture and safe observers before constructing the app."""

    evidence_dir = evidence_dir.resolve(strict=True)
    evidence_class = _evidence_class_for_run_id(run_id)
    fixture_bytes = canonical_json_bytes(FIXTURE_DOCUMENT)
    fixture_path = evidence_dir / "approved-cat-d3-compatibility-fixture.json"
    activation_path = evidence_dir / "fixture-activation.json"
    if fixture_path.exists() or activation_path.exists():
        raise CompatibilityFixtureError("refusing to reuse existing fixture or activation evidence")
    _write_bytes_once(fixture_path, fixture_bytes)
    document, fixture_hash = parse_fixture_bytes(fixture_bytes)
    binding_directory = evidence_dir / "binding-audits"
    interpretation_directory = evidence_dir / "d3-2-audits"
    d3_chain_directory = evidence_dir / "d3-chain-audits"

    from dataclasses import replace

    import smhai_backend.domains.support.service as support_service
    from smhai_backend.domains.assessment.binding import (
        D3_IDENTITY,
        D3_POLICY_HASH,
        D3_POLICY_ID,
        D3_POLICY_VERSION,
        AssessmentCompatibilityFixture,
        AssessmentIdentity,
    )
    from smhai_backend.integrations import d3 as d3_integration
    from smhai_backend.integrations.d3_chain import D3ChainError

    if D3_POLICY_ID != POLICY_ID or D3_IDENTITY.to_dict() != TARGET_IDENTITY:
        raise CompatibilityFixtureError("loaded Backend D3 identity/policy differs from approval")

    fixture = AssessmentCompatibilityFixture(
        fixture_id=FIXTURE_ID,
        fixture_version=FIXTURE_VERSION,
        source=AssessmentIdentity(**SOURCE_IDENTITY),
        target=AssessmentIdentity(**TARGET_IDENTITY),
        policy_id=POLICY_ID,
        approved=True,
        approval_reference=APPROVAL_REFERENCE,
        dimension_map=(),
    )
    baseline_config = d3_integration.default_fixture_config()
    evaluation_config = replace(baseline_config, assessment_fixtures=(fixture,))

    # The seam is the existing SupportOrchestrator fixture factory. Preserve
    # every other field from the established D3 config, including its separate
    # later RAG/content boundary.
    support_service.default_fixture_config = lambda: evaluation_config

    original_bind = support_service.bind_assessment

    def audited_bind(*args: Any, **kwargs: Any) -> Any:
        binding = original_bind(*args, **kwargs)
        source_before = binding.source_identity.to_dict()
        source_record = binding.assessment
        instrument = source_record.get("instrument")
        if not isinstance(instrument, Mapping):
            raise CompatibilityFixtureError("bound assessment source instrument is missing")
        dimensions = source_record.get("dimensions")
        dimension_keys = sorted(str(key) for key in dimensions) if isinstance(dimensions, Mapping) else []
        if source_before != SOURCE_IDENTITY or dimension_keys != ["demo_trait"]:
            raise CompatibilityFixtureError("bound source identity or dimensions failed the provenance gate")

        d3_projection = binding.assessment_for_d3()
        projected_instrument = d3_projection.get("instrument")
        source_after = {
            "instrument_id": instrument.get("instrument_id"),
            "instrument_version": instrument.get("version"),
            "population_scope": source_record.get("population_scope"),
        }
        projected_identity = {
            "instrument_id": projected_instrument.get("instrument_id")
            if isinstance(projected_instrument, Mapping)
            else None,
            "instrument_version": projected_instrument.get("version")
            if isinstance(projected_instrument, Mapping)
            else None,
            "population_scope": d3_projection.get("population_scope"),
        }
        binding.assert_intact()
        if source_after != SOURCE_IDENTITY or projected_identity != TARGET_IDENTITY:
            raise CompatibilityFixtureError("D3 projection altered source identity or missed the approved target")

        audit = binding.audit_projection()
        audit.update(
            {
                "fixture_canonical_json": document,
                "fixture_sha256": fixture_hash,
                "source_identity_after_projection": source_after,
                "d3_projection_identity": projected_identity,
                "source_dimension_keys": dimension_keys,
                "stored_source_unchanged_in_binding": True,
            }
        )
        _write_once(
            _correlated_evidence_path(
                binding_directory,
                "binding-audit",
                kwargs.get("request_id"),
                kwargs.get("trace_id"),
            ),
            audit,
        )
        return binding

    support_service.bind_assessment = audited_bind

    original_interpret = support_service.interpret_d3_chain

    def audited_interpret(context: Any, binding: Any, ledger: Any) -> Any:
        try:
            result = original_interpret(context, binding, ledger)
        except Exception as exc:
            _write_once(
                _correlated_evidence_path(
                    interpretation_directory,
                    "d3-2-audit",
                    getattr(context, "request_id", None),
                    getattr(context, "trace_id", None),
                ),
                {
                    "status": "ERROR",
                    "request_id": context.request_id,
                    "trace_id": context.trace_id,
                    "error_type": type(exc).__name__,
                    "policy_id_expected": POLICY_ID,
                },
            )
            raise

        interpretation = result.interpretation
        dimensions = binding.assessment.get("dimensions")
        source_dimension_keys = (
            sorted(str(key) for key in dimensions)
            if isinstance(dimensions, Mapping)
            else []
        )
        observed = build_d3_2_observation(
            interpretation,
            source_dimension_keys=source_dimension_keys,
            request_id=context.request_id,
            trace_id=context.trace_id,
            fixture_id=binding.compatibility_fixture_id,
        )
        _write_once(
            _correlated_evidence_path(
                interpretation_directory,
                "d3-2-audit",
                context.request_id,
                context.trace_id,
            ),
            observed,
        )

        if (
            observed["status"] != "MEASUREMENT_ONLY"
            or observed["policy_id"] != POLICY_ID
            or observed["policy_version"] != D3_POLICY_VERSION
            or observed["policy_hash"] != D3_POLICY_HASH
            or observed["claim_count"] != 0
        ):
            raise D3ChainError("D3_2_EVALUATION_POLICY_GATE")
        return result

    support_service.interpret_d3_chain = audited_interpret

    if evidence_class is not None:
        original_compose = support_service.compose_d3_chain

        def audited_compose(*args: Any, **kwargs: Any) -> Any:
            context = args[0] if args else kwargs.get("context")
            bundle = args[3] if len(args) > 3 else kwargs.get("bundle")
            request_id = getattr(context, "request_id", None)
            trace_id = getattr(context, "trace_id", None)
            try:
                result = original_compose(*args, **kwargs)
            except Exception as exc:
                audit = build_d3_smoke_chain_observation(
                    None,
                    bundle,
                    run_id=run_id,
                    request_id=request_id,
                    trace_id=trace_id,
                    error_type=type(exc).__name__,
                )
                validate_d3_smoke_chain_observation(audit)
                _write_once(
                    _correlated_evidence_path(
                        d3_chain_directory,
                        "d3-chain-audit",
                        request_id,
                        trace_id,
                    ),
                    audit,
                )
                raise

            audit = build_d3_smoke_chain_observation(
                result,
                bundle,
                run_id=run_id,
                request_id=request_id,
                trace_id=trace_id,
            )
            validate_d3_smoke_chain_observation(audit)
            _write_once(
                _correlated_evidence_path(
                    d3_chain_directory,
                    "d3-chain-audit",
                    request_id,
                    trace_id,
                ),
                audit,
            )
            if audit["status"] != "PASS":
                raise D3ChainError("D4_SMOKE_D3_CHAIN_OBSERVER_GATE")
            return result

        support_service.compose_d3_chain = audited_compose

    from smhai_backend.app_factory import create_app

    app = create_app()
    installed = app.state.container.support._d3_fixtures.assessment_fixtures
    if installed != (fixture,):
        raise CompatibilityFixtureError("evaluation fixture was not installed in the SupportOrchestrator")

    activated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    activation = _build_fixture_activation_record(
        run_id=run_id,
        fixture_path=fixture_path,
        document=document,
        fixture_bytes=fixture_bytes,
        activated_at=activated_at,
        process_pid=os.getpid(),
        fixture_instance_count=len(installed),
        d3_policy_version=D3_POLICY_VERSION,
        d3_policy_hash=D3_POLICY_HASH,
        evidence_class=evidence_class,
    )
    _write_once(activation_path, activation)
    app.state.d4_evaluation_fixture_activation = activation
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Backend with the explicit D4-3B evaluation-only compatibility fixture")
    parser.add_argument("--harness-command", choices=("run", "smoke-product"), required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if args.host != "127.0.0.1":
        raise SystemExit("evaluation Backend must bind only to 127.0.0.1")
    validate_harness_activation_context(harness_command=args.harness_command, run_id=args.run_id)
    import uvicorn

    app = create_injected_backend_app(evidence_dir=args.evidence_dir, run_id=args.run_id)
    uvicorn.run(app, host=args.host, port=args.port, workers=1, reload=False, log_level="info")


if __name__ == "__main__":
    main()
