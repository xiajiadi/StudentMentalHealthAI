"""A-phase contract, schema, OpenAPI, and cross-cutting rule tests.

This test suite intentionally covers only contract assets. It does not start
services, download models, call providers, or implement B-phase functionality.
"""

from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    import jsonschema
except ImportError:  # pragma: no cover - reported as a test failure below
    jsonschema = None


ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "00_architecture"
SCHEMAS = ARCH / "schemas"
FIXTURES = ARCH / "fixtures"
CONTRACTS = ROOT / "CONTRACTS.md"
OPENAPI = ARCH / "openapi.v1.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def local_ref(document: dict[str, Any], reference: str) -> Any:
    if not reference.startswith("#/"):
        raise AssertionError(f"external or malformed reference: {reference}")
    value: Any = document
    for part in reference[2:].split("/"):
        value = value[part.replace("~1", "/").replace("~0", "~")]
    return value


class ContractSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if jsonschema is None:
            raise AssertionError(
                "jsonschema is required for A-phase validation; install it in a project environment"
            )
        cls.schemas = {
            name: load_json(SCHEMAS / name)
            for name in (
                "assessment.v1.schema.json",
                "knowledge.v1.schema.json",
                "generation.v1.schema.json",
                "config.v1.schema.json",
                "logging.v1.schema.json",
            )
        }
        cls.validators = {}
        for name, schema in cls.schemas.items():
            validator_cls = jsonschema.validators.validator_for(schema)
            validator_cls.check_schema(schema)
            cls.validators[name] = validator_cls(schema)

    def assert_valid(self, schema_name: str, value: dict[str, Any]) -> None:
        errors = sorted(
            self.validators[schema_name].iter_errors(value),
            key=lambda error: list(error.path),
        )
        self.assertEqual(
            [],
            errors,
            msg=f"{schema_name} rejected valid fixture: "
            + "; ".join(error.message for error in errors),
        )

    def assert_invalid(self, schema_name: str, value: dict[str, Any]) -> None:
        errors = list(self.validators[schema_name].iter_errors(value))
        self.assertTrue(errors, msg=f"{schema_name} accepted an invalid fixture")

    def test_all_positive_fixtures_validate(self) -> None:
        mapping = {
            "valid_assessment.json": "assessment.v1.schema.json",
            "valid_knowledge_document.json": "knowledge.v1.schema.json",
            "valid_knowledge_chunk.json": "knowledge.v1.schema.json",
            "valid_generation_request.json": "generation.v1.schema.json",
            "valid_generation_result.json": "generation.v1.schema.json",
            "valid_config.json": "config.v1.schema.json",
            "valid_log.json": "logging.v1.schema.json",
        }
        for fixture_name, schema_name in mapping.items():
            with self.subTest(fixture=fixture_name):
                self.assert_valid(schema_name, load_json(FIXTURES / fixture_name))

    def test_assessment_required_fields_and_high_risk_invariant(self) -> None:
        assessment = load_json(FIXTURES / "valid_assessment.json")

        missing_risk = deepcopy(assessment)
        del missing_risk["risk"]
        self.assert_invalid("assessment.v1.schema.json", missing_risk)

        high_without_review = deepcopy(assessment)
        high_without_review["risk"]["level"] = "high"
        high_without_review["risk"]["need_human_review"] = False
        self.assert_invalid("assessment.v1.schema.json", high_without_review)

        unclassified = deepcopy(assessment)
        unclassified["risk"]["level"] = "not_assessed"
        unclassified["risk"]["need_human_review"] = False
        unclassified["dimensions"]["emotion"].update(
            {"theta": None, "se": None, "score": None, "band": "unknown", "interpretation_status": "not_scored"}
        )
        self.assert_valid("assessment.v1.schema.json", unclassified)

    def test_knowledge_status_and_unknown_field_are_rejected(self) -> None:
        chunk = load_json(FIXTURES / "valid_knowledge_chunk.json")
        extra_field = deepcopy(chunk)
        extra_field["unapproved_runtime_instruction"] = "must not be indexed"
        self.assert_invalid("knowledge.v1.schema.json", extra_field)

        pending_chunk = deepcopy(chunk)
        pending_chunk["review_status"] = "pending"
        self.assertFalse(self.knowledge_is_production_eligible(pending_chunk))

        restricted_chunk = deepcopy(chunk)
        restricted_chunk["rights_status"] = "restricted"
        self.assertFalse(self.knowledge_is_production_eligible(restricted_chunk))

    @staticmethod
    def knowledge_is_production_eligible(chunk: dict[str, Any]) -> bool:
        return (
            chunk.get("review_status") == "approved"
            and chunk.get("rights_status") == "verified"
        )

    def test_generation_blocking_and_review_invariants(self) -> None:
        result = load_json(FIXTURES / "valid_generation_result.json")

        blocked_with_content = deepcopy(result)
        blocked_with_content["status"] = "safety_blocked"
        self.assert_invalid("generation.v1.schema.json", blocked_with_content)

        approved_without_review = deepcopy(result)
        approved_without_review["status"] = "approved"
        approved_without_review["review"]["status"] = "pending"
        self.assert_invalid("generation.v1.schema.json", approved_without_review)

        review_required_but_generated = deepcopy(result)
        review_required_but_generated["safety"]["human_review_required"] = True
        self.assert_invalid("generation.v1.schema.json", review_required_but_generated)

    def test_config_does_not_accept_secret_values_or_unknown_keys(self) -> None:
        config = load_json(FIXTURES / "valid_config.json")

        with_secret = deepcopy(config)
        with_secret["api_key"] = "never-commit-secrets"
        self.assert_invalid("config.v1.schema.json", with_secret)

        with_url_value = deepcopy(config)
        with_url_value["components"]["database"]["url"] = (
            "mysql://user:password@localhost/db"
        )
        self.assert_invalid("config.v1.schema.json", with_url_value)

    def test_logging_requires_traceability_and_rejects_sensitive_fields(self) -> None:
        log = load_json(FIXTURES / "valid_log.json")

        missing_trace = deepcopy(log)
        del missing_trace["trace_id"]
        self.assert_invalid("logging.v1.schema.json", missing_trace)

        sensitive_metadata = deepcopy(log)
        sensitive_metadata["metadata"]["raw_response"] = "private"
        self.assert_invalid("logging.v1.schema.json", sensitive_metadata)

        self.assertFalse(self.contains_forbidden_log_key(log))

    def test_id_and_version_policy_is_explicit_and_machine_checked(self) -> None:
        contract_text = CONTRACTS.read_text(encoding="utf-8")
        for required_phrase in (
            "### 1.2 ID",
            "### 1.3 版本",
            "### 1.4 Config Contract",
            "### 1.5 ID Contract",
            "### 1.6 Version Contract",
            "### 1.7 Logging Contract",
            "v0.1.0",
        ):
            with self.subTest(phrase=required_phrase):
                self.assertIn(required_phrase, contract_text)

        assessment = load_json(FIXTURES / "valid_assessment.json")
        self.assertRegex(assessment["assessment_id"], r"^ASSESS_[A-Za-z0-9][A-Za-z0-9_.-]*$")
        self.assertRegex(assessment["subject_id"], r"^SUBJ_[A-Za-z0-9][A-Za-z0-9_.-]*$")
        self.assertEqual("assessment.v1", assessment["schema_version"])
        for version in assessment["provenance"].values():
            self.assertTrue(version)

        generation = load_json(FIXTURES / "valid_generation_result.json")
        self.assertEqual("generation.v1", generation["schema_version"])
        self.assertRegex(generation["generation_id"], r"^GEN_[A-Za-z0-9][A-Za-z0-9_.-]*$")
        self.assertTrue(generation["provenance"]["prompt_version"])
        self.assertTrue(generation["provenance"]["model_version"])
        self.assertTrue(generation["provenance"]["runtime_version"])

    def test_governance_skeleton_is_complete(self) -> None:
        root_documents = (
            "PROJECT.md",
            "ARCHITECTURE.md",
            "ROADMAP.md",
            "CONTRACTS.md",
            "MODULES.md",
            "AGENT_RULES.md",
        )
        for document_name in root_documents:
            with self.subTest(document=document_name):
                self.assertTrue((ROOT / document_name).is_file())

        expected_modules = (
            "00_architecture",
            "01_cat-engine",
            "02_item-bank",
            "03_assessment-adapter",
            "04_knowledge-pipeline",
            "05_rag-engine",
            "06_llm-runtime",
            "07_prompt-engine",
            "08_safety-engine",
            "09_backend",
            "10_frontend",
            "11_database",
            "12_evaluation",
            "13_deployment",
            "14_docs",
            "15_demo",
        )
        required_task_headings = ("职责", "输入", "输出", "禁止事项", "接口", "验收标准", "交付物")
        for module in expected_modules:
            task_path = ROOT / module / "TASK.md"
            with self.subTest(module=module):
                self.assertTrue(task_path.is_file())
                task_text = task_path.read_text(encoding="utf-8")
                for heading in required_task_headings:
                    self.assertIn(heading, task_text)

        architecture_text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("## 3. 主数据流", architecture_text)
        self.assertIn("## 4. 信任边界", architecture_text)
        self.assertIn("## 8. 配置边界", architecture_text)
        self.assertIn("## 7. 可观测性与审计", architecture_text)

    @staticmethod
    def contains_forbidden_log_key(value: Any) -> bool:
        forbidden = {
            "name",
            "student_name",
            "student_id",
            "phone",
            "email",
            "raw_response",
            "raw_answers",
            "prompt",
            "context",
            "secret",
            "token",
            "password",
        }
        if isinstance(value, dict):
            return any(
                key.lower() in forbidden
                or ContractSchemaTests.contains_forbidden_log_key(child)
                for key, child in value.items()
            )
        if isinstance(value, list):
            return any(ContractSchemaTests.contains_forbidden_log_key(item) for item in value)
        return False

    def test_contract_document_examples_are_parseable_and_schema_valid(self) -> None:
        text = CONTRACTS.read_text(encoding="utf-8")
        blocks = re.findall(r"~~~json\s*(.*?)\s*~~~", text, flags=re.DOTALL)
        self.assertGreaterEqual(len(blocks), 7)

        schema_by_version = {
            "assessment.v1": "assessment.v1.schema.json",
            "knowledge.v1": "knowledge.v1.schema.json",
            "generation.v1": "generation.v1.schema.json",
        }
        versioned_blocks = 0
        for index, block in enumerate(blocks):
            with self.subTest(example=index + 1):
                value = json.loads(block)
                version = value.get("schema_version")
                if version is not None:
                    versioned_blocks += 1
                    self.assertIn(version, schema_by_version)
                    self.assert_valid(schema_by_version[version], value)
        self.assertEqual(5, versioned_blocks)


class OpenApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = load_json(OPENAPI)

    def test_openapi_document_has_valid_top_level_shape(self) -> None:
        document = self.document
        self.assertEqual("3.1.0", document.get("openapi"))
        self.assertEqual("0.1.0", document["info"]["version"])
        self.assertIsInstance(document.get("paths"), dict)
        self.assertIsInstance(document.get("components"), dict)

    def test_public_paths_and_methods_are_complete(self) -> None:
        expected = {
            ("GET", "/api/v1/health"),
            ("GET", "/api/v1/assessments"),
            ("POST", "/api/v1/assessments"),
            ("POST", "/api/v1/assessments/{assessment_id}/responses"),
            ("POST", "/api/v1/assessments/{assessment_id}/complete"),
            ("POST", "/api/v1/retrievals"),
            ("POST", "/api/v1/safety/checks"),
            ("POST", "/api/v1/generations"),
            ("GET", "/api/v1/reports/{report_id}"),
            ("POST", "/api/v1/reports/{report_id}/reviews"),
        }
        actual = {
            (method.upper(), path)
            for path, path_item in self.document["paths"].items()
            for method in path_item
            if method.lower()
            in {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
        }
        self.assertEqual(expected, actual)

    def test_operations_have_unique_ids_responses_and_resolvable_refs(self) -> None:
        operation_ids: set[str] = set()
        for path, path_item in self.document["paths"].items():
            path_parameters = path_item.get("parameters", [])
            path_names = {
                self.resolve_parameter(parameter)["name"]
                for parameter in path_parameters
            }
            for method, operation in path_item.items():
                if method.lower() not in {
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                    "head",
                    "options",
                    "trace",
                }:
                    continue
                operation_id = operation.get("operationId")
                self.assertTrue(operation_id)
                self.assertNotIn(operation_id, operation_ids)
                operation_ids.add(operation_id)
                self.assertTrue(operation.get("responses"))
                for response in operation["responses"].values():
                    resolved = self.resolve(response)
                    self.assertTrue(resolved.get("description"))
                for parameter in operation.get("parameters", []):
                    resolved = self.resolve_parameter(parameter)
                    if resolved.get("in") == "path":
                        path_names.add(resolved["name"])
                for parameter_name in re.findall(r"{([^}]+)}", path):
                    self.assertIn(parameter_name, path_names)
                if "requestBody" in operation:
                    request_body = self.resolve(operation["requestBody"])
                    self.assertTrue(request_body.get("required"))
                    content = request_body.get("content", {})
                    self.assertIn("application/json", content)
                    schema = content["application/json"]["schema"]
                    resolved_schema = self.resolve(schema)
                    self.assertTrue(
                        "$ref" in schema or "type" in resolved_schema,
                        msg=f"request schema is not resolvable for {method.upper()} {path}",
                    )

    def test_contract_schema_links_exist(self) -> None:
        schemas = self.document["components"]["schemas"]
        expected = {
            "schemas/assessment.v1.schema.json",
            "schemas/knowledge.v1.schema.json",
            "schemas/generation.v1.schema.json",
        }
        linked = {
            value["x-contract-schema"]
            for value in schemas.values()
            if "x-contract-schema" in value
        }
        self.assertTrue(expected.issubset(linked))
        for relative_path in linked:
            self.assertTrue((ARCH / relative_path).is_file(), relative_path)

    def resolve(self, value: Any) -> Any:
        if isinstance(value, dict) and "$ref" in value:
            return local_ref(self.document, value["$ref"])
        return value

    def resolve_parameter(self, value: Any) -> dict[str, Any]:
        resolved = self.resolve(value)
        self.assertIsInstance(resolved, dict)
        self.assertIn("name", resolved)
        self.assertIn("in", resolved)
        return resolved


if __name__ == "__main__":
    unittest.main(verbosity=2)
