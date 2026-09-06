# Backend Technical Decision V1

Project: StudentMentalHealthAI  
Module: Backend Application & Orchestration Layer  
Version: 1.0  
Status: PROVISIONALLY_FROZEN  
Date: 2026-09-05  
Depends: Root Contract v0.1.0 FROZEN  
Owner: Project Technical Lead

## Decision summary

Backend Round 1 is a FastAPI application-orchestrator and backend-for-frontend.
It owns HTTP, browser session authentication, native authorization, workflow
ordering, safe frontend DTOs, correlation, audit metadata, health, and
integration ports. CAT, RAG, LLM Runtime, Safety policy, and database schema
remain owned by their respective modules or the later Database Agent.

The implementation uses a Python 3.12 isolated environment, domain-first
vertical slices, in-memory adapters, and loopback HTTP only where a real
upstream HTTP surface exists. CAT, RAG, and LLM Runtime have no formal HTTP
surface in the inspected Round 1 modules, so their explicit ContractFake
adapters are used and documented as integration requests. Safety does expose a
real local service and therefore has a real HttpSafetyClient hard gate.

## Decision register

| ID | Decision |
|---|---|
| D-01 | Backend is the application orchestrator and backend-for-frontend. |
| D-02 | Framework is FastAPI. |
| D-03 | Runtime is an isolated Python 3.12 environment. |
| D-04 | The proposal-era Flask direction is superseded by FastAPI. |
| D-05 | Research scope and project functionality are unchanged. |
| D-06 | Backend does not implement CAT algorithms. |
| D-07 | Backend does not calculate theta or SE. |
| D-08 | Backend does not implement retrieval or reranking. |
| D-09 | Backend does not perform LLM inference directly. |
| D-10 | Backend does not implement Safety policy. |
| D-11 | Round 1 does not implement database schema or migrations. |
| D-12 | Architecture is domain-first vertical slices. |
| D-13 | Full DDD, CQRS, and event sourcing are out of scope. |
| D-14 | Cross-runtime module integration defaults to local HTTP boundaries. |
| D-15 | No direct cross-environment Python imports are used for CAT, RAG, LLM, or Safety. |
| D-16 | HTTPX AsyncClient is the HTTP foundation. |
| D-17 | HTTP clients are long-lived and lifecycle-managed. |
| D-18 | Local module clients default to trust_env=False. |
| D-19 | Upstream base URLs are configuration-owned and never user-controlled. |
| D-20 | Every dependency client has explicit connect, read, write, and pool timeouts. |
| D-21 | Blind generic retry is forbidden. |
| D-22 | Non-idempotent generation and workflow POSTs are not automatically retried. |
| D-23 | Side-effecting operations use idempotency-aware design. |
| D-24 | Browser authentication uses opaque server-side sessions. |
| D-25 | Browser auth references are not stored in localStorage or sessionStorage. |
| D-26 | Session IDs are cryptographically secure opaque random references. |
| D-27 | Production cookies are HttpOnly, Secure, and SameSite=Lax. |
| D-28 | Production uses a __Host- cookie name by default when topology permits. |
| D-29 | Login rotates the session reference; future privilege changes must rotate it too. |
| D-30 | Logout revokes server-side session state. |
| D-31 | Cookie-authenticated mutations require CSRF protection. |
| D-32 | CSRF uses a session-bound synchronizer token. |
| D-33 | Origin, Referer, and Fetch Metadata checks are defense in depth. |
| D-34 | Passwords use pwdlib with its recommended Argon2 configuration. |
| D-35 | No custom password cryptography is implemented. |
| D-36 | JWT is not required for browser authentication in Round 1. |
| D-37 | Authorization V0.1 is a project-owned native AuthorizationProvider. |
| D-38 | OPA is not the Backend authorization engine in Round 1. |
| D-39 | A future OPA authorization adapter remains possible through the port. |
| D-40 | Authorization checks function, object, and data scope. |
| D-41 | Frontend route guards are not security boundaries. |
| D-42 | Backend authorization answers who may access an action or resource. |
| D-43 | Safety disclosure answers which sensitive fields may be exposed. |
| D-44 | Backend does not recreate Safety FULL, SUMMARY, REDACTED, or HIDDEN policy logic. |
| D-45 | API errors use RFC 9457 Problem Details. |
| D-46 | Application errors never use HTTP 200. |
| D-47 | Success payloads use explicit application DTOs. |
| D-48 | CRISIS_ROUTE is a successful domain decision, represented in a 202 workflow result. |
| D-49 | Safety unavailability fails closed for generation. |
| D-50 | Student-facing generation is buffered until output Safety approval. |
| D-51 | Raw unreviewed LLM streaming is disabled in Round 1. |
| D-52 | request_id and trace_id propagate through Backend and upstream HTTP calls. |
| D-53 | Structured logging uses structlog. |
| D-54 | Ordinary logs exclude raw psychological content, prompts, candidates, passwords, and cookies. |
| D-55 | Audit events and operational logs are separate concepts. |
| D-56 | OpenTelemetry is optional and exporter-independent. |
| D-57 | Observability failure must not break application requests. |
| D-58 | Health reports capability-aware dependency status. |
| D-59 | Backend does not start or stop CAT, RAG, LLM, or Safety processes. |
| D-60 | Process lifecycle belongs to Deployment. |
| D-61 | Redis is not required in Round 1. |
| D-62 | Celery, Kafka, and RabbitMQ are not required in Round 1. |
| D-63 | Kubernetes, service mesh, and service discovery are not required. |
| D-64 | Round 1 uses no real student data. |

## Compatibility and migration

The root contract and root OpenAPI remain frozen and read-only. The routes under
api/v1 that already exist in the root contract are implemented with
contract-faithful DTOs. Auth, support, review, health subroutes, and the
buffered workflow details are labelled PROVISIONAL BACKEND API and are exported
only in the backend-local OpenAPI report.

Repository ports are the future Database Agent seam. Replacing an in-memory
adapter must not change the domain service or public DTOs. Distributed sessions,
distributed rate limiting, persistence, production process management, and
streaming require a later decision and acceptance evidence.

## Explicit non-decisions

No clinical interpretation, risk threshold, disclosure policy, production
school authorization policy, OAuth/OIDC, MFA, password reset, persistent
schema, or streamed Safety contract is invented in this round. Those choices
remain outside the Backend Round 1 authority boundary.
