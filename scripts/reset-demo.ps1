$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'demo-common.ps1')

try {
    $dbTarget = Get-DemoDatabaseTarget
} catch {
    Write-Host "Reset blocked: $($_.Exception.Message)"
    exit 2
}

Write-Host "This will drop and recreate only the loopback MySQL schema '$($dbTarget.Name)'."
Write-Host 'It requires a dedicated synthetic-demo schema and an account with schema create/drop rights.'
$confirmation = Read-Host 'Type the schema name to continue'
if ($confirmation -cne 'smhai_m0_demo') {
    Write-Host 'Reset cancelled.'
    exit 1
}

try {
    Stop-ManagedDemoProcesses
} catch {
    Write-Host "Reset blocked because managed service shutdown was not verified: $($_.Exception.Message)"
    exit 2
}

$databasePython = Get-ProjectPython -RelativePath '11_database'
$resetHelper = Join-Path $PSScriptRoot 'reset_m0_database.py'
& $databasePython $resetHelper
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Dedicated demo schema reset failed; no application services were restarted.'
    exit 1
}

$migration = Join-Path $DemoRoot '11_database\scripts\run_migrations.ps1'
try { Invoke-DemoMigrations -MigrationScript $migration } catch {
    Write-Host 'Schema was recreated, but migration did not finish; demo services remain stopped.'
    exit 1
}
Write-Host 'Dedicated synthetic demo database reset and migrated. Backend startup recreates synthetic identities.'
