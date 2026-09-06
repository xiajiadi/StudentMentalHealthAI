[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$testFile = Join-Path $PSScriptRoot "test_contracts.py"
$openApiFile = Join-Path $PSScriptRoot "..\openapi.v1.json"

python $testFile
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

uvx --from openapi-spec-validator openapi-spec-validator $openApiFile
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Output "A-phase contract, Schema, and OpenAPI checks passed."
