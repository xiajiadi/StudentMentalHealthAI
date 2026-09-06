param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile,
    [Parameter(Mandatory = $true)]
    [string]$RestoreDatabaseName = $env:DB_NAME
)

if (-not (Test-Path -LiteralPath $BackupFile)) {
    throw 'The backup file does not exist.'
}
if (-not $RestoreDatabaseName -or $RestoreDatabaseName -notmatch '(?i)(test|round1|synthetic|restore)') {
    throw 'Restore requires an explicitly named test/round1/restore database.'
}
if (-not $env:DB_USER) {
    throw 'Set DB_USER before running the restore.'
}

$mysqlBin = if ($env:MYSQL_BIN) { $env:MYSQL_BIN } else { 'D:\Software\MySQLServer8.4\bin' }
$mysqlTool = Join-Path $mysqlBin 'mysql.exe'
if (-not (Test-Path -LiteralPath $mysqlTool)) {
    throw 'mysql.exe was not found at the configured MySQL bin directory.'
}

& $mysqlTool `
    '--protocol=tcp' `
    "--host=$($env:DB_HOST ?? '127.0.0.1')" `
    "--port=$($env:DB_PORT ?? '3306')" `
    "--user=$($env:DB_USER)" `
    '--password' `
    '--database=mysql' `
    '--execute' "DROP DATABASE IF EXISTS ``$RestoreDatabaseName``; CREATE DATABASE ``$RestoreDatabaseName`` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
if ($LASTEXITCODE -ne 0) {
    throw 'Fresh restore database creation failed.'
}

& $mysqlTool `
    '--protocol=tcp' `
    "--host=$($env:DB_HOST ?? '127.0.0.1')" `
    "--port=$($env:DB_PORT ?? '3306')" `
    "--user=$($env:DB_USER)" `
    '--password' `
    '--database' $RestoreDatabaseName `
    '--execute' ("SOURCE {0};" -f (Resolve-Path -LiteralPath $BackupFile).Path)
if ($LASTEXITCODE -ne 0) {
    throw 'Logical restore failed.'
}
Write-Output "Restore completed into: $RestoreDatabaseName"
