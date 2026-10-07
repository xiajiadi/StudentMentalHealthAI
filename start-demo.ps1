param([switch]$PreflightOnly)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot 'scripts\start-demo.ps1'
& $scriptPath @PSBoundParameters
