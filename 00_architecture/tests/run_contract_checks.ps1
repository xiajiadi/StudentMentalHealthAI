[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$testFile = Join-Path $PSScriptRoot "test_contracts.py"
$openApiFile = Join-Path $PSScriptRoot "..\openapi.v1.json"

python $testFile
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

# Use the module-local Backend environment so the root gate is reproducible
# without resolving a package from the network during every acceptance run.
$backendProject = Join-Path $PSScriptRoot "..\..\09_backend"
uv run --project $backendProject python -m openapi_spec_validator $openApiFile
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Output "A-phase contract, Schema, and OpenAPI checks passed."
