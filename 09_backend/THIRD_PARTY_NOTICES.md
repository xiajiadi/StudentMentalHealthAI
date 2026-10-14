# Backend Round 1 Third-Party Notices

Date: 2026-10-14

No source code was copied from the inspected reference repositories. The
implementation uses their public patterns only. The table records the
dependencies resolved by the Backend Round 1 lockfile and the license source
that should be retained for release review.

| Package | Resolved version | License / source |
|---|---:|---|
| bm25s | 0.3.11 | MIT; https://github.com/xhluca/bm25s |
| fastapi | 0.141.1 | MIT; https://github.com/fastapi/fastapi |
| starlette | 1.6.0 | BSD-3-Clause; https://github.com/encode/starlette |
| uvicorn | 0.52.4 | BSD-3-Clause; https://github.com/encode/uvicorn |
| pydantic | 2.13.5 | MIT; https://github.com/pydantic/pydantic |
| pydantic-settings | 2.15.0 | MIT; https://github.com/pydantic/pydantic-settings |
| httpx | 0.28.1 | BSD-3-Clause; https://github.com/encode/httpx |
| httpcore | 1.0.9 | BSD-3-Clause; https://github.com/encode/httpcore |
| pwdlib | 0.3.1 | MIT; https://github.com/frankie567/pwdlib |
| argon2-cffi | 25.1.0 | MIT; https://github.com/hynek/argon2_cffi |
| structlog | 25.5.0 | MIT OR Apache-2.0; https://github.com/hynek/structlog |
| jsonschema | 4.26.0 | MIT; https://github.com/python-jsonschema/jsonschema |
| pytest | 8.4.2 | MIT; https://github.com/pytest-dev/pytest |
| pytest-asyncio | 1.4.0 | Apache-2.0; https://github.com/pytest-dev/pytest-asyncio |
| pytest-httpx | 0.35.0 | MIT; https://github.com/Colin-b/pytest_httpx |
| ruff | 0.16.6 | MIT; https://github.com/astral-sh/ruff |
| pyright | 1.1.411 | MIT; https://github.com/microsoft/pyright |
| openapi-spec-validator | 0.9.0 | BSD-3-Clause; https://github.com/python-openapi/openapi-spec-validator |

Transitive packages are resolved in uv.lock and remain subject to the normal
release license scan. This document is an engineering inventory, not legal
advice.

## Reference-only repositories

The source audit in research/OPEN_SOURCE_REFERENCE_AUDIT.md records the
licenses and commits for the FastAPI template, FastAPI best practices,
FastAPI-boilerplate, HTTPX, structlog, fastapi-limiter, and starsessions.
Because no files were copied, no source attribution header was added to Backend
files.
