"""Normalized machine-evidence shell for D4 per-case records."""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .errors import HashIntegrityError, ManifestError
from .fixtures import compatibility_mapping_for, fixture_mode_for
from .hashing import validate_sha256_hex
from .paths import validate_result_path
from .run_ids import validate_run_id
from .splits import DATASET_SPLITS

EVIDENCE_REQUIRED_FIELDS = (
    "schema_version",
    "run_id",
    "run_mode",
    "case_id",
    "d4e_ids",
    "d4sup_ids",
    "risk_domain",
    "split",
    "fixture_version",
    "fixture_sha256",
    "git_commit",
    "route",
    "expected_invariant",
    "failure_type",
    "expected_response_class",
    "observed_response_class",
    "observed_outcome",
    "calls",
    "human_review",
    "request_id",
    "trace_id",
    "transaction_id",
    "stage",
    "target_identity",
    "model_identity",
    "template_identity",
    "policy_identity",
    "evidence_bundle",
    "http_status",
    "product_status",
    "safety",
    "citation_support",
    "answerability",
    "assessment_binding",
    "role_context",
    "real_student_data",
    "cloud_fallback",
)
EVIDENCE_OPTIONAL_FIELDS = {
    "context_id",
    "call_order",
    "citations",
    "grader",
    "artifacts",
    "limitations",
    "unknown_fields",
    "false_refusal",
    "chinese_behavior",
    "behavioral",
    "structured_output",
    "availability",
    "sealed_result",
    "regression_fixture_promoted",
}
EVIDENCE_ALLOWED_FIELDS = set(EVIDENCE_REQUIRED_FIELDS) | EVIDENCE_OPTIONAL_FIELDS
RESPONSE_CLASSES = {
    "MUST_ANSWER",
    "SHOULD_ANSWER",
    "SHOULD_ABSTAIN",
    "MUST_ROUTE",
    "MUST_DENY",
    "GENERATED",
    "SAFETY_STOP",
    "UNANSWERABLE_FAIL_CLOSED",
    "ROLE_BOUNDARY_DENIED",
    "DEPENDENCY_FAILURE",
    "FORMAT_FAILURE",
    "AUTHZ_FAILURE",
    "NOT_OBSERVED",
}
EXPECTED_RESPONSE_CLASSES = {
    "MUST_ANSWER",
    "SHOULD_ANSWER",
    "SHOULD_ABSTAIN",
    "MUST_ROUTE",
    "MUST_DENY",
}
OBSERVED_RESPONSE_CLASSES = {
    "GENERATED",
    "ABSTAINED",
    "ROUTED_TO_HUMAN_REVIEW",
    "DENIED",
    "SAFETY_STOP",
    "UNANSWERABLE_FAIL_CLOSED",
    "ROLE_BOUNDARY_DENIED",
    "DEPENDENCY_FAILURE",
    "FORMAT_FAILURE",
    "AUTHZ_FAILURE",
    "NOT_OBSERVED",
}
OBSERVED_OUTCOMES = {
    "PASS",
    "FAIL",
    "BLOCKED",
    "NOT_RUN",
    "PENDING_REVIEW",
    "ERROR",
}
D4E_IDS = {f"D4E-{index:02d}" for index in range(1, 61)}
D4SUP_IDS = {f"D4SUP-{index:02d}" for index in range(1, 21)}
FAILURE_TYPES = {
    None,
    "NONE",
    "MODEL_FAILURE",
    "APPLICATION_FAILURE",
    "SAFETY_FAILURE",
    "RETRIEVAL_FAILURE",
    "POLICY_FAILURE",
    "AUTHZ_FAILURE",
    "FORMAT_FAILURE",
    "DEPENDENCY_FAILURE",
}
CALL_FIELDS = (
    "safety_input",
    "d3_2",
    "rag",
    "safety_retrieval",
    "d3_3",
    "d3_1",
    "llm",
    "safety_output",
)
_SECRET_FIELD_PATTERN = re.compile(
    r"(?:^|_)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|session[_-]?token|"
    r"password|passwd|secret|credential|private[_-]?key|cookie|env[_-]?dump|environment[_-]?dump)(?:$|_)",
    re.IGNORECASE,
)


