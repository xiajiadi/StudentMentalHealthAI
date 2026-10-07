$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'demo-common.ps1')
Stop-ManagedDemoProcesses
Write-Host 'Stopped only the M0 demo processes recorded for this worktree.'
Set-DemoExitCode -Code 0
