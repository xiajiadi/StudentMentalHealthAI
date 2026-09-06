# External OpenAPI Validation

Evidence run: 2026-09-05T01:48:25+08:00 (Asia/Shanghai)

## Validator

| Field | Value |
| --- | --- |
| Validator | `openapi-spec-validator` |
| Version | `0.9.0` |
| Target | `D:\Projects\StudentMentalHealthAI\00_architecture\openapi.v1.json` |
| Source command | `uvx --from openapi-spec-validator openapi-spec-validator <target>` |
| Validation result | `OK` |
| Validator process exit code | 0 |

## Commands and output

The project's formal root script was executed:

```powershell
.\00_architecture\tests\run_contract_checks.ps1
```

Its external-validator step produced:

```text
D:\Projects\StudentMentalHealthAI\00_architecture\tests\..\openapi.v1.json: OK
```

The installed/executed validator version was independently checked with:

```powershell
uvx --from openapi-spec-validator openapi-spec-validator --version
```

Output:

```text
openapi-spec-validator 0.9.0
```

The four internal OpenAPI shape, path, operation and Contract-link tests in
the same root run also passed. The OpenAPI document was not edited to obtain
this result; it remains a frozen Contract asset.

The formal root script was also rerun after the closure documentation was
written at `2026-09-05T01:53:46+08:00`; its external step again returned
`openapi.v1.json: OK` and the script exited 0.
