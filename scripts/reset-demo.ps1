$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'demo-common.ps1')

try {
    $dbTarget = Get-DemoDatabaseTarget
} catch {
    Write-Host "Reset blocked: $($_.Exception.Message)"
    Set-DemoExitCode -Code 2
    return
}

Write-Host "This will drop and recreate only the loopback MySQL schema '$($dbTarget.Name)'."
Write-Host 'It requires a dedicated synthetic-demo schema and an account with schema create/drop rights.'
$confirmation = Read-Host 'Type the schema name to continue'
if ($confirmation -cne 'smhai_m0_demo') {
    Write-Host 'Reset cancelled.'
    Set-DemoExitCode -Code 1
    return
}

try {
    Stop-ManagedDemoProcesses
} catch {
    Write-Host "Reset blocked because managed service shutdown was not verified: $($_.Exception.Message)"
    Set-DemoExitCode -Code 2
    return
}

$databasePython = Get-ProjectPython -RelativePath '11_database'
$resetHelper = Join-Path $PSScriptRoot 'reset_m0_database.py'
Invoke-WithDemoDatabaseEnvironment -Access bootstrap -Action {
    & $databasePython $resetHelper
}
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Dedicated demo schema reset failed; no application services were restarted.'
    Set-DemoExitCode -Code 1
    return
}

$migration = Join-Path $DemoRoot '11_database\scripts\run_migrations.ps1'
try { Invoke-DemoMigrations -MigrationScript $migration } catch {
    Write-Host 'Schema was recreated, but migration did not finish; demo services remain stopped.'
    Set-DemoExitCode -Code 1
    return
}
Write-Host 'Dedicated synthetic demo database reset and migrated. Backend startup recreates synthetic identities.'
Set-DemoExitCode -Code 0
