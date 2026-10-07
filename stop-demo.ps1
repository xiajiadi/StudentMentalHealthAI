$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'scripts\stop-demo.ps1'
$global:SMHAI_M0_DEMO_EXIT_CODE = 1
$exitCode = 1
try {
    & $scriptPath
    $exitCode = [int]$global:SMHAI_M0_DEMO_EXIT_CODE
} catch {
    Write-Host 'M0 stop command failed; process ownership checks refused an unsafe stop.'
    $exitCode = 1
} finally {
    Remove-Variable -Name SMHAI_M0_DEMO_EXIT_CODE -Scope Global -ErrorAction SilentlyContinue
}
exit $exitCode
