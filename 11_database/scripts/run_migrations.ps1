param(
    [ValidateSet('upgrade', 'downgrade', 'check')]
    [string]$Action = 'upgrade',
    [string]$Revision = 'head'
)

$moduleRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $env:DATABASE_URL) {
    throw 'Set DATABASE_URL to an async MySQL URL before running migrations.'
}

Push-Location $moduleRoot
try {
    if ($Action -eq 'upgrade') {
        & uv run alembic -c alembic.ini upgrade $Revision
    } elseif ($Action -eq 'downgrade') {
        $databaseName = $env:DB_NAME
        if (-not $databaseName -or $databaseName -notmatch '(?i)(test|round1|synthetic|restore)') {
            throw 'Downgrade is allowed only when DB_NAME explicitly identifies a test/round1 database.'
        }
        & uv run alembic -c alembic.ini downgrade $Revision
    } else {
        & uv run alembic -c alembic.ini check
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Alembic action failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}
