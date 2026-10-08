$ErrorActionPreference = 'Stop'

$global:SMHAI_M0_DEMO_EXIT_CODE = 2
Write-Host 'M0 reset is blocked: the current database has no durable per-record M0 demo marker.'
Write-Host 'No process was stopped and no database was read or changed. Schema-wide DROP is disabled.'
Write-Host 'Use a future approved marker-aware reset implementation before clearing demo records.'
