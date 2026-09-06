param(
    [string]$OutputFile = '',
    [string]$DatabaseName = $env:DB_NAME
)

if (-not $DatabaseName -or $DatabaseName -notmatch '(?i)(test|round1|synthetic)') {
    throw 'Round 1 backup requires a database name containing test, round1, or synthetic.'
}
if (-not $env:DB_USER) {
    throw 'Set DB_USER before running the backup.'
}

$mysqlBin = if ($env:MYSQL_BIN) { $env:MYSQL_BIN } else { 'D:\Software\MySQLServer8.4\bin' }
$dumpTool = Join-Path $mysqlBin 'mysqldump.exe'
if (-not (Test-Path -LiteralPath $dumpTool)) {
    throw "mysqldump was not found at the configured MySQL bin directory."
}

if (-not $OutputFile) {
    $backupDir = 'D:\Dev\backups\studentmentalhealthai\round1'
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    $OutputFile = Join-Path $backupDir ("{0}_{1}.sql" -f $DatabaseName, (Get-Date -Format 'yyyyMMdd_HHmmss'))
}

& $dumpTool `
    '--protocol=tcp' `
    "--host=$($env:DB_HOST ?? '127.0.0.1')" `
    "--port=$($env:DB_PORT ?? '3306')" `
    "--user=$($env:DB_USER)" `
    '--password' `
    '--single-transaction' `
    '--no-tablespaces' `
    '--routines' `
    '--events' `
    '--triggers' `
    '--hex-blob' `
    '--set-gtid-purged=OFF' `
    '--result-file' $OutputFile `
    $DatabaseName
if ($LASTEXITCODE -ne 0) {
    throw "Logical backup failed with exit code $LASTEXITCODE."
}
Write-Output "Backup created: $OutputFile"
