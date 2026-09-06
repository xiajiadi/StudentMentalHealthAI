# Backend Module Integration Matrix

Date: 2026-09-05

| Module | Current runtime | Interface discovered | HTTP available? | Round 1 adapter | Evidence label | Current limitation / request |
|---|---|---|---|---|---|---|
| 01 CAT Engine | Python 3.12 module environment | CATService, CAT provider, assessment mapper; lifecycle methods are Python APIs | No formal service found | CatClient + ContractFakeCatClient | CONTRACT_FAKE | CAT owner must publish a versioned lifecycle service; theta, SE, item selection, and stopping remain CAT-owned. See CAT_BACKEND_INTEGRATION_REQUEST.md |
| 05 RAG Engine | Python module environment with local retrieval components | Retrieval service, chunks, citations, RetrievalTrace | No formal service found | RagClient + ContractFakeRagClient | CONTRACT_FAKE | RAG owner must publish bounded retrieval and provenance HTTP surface. Reranker remains accepted default OFF. See RAG_BACKEND_INTEGRATION_REQUEST.md |
| 06 LLM Runtime | Python 3.12 runtime/provider module | RuntimeService and provider ports; Ollama is internal to that module | No formal service found | LLMRuntimeClient + ContractFakeLLMRuntimeClient | CONTRACT_FAKE | LLM owner must publish internal generation surface. Backend never calls Ollama. See LLM_RUNTIME_BACKEND_INTEGRATION_REQUEST.md |
| 08 Safety Engine | Independent FastAPI service on loopback 127.0.0.1:8190 | /health, /internal/safety/check-input, /internal/safety/check-output, /internal/safety/check-retrieval, review transitions | Yes | HttpSafetyClient when SMHAI_SAFETY__MODE=http; fake only for local unit tests | REAL_HTTP when enabled; CONTRACT_FAKE by default | Real HTTP acceptance is a hard gate. Crisis route and output approval are enforced by Backend order. |
| 11 Database | Not implemented in this round | Future repository implementations | No | Repository ports plus in-memory adapters | IN_MEMORY | No SQLAlchemy, schema, DDL, migrations, or production adapter in Round 1. |
| Deployment | External process manager | Process start/stop responsibility | N/A | Backend does not launch module processes | DEFERRED | Local service lifecycle is outside Backend; integration harness assumes Safety is already running. |

## Common boundary rules

- Base URLs are configuration-owned and validated; clients never accept a URL
  from request data.
- Local HTTP clients use trust_env=False, explicit connect/read/write/pool
  timeouts, bounded connection pools, and no blind retry.
- request_id, trace_id, and optional traceparent are forwarded to Safety.
- Upstream dictionaries are mapped to Backend domain views before reaching
  routers.
- A missing mandatory Safety decision fails closed; crisis never enters RAG or
  LLM.
- Every result and evidence record names the actual integration label. A
  schema-valid fake is never reported as a real module integration.
