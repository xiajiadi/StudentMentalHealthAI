# Backend Round 1 Open-Source Reference Audit

Date: 2026-09-05

This audit records source inspection performed for the Backend Application and
Orchestration Layer. The repositories were cloned to the isolated cache
D:\Dev\cache\smhai-backend-oss and inspected at the SHAs below. No source file
was copied into 09_backend.

## Decisions from the reference implementations

The adopted baseline is domain-first FastAPI with an application factory,
lifespan-managed resources, dependency injection, explicit Pydantic DTOs,
ASGITransport tests, HTTPX clients owned by the application lifecycle, and
structured logging. SQLAlchemy, Redis, Taskiq, frontend generation, and
template-specific product code were not adopted because they cross the Round 1
ownership boundary or are not required for the application workflow.

## Primary FastAPI references

| Source | URL | Commit / observed license | Files actually inspected | Adopted | Rejected |
|---|---|---|---|---|---|
| full-stack-fastapi-template | https://github.com/fastapi/full-stack-fastapi-template | cb740b656d7a0a6c5e12c7bf8e50343ec94ee9c7; MIT; GitHub page showed about 45.4k stars on the audit date | backend/app/main.py, backend/app/core/config.py, backend/app/api/main.py, backend/app/api/deps.py, backend/app/api/routes/login.py, backend/app/tests/api/routes/test_login.py, backend/app/tests/api/test_routes.py | settings object, factory-style app construction, lifespan, dependency overrides, route/test separation, generated-client awareness | full-stack template clone, SQLModel/SQLAlchemy persistence, Alembic, React frontend, template auth routes |
| fastapi-best-practices | https://github.com/zhanymkanov/fastapi-best-practices | 5e00aa6095521f0d00e4eec2ef0afa44cd566af4; no root LICENSE file was present in the checkout | README.md, AGENTS.md, sections on project structure, async routes, Pydantic, dependency injection, tests, error handling, background tasks | domain-by-feature structure, async I/O guidance, Pydantic v2 settings, ASGITransport tests, dependency override pattern, explicit background-task caution | its SQLAlchemy/Redis examples, framework-wide adoption without project-specific policy, treating a checklist as a substitute for acceptance evidence |
| FastAPI-boilerplate (redirect target of igorbenav/FastAPI-boilerplate) | https://github.com/igorbenav/FastAPI-boilerplate and https://github.com/benavlabs/FastAPI-boilerplate | 2b6373d922bc993c7706c25a53f8dbab4e00217f; MIT | backend/src/infrastructure/app_factory.py, backend/src/infrastructure/middleware.py, backend/src/config/settings.py, backend/src/auth, backend/src/common, backend/tests | application factory, middleware layering, settings separation, router/service split, test organization | SQLAlchemy/async database setup, Redis, Taskiq, generic boilerplate modules, copying infrastructure wholesale |

The original igorbenav URL currently redirects to the benavlabs repository.
The audit follows the current repository content while retaining the requested
source URL for provenance.

## HTTP and observability references

| Source | URL | Commit / license | Files actually inspected | Applied to Backend |
|---|---|---|---|---|
| HTTPX | https://github.com/encode/httpx | b5addb64f0161ff6bfe94c124ef76f6a1fba5254; BSD-3-Clause | _client.py, docs/advanced/clients.md, docs/advanced/timeouts.md, async examples and tests | one long-lived AsyncClient per HTTP dependency, explicit connect/read/write/pool timeouts, connection limits, close at lifespan shutdown, no generic retry |
| structlog | https://github.com/hynek/structlog | d8e321a031aeae5704f798f9102ef9559532b22f; MIT OR Apache-2.0 | src/structlog/contextvars.py, src/structlog/stdlib.py, configuration examples | contextvars correlation fields, JSON renderer, log level/timestamp processors, safe metadata-only events |

## Secondary references

| Source | URL | Commit / license | Files actually inspected | Decision |
|---|---|---|---|---|
| fastapi-limiter | https://github.com/long2ice/fastapi-limiter | cc95615f9d68a6e82dcd2fa5abbf3f09c3f82569; Apache-2.0 | README.md, fastapi_limiter/depends.py, tests and middleware examples | rejected as a Round 1 dependency: it brings a PyrateLimiter/Redis-oriented integration where a transparent single-process limiter is enough for the declared engineering baseline |
| starsessions | https://github.com/alex-oleshkevich/starsessions | f2942f9be1ebe058a9629cb7a52d741c46c80168; MIT | README.md, session middleware/store examples, cookie-store documentation | rejected for the default implementation: the Backend requires a deliberately explicit server-side store and a synchronizer CSRF token; the README also distinguishes signed cookies from encrypted storage |

## Official standards and framework material inspected

- FastAPI source and security documentation:
  https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- RFC 9457 Problem Details:
  https://www.rfc-editor.org/rfc/rfc9457.html
- OWASP REST Security Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
- OWASP Session Management Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- OWASP CSRF Prevention Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- OWASP API Security Top 10 2023:
  https://owasp.org/API-Security/editions/2023/en/0x11-t10/
- HTTPX async client guidance:
  https://www.python-httpx.org/async/
- OpenTelemetry Python libraries:
  https://opentelemetry.io/docs/languages/python/libraries/

## License and attribution outcome

Only declared package dependencies are installed. No reference repository code
was copied, so there is no copied-source attribution requirement for the
implementation. License inventory for actual runtime dependencies is recorded
in THIRD_PARTY_NOTICES.md. The fastapi-best-practices repository had no root
license file in the inspected checkout; its prose was used as research, not
copied into product code.
