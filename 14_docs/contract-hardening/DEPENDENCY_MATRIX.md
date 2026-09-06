# Contract/API Hardening Dependency Matrix

| Tool or dependency | Selected version | Source/use | Evidence command |
|---|---:|---|---|
| Python | 3.12 project runtime | Backend and database module environments | uv run --project . python --version |
| FastAPI | project lock range <1 | source OpenAPI generation | uv run --project 09_backend python -c ... |
| Pydantic | project lock range <3 | request/response DTOs | uv run --project 09_backend python -c ... |
| Redocly CLI | 2.51.2 | lint and Respect | npx --yes @redocly/cli@2.51.2 |
| oasdiff | 1.28.0 | root-to-candidate compatibility | D:\Dev\tools\oasdiff\1.28.0\oasdiff.exe --version |
| Schemathesis | 4.25.2 | live API property and negative checks | uvx --from schemathesis==4.25.2 schemathesis --version |
| Arazzo | 1.0.1 document | workflow description | Redocly Respect execution |
| @hey-api/openapi-ts | 0.99.0 exact | generated TypeScript SDK | npm ls @hey-api/openapi-ts |
| Gitleaks | 8.30.1 | secret scanning | D:\Dev\tools\gitleaks\8.30.1\gitleaks.exe version |

Unrelated dependency upgrades are out of scope. Tool caches belong on D: where
the tool permits configuration; no credentials are stored in this matrix.
