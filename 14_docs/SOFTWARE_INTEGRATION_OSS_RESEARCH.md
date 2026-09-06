# Software Integration Round 1 — OSS Research Record

Status: `STAGE 0 COMPLETE`  
Inspection date: `2026-09-05`  
Scope: integration architecture and tooling only; all project data remains synthetic.

## Research method

The references below were checked against their first-party repositories or documentation. The repository is not a Git checkout, so upstream revisions are recorded explicitly rather than inferred from a local branch. Local package/runtime availability was checked separately and is recorded as evidence in the Round 1 report.

## Decisions

| Reference | Exact revision/version checked | Relevant pattern | Decision |
| --- | --- | --- | --- |
| [FastAPI full-stack template](https://github.com/fastapi/full-stack-fastapi-template) | `master` at `cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7` | FastAPI + typed settings + database-backed full-stack development structure | Adopt the operational separation only: FastAPI app factory, environment configuration, and same-origin development topology. Do not copy its React, SQLModel, PostgreSQL, JWT, or deployment assumptions. |
| [Hey API openapi-ts](https://github.com/hey-api/hey-api) | repository `main` at `9d56b7e1aa05434a34d6e1dbb35b786d8f69dc4e`; npm `@hey-api/openapi-ts@0.99.0` | Deterministic OpenAPI-to-TypeScript generation and generated-only output | Adopt. The local Node is `v24.15.0`, npm is `12.0.2`, and the checked package declares `node >=22.18.0`; this is compatible without upgrading the existing frontend toolchain. Pin `0.99.0`. |
| [oasdiff](https://github.com/oasdiff/oasdiff) | `v1.28.0` at `f7318d9` | Breaking/additive OpenAPI diff and changelog output | Adopt exact `v1.28.0` when the Windows binary is available. Do not depend on Go or Docker for the baseline because neither is installed on this host; an unavailable executable is an explicit evidence gap, not a fabricated pass. |
| [Schemathesis CLI](https://github.com/schemathesis/schemathesis) | PyPI `4.25.2`; current CLI documentation uses `schemathesis run <schema-url>` | Property-based tests against a live OpenAPI service, with headers/configuration and JUnit reporting | Adopt exact `4.25.2` in a disposable synthetic environment. Use the current `run` CLI and protected-route hooks/headers; exclude only destructive operations with a recorded alternate test. |
| [Cosmic Python](https://github.com/cosmicpython/book) | `main` at `d4522c44ed89eb320ad9eed2525d2af3b149bd3f` | Repository, Service Layer, Unit of Work, and bootstrap patterns | Adopt the boundary principle. The existing Database module already owns an async SQLAlchemy Unit of Work, so add only a thin Backend adapter and keep orchestration in Backend. Do not add a second ORM or DI framework. |
| [Docker Compose](https://docs.docker.com/compose/) | current official Compose documentation checked on `2026-09-05` | Service profiles, health-gated startup, and one-off migration commands | Use as a future deployment reference only. Docker is not installed locally and Round 1 explicitly does not require containerizing all AI modules. The Windows harness owns only processes it starts. |

## Adopted integration consequences

1. The Backend remains the application-plane composition root. Capability services remain thin loopback HTTP adapters around their accepted Python APIs.
2. The Database Unit of Work is a short-lived boundary per local persistence operation. It is never held while waiting for Safety, CAT, RAG, LLM Runtime, model loading, or another process.
3. Generated TypeScript is derived from the actual Backend Integration Candidate OpenAPI and is never hand-edited. Runtime behavior belongs in `RealApiProvider`.
4. Health is split into liveness, readiness, and capability detail. A listening socket alone is not readiness for a model/index service.
5. Full Docker/Kubernetes/service-mesh adoption is rejected for this round because it adds deployment scope without improving the required local synthetic vertical slice.

## Rejected or deferred alternatives

- React/SQLModel/PostgreSQL from the FastAPI template: incompatible with the existing Vue/MySQL architecture.
- Direct Browser → CAT/RAG/LLM/Safety calls: violates the frozen BFF boundary and exposes internal capability topology.
- Direct Backend → Ollama: violates LLM Runtime ownership; Backend must call the Runtime service.
- A heavyweight DI framework: no existing need; FastAPI-native dependency injection and one explicit container are sufficient.
- “latest” code-generation/tool versions: not reproducible; exact versions are recorded above.
- Full Compose orchestration: deferred to `13_deployment`; this host has no Docker executable.

## License and compatibility note

The checked references are compatible with research use in this repository: FastAPI full-stack template and Hey API are MIT-licensed, while Cosmic Python's book content is used as an architectural reference. The project does not copy source code from these references. oasdiff and Schemathesis are used as external test tools. No license incompatibility was identified during Stage 0.