def _reject_secret_fields(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if _SECRET_FIELD_PATTERN.search(key_text):
                location = ".".join(path + (key_text,))
                raise ManifestError(
                    f"secret-shaped machine-evidence field is forbidden: {location}"
                )
            _reject_secret_fields(child, path + (key_text,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, path + (str(index),))


def _first_fixture_ref(scenario: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if scenario is None:
        return {}
    refs = scenario.get("fixture_refs")
    if isinstance(refs, list) and refs and isinstance(refs[0], Mapping):
        return refs[0]
    binding = scenario.get("assessment_binding")
    if isinstance(binding, Mapping):
        return binding
    return {}


def _scenario_mode(scenario: Mapping[str, Any] | None) -> str:
    if scenario is None:
        return "exact_d3_fixture"
    return fixture_mode_for(scenario)


def _manifest_value(
    manifest: Mapping[str, Any], container: str, key: str
) -> Any:
    """Read an optional nested manifest value without assuming its shape."""

    value = manifest.get(container)
    if not isinstance(value, Mapping):
        return None
    return value.get(key)


def _default_assessment_binding(
    scenario: Mapping[str, Any] | None,
) -> dict[str, Any]:
    mode = _scenario_mode(scenario)
    ref = _first_fixture_ref(scenario)
    fixture_sha = ref.get("sha256") or "0" * 64
    try:
        validate_sha256_hex(fixture_sha)
    except Exception as exc:
        raise ManifestError(f"fixture reference sha256 is invalid: {exc}") from exc
    return {
        "fixture_mode": mode,
        "assessment_id_digest": None,
        "fixture_identity": str(
            ref.get("fixture_identity")
            or str(ref.get("path") or "synthetic_assessment.v1")
            .replace("\\", "/")
            .rsplit("/", 1)[-1]
            .rsplit(".", 1)[0]
        ),
        "fixture_version": str(
            ref.get("fixture_version")
            or (scenario or {}).get("version")
            or "synthetic_assessment.v1"
        ),
        "source_identity": str(ref.get("source_identity") or "CURRENT_SYNTHETIC_GRM"),
        "target_identity": str(ref.get("target_identity") or "SYNTHETIC_STUDENT_DEMO"),
        "compatibility_mapping": str(
            ref.get("compatibility_mapping") or compatibility_mapping_for(mode)
        ),
    }


def _default_role_context(scenario: Mapping[str, Any] | None) -> dict[str, Any]:
    scenario = scenario or {}
    actor_role = scenario.get("actor_role", "student")
    target_role = scenario.get("role", "student")
    if actor_role not in {"student", "teacher", "reviewer"}:
        raise ManifestError(f"invalid actor_role: {actor_role}")
    if target_role not in {"student", "teacher", "parent", "admin", "reviewer"}:
        raise ManifestError(f"invalid target role: {target_role}")
    projection = "server_derived"
    if target_role in {"parent", "admin"}:
        projection = "approved_in_process_projection"
    return {
        "actor_role": actor_role,
        "target_role": target_role,
        "projection_mode": projection,
        "authorization_source": "synthetic_auth_fixture",
        "unavailable_actor_decision": (
            "CONTROLLER_DECISION_REQUIRED"
            if target_role in {"parent", "admin"}
            else "NOT_APPLICABLE"
        ),
    }


def _default_calls(overrides: Mapping[str, Any] | None) -> dict[str, int]:
    calls = {field: 0 for field in CALL_FIELDS}
    if overrides is not None:
        for key, value in overrides.items():
            if key not in calls:
                raise ManifestError(f"unknown machine-evidence call field: {key}")
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ManifestError(f"call count must be a non-negative int: {key}")
            calls[key] = value
    return calls


def build_machine_evidence(
    manifest: Mapping[str, Any],
    scenario: Mapping[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    """Create a schema-shaped, secret-free per-case evidence record."""

    run_id = manifest.get("run_id")
    try:
        validate_run_id(run_id)
    except Exception as exc:
        raise ManifestError(f"machine evidence run_id is invalid: {exc}") from exc
    scenario = scenario or {}
    mode = _scenario_mode(scenario)
    manifest_audit = manifest.get("fixture_audit")
    if isinstance(manifest_audit, Mapping):
        manifest_mode = manifest_audit.get("fixture_mode", manifest_audit.get("mode"))
        if manifest_mode is not None and manifest_mode != mode:
            raise ManifestError(
                "machine evidence fixture mode conflicts with manifest fixture_audit.mode"
            )
    ref = _first_fixture_ref(scenario)
    fixture_sha = fields.pop("fixture_sha256", ref.get("sha256") or "0" * 64)
    try:
        validate_sha256_hex(fixture_sha)
    except Exception as exc:
        raise ManifestError(f"fixture_sha256 is invalid: {exc}") from exc
    split = fields.pop("split", scenario.get("split", "DEV"))
    if split not in DATASET_SPLITS:
        raise ManifestError(f"machine evidence split is invalid: {split}")
    expected = scenario.get("expected_response_class", "SHOULD_ABSTAIN")
    expected_response_class = fields.pop("expected_response_class", expected)
    if expected_response_class not in EXPECTED_RESPONSE_CLASSES:
        raise ManifestError(
            "machine evidence expected_response_class is invalid: "
            + str(expected_response_class)
        )
    # ``response_class`` appeared in the planning schema.  Keep accepting it
    # as an input alias, while emitting the frozen expected/observed fields.
    legacy_response = fields.pop("response_class", None)
    observed_response_class = fields.pop(
        "observed_response_class",
        "NOT_OBSERVED" if legacy_response is None else legacy_response,
    )
    legacy_map = {
        "MUST_ANSWER": "NOT_OBSERVED",
        "SHOULD_ANSWER": "NOT_OBSERVED",
        "SHOULD_ABSTAIN": "ABSTAINED",
        "MUST_ROUTE": "ROUTED_TO_HUMAN_REVIEW",
        "MUST_DENY": "DENIED",
    }
    observed_response_class = legacy_map.get(observed_response_class, observed_response_class)
    if observed_response_class not in OBSERVED_RESPONSE_CLASSES:
        raise ManifestError(
            "machine evidence observed_response_class is invalid: "
            + str(observed_response_class)
        )
    observed_outcome = fields.pop("observed_outcome", "NOT_RUN")
    if observed_outcome not in OBSERVED_OUTCOMES:
        raise ManifestError(
            "machine evidence observed_outcome is invalid: " + str(observed_outcome)
        )
    review_required = bool(
        fields.pop("human_review_required", scenario.get("human_review_required", False))
    )
    review_override = fields.pop("human_review", None)
    if review_override is not None and not isinstance(review_override, Mapping):
        raise ManifestError("human_review must be an object when supplied")
    review_status = "PENDING" if review_required else "NOT_REQUIRED"
    review = {
        "required": review_required,
        "status": review_status,
        "packet_id": None,
        "disagreement_preserved": True,
        "unresolved_decision": review_required,
    }
    if review_override is not None:
        review.update(review_override)
    if manifest.get("run_mode") == "SEALED_FINAL":
        if review_required:
            if (
                review_override is None
                or review.get("required") is not True
                or review.get("status") != "COMPLETE"
                or not review.get("packet_id")
                or review.get("unresolved_decision") is not False
            ):
                raise ManifestError(
                    "SEALED_FINAL required human review must be explicitly COMPLETE"
                )
        elif review_override is not None and review.get("status") != "NOT_REQUIRED":
            raise ManifestError(
                "SEALED_FINAL optional human review must be explicitly NOT_REQUIRED"
            )
        review["required"] = review_required
        review["status"] = "COMPLETE" if review_required else "NOT_REQUIRED"
        review["unresolved_decision"] = False
    assessment_binding = _default_assessment_binding(scenario)
    assessment_binding.update(fields.pop("assessment_binding", {}))
    role_context = _default_role_context(scenario)
    role_context.update(fields.pop("role_context", {}))
    calls = _default_calls(fields.pop("calls", None))
    fixture_version = fields.pop(
        "fixture_version", assessment_binding.get("fixture_version", "synthetic_assessment.v1")
    )
    raw_d4e_ids = fields.pop("d4e_ids", scenario.get("d4e_ids", ["D4E-20"]))
    raw_d4sup_ids = fields.pop("d4sup_ids", scenario.get("d4sup_ids", ["D4SUP-15"]))
    for field_name, raw_ids, allowed_ids in (
        ("d4e_ids", raw_d4e_ids, D4E_IDS),
        ("d4sup_ids", raw_d4sup_ids, D4SUP_IDS),
    ):
        if not isinstance(raw_ids, list):
            raise ManifestError(f"{field_name} must be a list")
        if field_name == "d4e_ids" and not raw_ids:
            raise ManifestError("d4e_ids must contain at least one ID")
        if any(not isinstance(value, str) for value in raw_ids):
            raise ManifestError(f"{field_name} contains a non-string ID")
        if len(raw_ids) != len(set(raw_ids)):
            raise ManifestError(f"{field_name} must not contain duplicate IDs")
        if any(value not in allowed_ids for value in raw_ids):
            raise ManifestError(f"{field_name} contains an invalid ID")

    evidence: dict[str, Any] = {
        "schema_version": "d4-evidence-v1",
        "run_id": run_id,
        "run_mode": manifest.get("run_mode", "FAST_REGRESSION"),
        "case_id": fields.pop("case_id", scenario.get("case_id", "D4E-01-FOUNDATION-CASE")),
        "d4e_ids": sorted(raw_d4e_ids),
        "d4sup_ids": sorted(raw_d4sup_ids),
        "risk_domain": fields.pop("risk_domain", "FOUNDATION_REPRODUCIBILITY"),
        "split": split,
        "fixture_version": str(fixture_version),
        "fixture_sha256": fixture_sha,
        "git_commit": manifest.get("git_commit"),
        "route": fields.pop("route", "/api/v1/support/requests"),
        "expected_invariant": fields.pop(
            "expected_invariant", "machine evidence remains schema-shaped and traceable"
        ),
        "failure_type": fields.pop("failure_type", None),
        "expected_response_class": expected_response_class,
        "observed_response_class": observed_response_class,
        "observed_outcome": observed_outcome,
        "calls": calls,
        "human_review": review,
        "request_id": fields.pop("request_id", None),
        "trace_id": fields.pop("trace_id", None),
        "transaction_id": fields.pop("transaction_id", None),
        "stage": fields.pop("stage", None),
        "target_identity": fields.pop(
            "target_identity", _manifest_value(manifest, "provider_identities", "target")
        ),
        "model_identity": fields.pop(
            "model_identity", _manifest_value(manifest, "runtime", "model")
        ),
        "template_identity": fields.pop("template_identity", None),
        "policy_identity": fields.pop("policy_identity", None),
        "evidence_bundle": fields.pop(
            "evidence_bundle", {"id": None, "hash": None, "status": "NOT_ASSESSED"}
        ),
        "http_status": fields.pop("http_status", None),
        "product_status": fields.pop("product_status", None),
        "safety": fields.pop("safety", {}),
        "citation_support": fields.pop("citation_support", {}),
        "answerability": fields.pop(
            "answerability",
            {
                "expected": expected,
                "observed": observed_response_class,
                "false_refusal": False,
                "false_answer": False,
            },
        ),
        "assessment_binding": assessment_binding,
        "role_context": role_context,
        "real_student_data": fields.pop("real_student_data", False),
        "cloud_fallback": fields.pop("cloud_fallback", False),
    }
    for key in EVIDENCE_OPTIONAL_FIELDS:
        if key in fields:
            evidence[key] = fields.pop(key)
    if fields:
        raise ManifestError(
            "unknown machine-evidence fields: " + ", ".join(sorted(fields))
        )
    return normalize_machine_evidence(evidence)


def normalize_machine_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and validate a machine-evidence mapping without data repair."""

    unknown = set(evidence) - EVIDENCE_ALLOWED_FIELDS
    if unknown:
        raise ManifestError(
            "machine evidence contains unknown top-level fields: "
            + ", ".join(sorted(unknown))
        )
    missing = [field for field in EVIDENCE_REQUIRED_FIELDS if field not in evidence]
    if missing:
        raise ManifestError(
            "machine evidence missing required fields: " + ", ".join(missing)
        )
    result = deepcopy(dict(evidence))
    _reject_secret_fields(result)
    try:
        validate_run_id(result["run_id"])
    except Exception as exc:
        raise ManifestError(str(exc)) from exc
    if result["run_mode"] not in {"FAST_REGRESSION", "FULL_ENGINEERING", "SEALED_FINAL"}:
        raise ManifestError("machine evidence run_mode is invalid")
    if result["split"] not in DATASET_SPLITS:
        raise ManifestError("machine evidence split is invalid")
    if not isinstance(result["case_id"], str) or not result["case_id"]:
        raise ManifestError("machine evidence case_id is required")
    for field in ("fixture_sha256",):
        try:
            validate_sha256_hex(result[field])
        except Exception as exc:
            raise ManifestError(f"{field} is invalid: {exc}") from exc
    commit = result["git_commit"]
    if not isinstance(commit, str) or len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise ManifestError("machine evidence git_commit is invalid")
    if result["expected_response_class"] not in EXPECTED_RESPONSE_CLASSES:
        raise ManifestError("machine evidence expected_response_class is invalid")
    if result["observed_response_class"] not in OBSERVED_RESPONSE_CLASSES:
        raise ManifestError("machine evidence observed_response_class is invalid")
    if result["observed_outcome"] not in OBSERVED_OUTCOMES:
        raise ManifestError("machine evidence observed_outcome is invalid")
    if result["failure_type"] not in FAILURE_TYPES:
        raise ManifestError("machine evidence failure_type is invalid")
    for field in ("route", "expected_invariant", "fixture_version"):
        if not isinstance(result[field], str) or not result[field].strip():
            raise ManifestError(f"machine evidence {field} is required")
    if result["http_status"] is not None and (
        not isinstance(result["http_status"], int)
        or isinstance(result["http_status"], bool)
        or not 100 <= result["http_status"] <= 599
    ):
        raise ManifestError("machine evidence http_status is invalid")
    calls = result["calls"]
    if not isinstance(calls, Mapping) or set(calls) != set(CALL_FIELDS):
        raise ManifestError("machine evidence calls must contain exactly the D4 call fields")
    for field in CALL_FIELDS:
        if not isinstance(calls[field], int) or isinstance(calls[field], bool) or calls[field] < 0:
            raise ManifestError(f"machine evidence call count is invalid: {field}")
    review = result["human_review"]
    if not isinstance(review, Mapping) or not all(
        field in review for field in ("required", "status", "disagreement_preserved", "unresolved_decision")
    ):
        raise ManifestError("machine evidence human_review is incomplete")
    if review["status"] not in {"NOT_REQUIRED", "PENDING", "COMPLETE", "ESCALATED"}:
        raise ManifestError("machine evidence human_review.status is invalid")
    result.setdefault("real_student_data", False)
    result.setdefault("cloud_fallback", False)
    if result.get("real_student_data") is not False or result.get("cloud_fallback") is not False:
        raise ManifestError("machine evidence must set real_student_data/cloud_fallback false")
    binding = result["assessment_binding"]
    if not isinstance(binding, Mapping):
        raise ManifestError("assessment_binding must be an object")
    for field in ("fixture_mode", "fixture_identity", "fixture_version", "source_identity", "target_identity", "compatibility_mapping"):
        if field not in binding:
            raise ManifestError(f"assessment_binding.{field} is required")
    mode = binding["fixture_mode"]
    if mode not in {"exact_d3_fixture", "legacy_compatibility_fixture"}:
        raise ManifestError("assessment_binding.fixture_mode is invalid")
    if binding["compatibility_mapping"] != compatibility_mapping_for(mode):
        raise ManifestError("assessment_binding compatibility mapping is invalid")
    for field in (
        "fixture_identity",
        "fixture_version",
        "source_identity",
        "target_identity",
        "compatibility_mapping",
    ):
        if not isinstance(binding[field], str) or not binding[field].strip():
            raise ManifestError(f"assessment_binding.{field} is invalid")
    digest = binding.get("assessment_id_digest")
    if digest is not None:
        try:
            validate_sha256_hex(digest)
        except Exception as exc:
            raise ManifestError("assessment_binding.assessment_id_digest is invalid") from exc
    role = result["role_context"]
    if not isinstance(role, Mapping) or not all(
        field in role for field in ("actor_role", "target_role", "projection_mode", "authorization_source", "unavailable_actor_decision")
    ):
        raise ManifestError("role_context is incomplete")
    if role.get("actor_role") not in {"student", "teacher", "reviewer"}:
        raise ManifestError("role_context.actor_role is invalid")
    if role.get("target_role") not in {"student", "teacher", "parent", "admin", "reviewer"}:
        raise ManifestError("role_context.target_role is invalid")
    if role.get("projection_mode") not in {
        "server_derived",
        "approved_in_process_projection",
        "forged_target_role_attempt",
    }:
        raise ManifestError("role_context.projection_mode is invalid")
    # Normalize set-like ID lists, but never repair missing/invalid content.
    for field in ("d4e_ids", "d4sup_ids"):
        if not isinstance(result[field], list):
            raise ManifestError(f"{field} must be a list")
        if any(not isinstance(value, str) for value in result[field]):
            raise ManifestError(f"{field} contains a non-string ID")
        if len(result[field]) != len(set(result[field])):
            raise ManifestError(f"{field} must not contain duplicate IDs")
        values = sorted(result[field])
        allowed_ids = D4E_IDS if field == "d4e_ids" else D4SUP_IDS
        if field == "d4e_ids" and not values:
            raise ManifestError("d4e_ids must contain at least one ID")
        if any(not isinstance(value, str) or value not in allowed_ids for value in values):
            raise ManifestError(f"{field} contains an invalid ID")
        result[field] = values
    answerability = result["answerability"]
    if not isinstance(answerability, Mapping):
        raise ManifestError("answerability must be an object")
    if answerability.get("expected") != result["expected_response_class"]:
        raise ManifestError("answerability.expected must match expected_response_class")
    if answerability.get("observed") != result["observed_response_class"]:
        raise ManifestError("answerability.observed must match observed_response_class")
    if "artifacts" in result:
        if not isinstance(result["artifacts"], list):
            raise ManifestError("artifacts must be a list")
        result["artifacts"] = [validate_result_path(path) for path in result["artifacts"]]
    if review["status"] == "PENDING" and review["unresolved_decision"] is not True:
        raise ManifestError("pending machine evidence review must preserve unresolved_decision")
    if review["status"] == "COMPLETE":
        if review["required"] is not True or not review.get("packet_id"):
            raise ManifestError("complete machine evidence review requires packet_id")
        if review["unresolved_decision"] is not False:
            raise ManifestError("complete machine evidence review cannot be unresolved")
    if result["run_mode"] == "SEALED_FINAL":
        if review["required"] is True and review["status"] != "COMPLETE":
            raise ManifestError("SEALED_FINAL required machine evidence review must be complete")
        if review["required"] is False and review["status"] != "NOT_REQUIRED":
            raise ManifestError("SEALED_FINAL optional machine evidence review must be not required")
        if review["unresolved_decision"] is not False:
            raise ManifestError("SEALED_FINAL machine evidence review cannot be unresolved")
    return result


# Explicit alias for callers that prefer the noun first.
new_machine_evidence = build_machine_evidence
new_evidence_shell = build_machine_evidence
normalize_evidence = normalize_machine_evidence
