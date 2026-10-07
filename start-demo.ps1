param([switch]$PreflightOnly)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'scripts\start-demo.ps1'
$global:SMHAI_M0_DEMO_EXIT_CODE = 1
$exitCode = 1
try {
    & $scriptPath @PSBoundParameters
    $exitCode = [int]$global:SMHAI_M0_DEMO_EXIT_CODE
} catch {
    Write-Host 'M0 start command failed unexpectedly.'
    $exitCode = 1
} finally {
    Remove-Variable -Name SMHAI_M0_DEMO_EXIT_CODE -Scope Global -ErrorAction SilentlyContinue
}
exit $exitCode
