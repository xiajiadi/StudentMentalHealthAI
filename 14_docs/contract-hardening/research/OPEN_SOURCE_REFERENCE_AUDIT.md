# Open-Source Reference Audit

Audit date: 2026-09-06 (Asia/Shanghai)  
Purpose: resolve the contract-hardening design uncertainties before coding.

The sources below were opened and read on the audit date. Versions are recorded
where the source or local tool exposes one. The audit stops here because the
required choices are resolved and remaining uncertainty is testable locally.

| Reference | Observed source/version | Decision | Rationale |
|---|---|---|---|
| OpenAPI Specification | https://spec.openapis.org/oas/latest.html; latest published 3.2.0 dated 2025-09-19; 3.1.0 remains published | Adopt OpenAPI 3.1.x for this round | The user constraint and existing FastAPI/OpenAPI 3.1 contract take precedence over the newer 3.2 publication. Do not upgrade the root contract. |
| FastAPI response models | https://fastapi.tiangolo.com/tutorial/response-model/ | Adopt response_model with Pydantic DTOs | FastAPI documents response_model as the source for response documentation, validation, filtering, and client generation. |
| FastAPI path operation configuration | https://fastapi.tiangolo.com/tutorial/path-operation-configuration/ | Adopt explicit operation_id, status codes, summaries, and responses at route decorators | Operation IDs are public client-generation names and must be deterministic. |
| FastAPI client generation guidance | https://fastapi.tiangolo.com/advanced/generate-clients/ | Adopt source OpenAPI to Hey API generation | The documented flow generates a TypeScript client from the running OpenAPI document; no hand-edited generated files. |
| Redocly CLI repository/docs | https://github.com/Redocly/redocly-cli and https://redocly.com/docs/cli/; local latest query 2.51.2 | Adopt Redocly CLI as the only governance linter | Matches the hardening constraint. Do not add Spectral or Vacuum. |
| Redocly Respect | https://redocly.com/docs/cli/commands/respect/; docs state Respect supports Arazzo 1.0.1 descriptions only | Adopt Respect execution with Arazzo 1.0.1 | This is the explicit compatibility check required before selecting Arazzo version. |
| oasdiff | https://github.com/oasdiff/oasdiff; local binary 1.28.0 | Adopt oasdiff breaking-change detection | It compares the frozen root document to the candidate without requiring a second compatibility framework. |
| Schemathesis | https://github.com/schemathesis/schemathesis and https://schemathesis.readthedocs.io/en/stable/; local runner 4.25.2 | Adopt live property, negative, fuzz, and stateful checks where the API semantics support them | Existing integration evidence already uses Schemathesis; this round adds candidate-specific configuration and evidence. |
| Arazzo Specification | https://spec.openapis.org/arazzo/latest.html; latest page is 1.1.0 | Use 1.0.1, not latest | Respect's official docs explicitly support 1.0.1 only. Workflows must reference real operationIds and must not invent Links. |
| Hey API | https://github.com/hey-api/openapi-ts and FastAPI's Hey API example; exact project dependency 0.99.0 | Keep exact @hey-api/openapi-ts 0.99.0 | This is the accepted integration generator and the user explicitly forbids upgrading it in this round. Regenerate twice for determinism. |
| RFC 9457 | https://www.rfc-editor.org/rfc/rfc9457.html | Adopt one typed Problem Details response family | The current runtime already uses application/problem+json; hardening documents and types that path instead of adding another error framework. |
| Zalando RESTful API Guidelines | https://opensource.zalando.com/restful-api-guidelines/ | Adopt machine-readable error codes and stable resource/API conventions selectively | Use the guidance for predictable HTTP semantics and machine handling; keep the project's existing envelope and safety boundary. |
| MADR | https://adr.github.io/madr/ | Adopt a concise decision record | The technical decision artifact will record context, decision, alternatives, and consequences without adding process ceremony. |
| Gitleaks | https://github.com/gitleaks/gitleaks; local binary 8.30.1 | Adopt pre-Git, post-ignore, post-implementation, and history scans | Gitleaks is the requested secret detector. Synthetic hash-like fixture false positives are scoped in .gitleaks.toml and remain visible in evidence. |

## Decisions carried into implementation

1. The candidate is emitted by FastAPI from source DTOs. There is no
   post-generation patch step.
2. Root operation IDs are preserved byte-for-byte in the candidate where their
   route remains the same. New routes receive stable explicit IDs.
3. RFC 9457 remains the single error runtime path. ProblemDetails and
   validation field errors become documented Pydantic models.
4. Session-cookie and CSRF security declarations are generated from FastAPI
   dependencies so the document reflects runtime enforcement.
5. RAG provenance keeps chunk/document/content-hash/rank through the
   orchestrator, persistence, report reconstruction, and API projection.
6. NOT_RUN uses a null model_id. Controlled synthetic output is an explicit
   source label. The frozen generation.v1 schema is not modified.
7. Redocly CLI 2.51.2, oasdiff 1.28.0, Schemathesis 4.25.2, Hey API 0.99.0,
   and Gitleaks 8.30.1 are recorded as the locally selected tool versions.
