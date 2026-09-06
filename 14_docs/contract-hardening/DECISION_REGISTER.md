# Contract/API Hardening Decision Register

| ID | Decision | Status |
|---|---|---|
| APIH-01 | Keep OpenAPI 3.1.x; FastAPI/Pydantic is the source of truth | accepted |
| APIH-02 | Generate the hardened candidate from the actual app; no manual OpenAPI patch | accepted |
| APIH-03 | Keep root v0.1.0 contracts byte-unchanged and candidate-only | accepted |
| APIH-04 | Use explicit response DTOs for meaningful browser-facing 2xx responses | accepted |
| APIH-05 | Keep strict request DTOs; do not force additionalProperties=false on all responses | accepted |
| APIH-06 | Preserve root operationIds; explicitly name new operations | accepted |
| APIH-07 | Keep the existing RFC 9457 runtime error path and type/document it | accepted |
| APIH-08 | Use problem code/type for machine behavior; human detail is display text | accepted |
| APIH-09 | Redocly CLI is the only governance linter; no Spectral/Vacuum | accepted |
| APIH-10 | Use oasdiff for compatibility comparison | accepted |
| APIH-11 | Use Schemathesis for live property/negative/fuzz/stateful checks where semantic | accepted |
| APIH-12 | Use Arazzo 1.0.1 and Redocly Respect because official docs confirm 1.0.1 support | accepted |
| APIH-13 | Keep @hey-api/openapi-ts exactly at 0.99.0 and regenerate, never hand edit | accepted |
| APIH-14 | Do not add runtime API version negotiation or /v1 migration behavior | accepted |
| APIH-15 | Preserve provenance from retrieval through persistence, report, and API | accepted |
| APIH-16 | Represent blocked/no-call execution as NOT_RUN with model_id null | accepted |
| APIH-17 | Mark controlled synthetic candidates explicitly | accepted |
| APIH-18 | Change the database only for the proven provenance persistence loss | accepted |

Open choice: whether the candidate is ready for a future v0.2 promotion remains
an evidence-based proposal outcome, not an approval made in this round.
