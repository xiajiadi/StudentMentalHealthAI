"""Export the actual additive Backend OpenAPI candidate."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import sys
from pathlib import Path


def _problem_response(status: int, description: str) -> dict[str, object]:
    """Describe the Backend's RFC 9457 error response for the live candidate."""
    return {
        "description": f"{description} ({status})",
        "content": {
            "application/problem+json": {
                "schema": {"$ref": "#/components/schemas/ProblemDetails"}
            }
        },
    }


def _apply_runtime_contract(
    document: dict[str, object], root_contract: dict[str, object]
) -> dict[str, object]:
    """Reconcile FastAPI's generated shape with the actual Backend boundary.

    The root OpenAPI document is frozen. This candidate documents the additive
    Backend routes and the shared problem-details middleware without modifying
    the root contract or runtime.
    """
    # Keep every existing root operation as the compatibility baseline. The
    # candidate adds runtime routes around it; it must not silently weaken the
    # frozen request/response shapes while documenting the live error media.
    for path, root_path_item in root_contract.get("paths", {}).items():
        if path not in document["paths"]:
            continue
        for method, root_operation in root_path_item.items():
            if method in document["paths"][path]:
                document["paths"][path][method] = deepcopy(root_operation)

    components = document.setdefault("components", {})
    root_components = root_contract.get("components", {})
    for component_type in ("schemas", "parameters", "responses"):
        components.setdefault(component_type, {}).update(
            deepcopy(root_components.get(component_type, {}))
        )
    schemas = components.setdefault("schemas", {})
    schemas["ProblemDetails"] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "type",
            "title",
            "status",
            "detail",
            "instance",
            "code",
            "retryable",
            "request_id",
            "trace_id",
        ],
        "properties": {
            "type": {"type": "string"},
            "title": {"type": "string"},
            "status": {"type": "integer", "minimum": 400, "maximum": 599},
            "detail": {"type": "string"},
            "instance": {"type": ["string", "null"]},
            "code": {"type": "string"},
            "retryable": {"type": "boolean"},
            "request_id": {"type": "string", "pattern": "^REQ_[A-Za-z0-9][A-Za-z0-9_.-]*$"},
            "trace_id": {"type": "string", "pattern": "^TRACE_[A-Za-z0-9][A-Za-z0-9_.-]*$"},
        },
    }
    components["securitySchemes"] = {
        "sessionCookie": {
            "type": "apiKey",
            "in": "cookie",
            "name": "smhai_dev_session",
            "description": "Local Round 1 opaque server-side session cookie.",
        },
        "csrfToken": {
            "type": "apiKey",
            "in": "header",
            "name": "X-CSRF-Token",
            "description": "Session-bound token required for state-changing requests.",
        },
    }

    public_paths = {
        "/health/live",
        "/health/ready",
        "/health/dependencies",
        "/api/v1/health",
        "/api/v1/auth/login",
    }
    csrf_paths = {
        "/api/v1/auth/logout",
        "/api/v1/assessments",
        "/api/v1/assessments/{assessment_id}/responses",
        "/api/v1/assessments/{assessment_id}/complete",
        "/api/v1/retrievals",
        "/api/v1/safety/checks",
        "/api/v1/support/requests",
        "/api/v1/generations",
        "/api/v1/reports/{report_id}/reviews",
    }
    for path, path_item in document["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            responses = operation.setdefault("responses", {})
            if path not in public_paths:
                operation["security"] = (
                    [{"sessionCookie": [], "csrfToken": []}]
                    if path in csrf_paths
                    else [{"sessionCookie": []}]
                )
                responses.setdefault("401", _problem_response(401, "Authentication required"))
                responses.setdefault("403", _problem_response(403, "Forbidden"))
            elif path == "/api/v1/auth/login":
                # Invalid credentials are a normal, documented login outcome;
                # login itself does not require an existing session.
                responses.setdefault("401", _problem_response(401, "Authentication failed"))
                responses.setdefault("403", _problem_response(403, "Mutation origin rejected"))
            if path.startswith("/api/v1/") and method == "post":
                responses.setdefault("409", _problem_response(409, "Workflow conflict"))
            if path.startswith("/api/v1/") and (
                "{" in path or method == "post"
            ):
                responses.setdefault("404", _problem_response(404, "Resource not found"))
            if path in {"/api/v1/auth/login", "/api/v1/support/requests", "/api/v1/generations"}:
                responses.setdefault("429", _problem_response(429, "Rate limit exceeded"))
            if path in {
                "/api/v1/retrievals",
                "/api/v1/safety/checks",
                "/api/v1/support/requests",
                "/api/v1/generations",
            }:
                for status, description in (
                    (502, "Dependency response invalid"),
                    (503, "Dependency unavailable"),
                    (504, "Dependency timeout"),
                ):
                    responses.setdefault(str(status), _problem_response(status, description))
            response_422 = responses.get("422")
            if not isinstance(response_422, dict) or "$ref" not in response_422:
                responses["422"] = _problem_response(422, "Request validation failed")
            responses.setdefault("500", _problem_response(500, "Internal server error"))

    # Re-apply the root operation's existing status entries after adding
    # runtime-only statuses. This keeps frozen response references intact
    # while retaining candidate-only 401/403/5xx documentation.
    for path, root_path_item in root_contract.get("paths", {}).items():
        if path not in document["paths"]:
            continue
        for method, root_operation in root_path_item.items():
            if method not in document["paths"][path]:
                continue
            generated_operation = document["paths"][path][method]
            merged_operation = deepcopy(root_operation)
            merged_responses = merged_operation.setdefault("responses", {})
            for status, response in generated_operation.get("responses", {}).items():
                merged_responses.setdefault(status, response)
            if "security" in generated_operation:
                merged_operation["security"] = generated_operation["security"]
            document["paths"][path][method] = merged_operation
    return document


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(project_root / "09_backend" / "src"))
    from smhai_backend.app_factory import create_app

    args.output.parent.mkdir(parents=True, exist_ok=True)
    root_contract = json.loads(
        (project_root / "00_architecture" / "openapi.v1.json").read_text(encoding="utf-8")
    )
    candidate = _apply_runtime_contract(create_app().openapi(), root_contract)
    args.output.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
