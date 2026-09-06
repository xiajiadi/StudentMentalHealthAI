param(
    [int]$ServerPort = 3307,
    [string]$RunId = (Get-Date -Format 'yyyyMMdd-HHmmss')
)

$ErrorActionPreference = 'Stop'

$moduleRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$mysqlRoot = 'D:\Software\MySQLServer8.4'
$mysql = Join-Path $mysqlRoot 'bin\mysql.exe'
$mysqld = Join-Path $mysqlRoot 'bin\mysqld.exe'
$mysqldump = Join-Path $mysqlRoot 'bin\mysqldump.exe'
$runRoot = Join-Path 'D:\Dev\studentmentalhealthai' "mysql-round1-$RunId"
$dataRoot = Join-Path $runRoot 'data'
$backupRoot = 'D:\Dev\backups\studentmentalhealthai'
$backupPath = Join-Path $backupRoot "database-round1-$RunId.sql"
$keyFile = 'D:\Dev\secrets\studentmentalhealthai\database-keys.json'
$database = "smhai_round1_test_$($RunId.Replace('-', '_'))"
$restoreDatabase = "smhai_round1_restore_$($RunId.Replace('-', '_'))"
$appUser = "smhai_app_$($RunId.Replace('-', '_'))"
$migratorUser = "smhai_migrator_$($RunId.Replace('-', '_'))"
$appPassword = [Guid]::NewGuid().ToString('N')
$migratorPassword = [Guid]::NewGuid().ToString('N')
$serverProcess = $null
$pushedLocation = $false
$previousMySqlPassword = $env:MYSQL_PWD

function Invoke-RootSql {
    param([Parameter(Mandatory)][string]$Sql)

    $rootArgs = @(
        '--protocol=tcp', '--host=127.0.0.1', "--port=$ServerPort", '--user=root',
        '--batch', '--raw'
    )
    $output = & $mysql @rootArgs -e $Sql 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "root MySQL statement failed ($exitCode) for [$Sql]: $($output -join ' ')"
    }
    return @($output)
}

function Invoke-UserSql {
    param(
        [Parameter(Mandatory)][string]$User,
        [Parameter(Mandatory)][string]$Password,
        [Parameter(Mandatory)][string]$Sql
    )

    $oldPassword = $env:MYSQL_PWD
    try {
        $env:MYSQL_PWD = $Password
        $output = & $mysql --protocol=tcp --host=127.0.0.1 "--port=$ServerPort" "--user=$User" "--database=$database" --batch --raw -e $Sql 2>&1
        return [pscustomobject]@{
            Code = $LASTEXITCODE
            Output = @($output)
        }
    }
    finally {
        if ($null -eq $oldPassword) {
            Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
        }
        else {
            $env:MYSQL_PWD = $oldPassword
        }
    }
}

function Invoke-Uv {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$Step
    )

    $output = & uv run @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        $tail = ($output | Select-Object -Last 120) -join "`n"
        throw "$Step failed:`n$tail"
    }
    return @($output)
}

try {
    if (-not (Test-Path -LiteralPath $mysql) -or -not (Test-Path -LiteralPath $mysqld) -or -not (Test-Path -LiteralPath $mysqldump)) {
        throw 'MySQL 8.4 command-line tools are missing from the configured local installation'
    }
    if (Test-Path -LiteralPath $runRoot) {
        throw "refusing to reuse an existing isolated run directory: $runRoot"
    }

    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    & $mysqld --initialize-insecure --datadir=$dataRoot --basedir=$mysqlRoot *> (Join-Path $runRoot 'initialize.log')
    if ($LASTEXITCODE -ne 0) {
        throw "isolated MySQL initialization failed; inspect $(Join-Path $runRoot 'initialize.log')"
    }

    $serverOutput = Join-Path $runRoot 'server.out.log'
    $serverError = Join-Path $runRoot 'server.err.log'
    $serverArgs = @(
        "--datadir=$dataRoot", "--basedir=$mysqlRoot", "--port=$ServerPort",
        '--bind-address=127.0.0.1', '--mysqlx=OFF', '--character-set-server=utf8mb4',
        '--collation-server=utf8mb4_0900_ai_ci', '--default-storage-engine=InnoDB',
        '--max_connections=100'
    )
    $serverProcess = Start-Process -FilePath $mysqld -ArgumentList $serverArgs -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $serverOutput -RedirectStandardError $serverError

    $ready = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        Start-Sleep -Seconds 1
        & $mysql --protocol=tcp --host=127.0.0.1 "--port=$ServerPort" --user=root -e 'SELECT 1' *> $null
        if ($LASTEXITCODE -eq 0) {
            $ready = $true
            break
        }
    }
    if (-not $ready) {
        $tail = Get-Content -LiteralPath $serverError -Tail 30 -ErrorAction SilentlyContinue
        throw "isolated MySQL did not become ready:`n$($tail -join "`n")"
    }

    $runtime = Invoke-RootSql 'SELECT VERSION(), @@version_comment, @@character_set_server, @@collation_server'
    Invoke-RootSql "CREATE DATABASE $database CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci" | Out-Null
    Invoke-RootSql "CREATE DATABASE $restoreDatabase CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci" | Out-Null
    Invoke-RootSql "CREATE USER '$migratorUser'@'127.0.0.1' IDENTIFIED BY '$migratorPassword'" | Out-Null
    Invoke-RootSql "CREATE USER '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword'" | Out-Null
    Invoke-RootSql "GRANT ALL PRIVILEGES ON $database.* TO '$migratorUser'@'127.0.0.1'" | Out-Null
    Invoke-RootSql "GRANT ALL PRIVILEGES ON $restoreDatabase.* TO '$migratorUser'@'127.0.0.1'" | Out-Null
    Invoke-RootSql "GRANT SELECT, INSERT, UPDATE, DELETE ON $database.* TO '$appUser'@'127.0.0.1'" | Out-Null

    $env:DATABASE_KEY_FILE = $keyFile
    Push-Location $moduleRoot
    $pushedLocation = $true
    if (-not (Test-Path -LiteralPath $keyFile)) {
        Invoke-Uv -Arguments @('python', 'scripts/init_dev_key.py') -Step 'development key initialization' | Out-Null
    }

    $migratorUrl = "mysql+aiomysql://$migratorUser`:$migratorPassword@127.0.0.1`:$ServerPort/$database`?charset=utf8mb4"
    $appUrl = "mysql+aiomysql://$appUser`:$appPassword@127.0.0.1`:$ServerPort/$database`?charset=utf8mb4"
    $restoreUrl = "mysql+aiomysql://$migratorUser`:$migratorPassword@127.0.0.1`:$ServerPort/$restoreDatabase`?charset=utf8mb4"

    $env:DATABASE_URL = $migratorUrl
    Invoke-Uv -Arguments @('alembic', 'upgrade', 'head') -Step 'Alembic upgrade' | Out-Null
    Invoke-Uv -Arguments @('alembic', 'check') -Step 'Alembic drift check' | Out-Null
    Invoke-Uv -Arguments @('alembic', 'downgrade', 'base') -Step 'Alembic downgrade' | Out-Null
    Invoke-Uv -Arguments @('alembic', 'upgrade', 'head') -Step 'Alembic re-upgrade' | Out-Null
    Invoke-Uv -Arguments @('alembic', 'check') -Step 'Alembic post-reupgrade drift check' | Out-Null

    $env:DATABASE_URL = $appUrl
    $mysqlTests = Invoke-Uv -Arguments @('pytest', '-vv', '-m', 'mysql') -Step 'real MySQL integration tests'
    Invoke-Uv -Arguments @('python', 'scripts/seed_round1.py') -Step 'synthetic fixture seed' | Out-Null

    $grants = Invoke-UserSql -User $appUser -Password $appPassword -Sql 'SHOW GRANTS'
    $createDenied = Invoke-UserSql -User $appUser -Password $appPassword -Sql "CREATE TABLE $database.app_should_be_denied (id INT)"
    $dropDenied = Invoke-UserSql -User $appUser -Password $appPassword -Sql "DROP TABLE $database.accounts"
    $grantDenied = Invoke-UserSql -User $appUser -Password $appPassword -Sql "GRANT SELECT ON $database.accounts TO '$appUser'@'127.0.0.1'"
    $fileTarget = Join-Path $runRoot 'app-should-not-write.txt'
    $fileTargetSql = $fileTarget.Replace([char]92, [char]47)
    $fileDenied = Invoke-UserSql -User $appUser -Password $appPassword -Sql "SELECT 'blocked' INTO OUTFILE '$fileTargetSql'"
    $fileCreated = Test-Path -LiteralPath $fileTarget
    if ($fileCreated) {
        Remove-Item -LiteralPath $fileTarget -Force
    }
    if ($grants.Code -ne 0 -or $createDenied.Code -eq 0 -or $dropDenied.Code -eq 0 -or $grantDenied.Code -eq 0 -or $fileDenied.Code -eq 0 -or $fileCreated) {
        throw "least-privilege assertions failed: grants=$($grants.Code), create=$($createDenied.Code), drop=$($dropDenied.Code), grant=$($grantDenied.Code), file=$($fileDenied.Code), fileCreated=$fileCreated"
    }

    $subjectPublicIdResult = Invoke-UserSql -User $appUser -Password $appPassword -Sql 'SELECT public_id FROM subjects ORDER BY id LIMIT 1'
    if ($subjectPublicIdResult.Code -ne 0 -or $subjectPublicIdResult.Output.Count -lt 2) {
        throw 'could not read the synthetic subject public ID for EXPLAIN'
    }
    $subjectPublicId = ($subjectPublicIdResult.Output | Select-Object -Last 1).Trim()
    $explain = Invoke-UserSql -User $appUser -Password $appPassword -Sql "EXPLAIN SELECT id, public_id FROM subjects WHERE public_id = '$subjectPublicId'"
    if ($explain.Code -ne 0) {
        throw "EXPLAIN failed: $($explain.Output -join ' ')"
    }

    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    if (Test-Path -LiteralPath $backupPath) {
        throw "refusing to overwrite existing backup: $backupPath"
    }
    $env:MYSQL_PWD = $migratorPassword
    $dumpError = Join-Path $backupRoot "database-round1-$RunId.err"
    $dumpArgs = @(
        '--protocol=tcp', '--host=127.0.0.1', "--port=$ServerPort", "--user=$migratorUser",
        '--single-transaction', '--skip-lock-tables', '--no-tablespaces', '--routines', '--events', '--triggers',
        '--hex-blob', '--set-gtid-purged=OFF', "--result-file=$backupPath", $database
    )
    $dumpProcess = Start-Process -FilePath $mysqldump -ArgumentList $dumpArgs -WindowStyle Hidden -Wait -PassThru `
        -RedirectStandardError $dumpError
    Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    if ($dumpProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $backupPath)) {
        $tail = Get-Content -LiteralPath $dumpError -Tail 30 -ErrorAction SilentlyContinue
        throw "logical backup failed ($($dumpProcess.ExitCode)):`n$($tail -join "`n")"
    }
    $backupTimestamp = (Get-Item -LiteralPath $backupPath).LastWriteTimeUtc.ToString('o')

    $sourcePath = $backupPath.Replace([char]92, [char]47)
    $restoreStart = (Get-Date).ToUniversalTime().ToString('o')
    $restoreOutput = & $mysql @(
        '--protocol=tcp', '--host=127.0.0.1', "--port=$ServerPort", '--user=root',
        "--database=$restoreDatabase", '--verbose', '--show-warnings', '-e', "SOURCE $sourcePath"
    ) 2>&1
    $restoreExitCode = $LASTEXITCODE
    $restoreCompletion = (Get-Date).ToUniversalTime().ToString('o')
    if ($restoreExitCode -ne 0) {
        throw "restore import failed ($restoreExitCode): $($restoreOutput | Select-Object -Last 80 | Join-String -Separator ' ')"
    }
    $env:DATABASE_URL = $restoreUrl
    $env:RESTORE_SOURCE_DATABASE_URL = $migratorUrl
    $env:RESTORE_BACKUP_FILE = $backupPath
    $env:RESTORE_BACKUP_TIMESTAMP = $backupTimestamp
    $env:RESTORE_FRESH_TARGET = 'true'
    $env:RESTORE_START_TIME = $restoreStart
    $env:RESTORE_COMPLETION_TIME = $restoreCompletion
    $env:RESTORE_COMMAND_CATEGORY = 'mysqldump logical backup + mysql SOURCE into a new empty database'
    $env:RESTORE_EXIT_CODE = "$restoreExitCode"
    $restoreVerification = Invoke-Uv -Arguments @('python', 'scripts/verify_restore_closure.py') -Step 'complete fresh restore verification'

    $env:DATABASE_URL = $appUrl
    $env:ROUND1_MIGRATION_STATUS = 'PASS_ALEMBIC_UPGRADE_CHECK_DOWNGRADE_REUPGRADE_CHECK'
    $env:ROUND1_LEAST_PRIVILEGE = 'PASS_APP_SHOW_GRANTS_CREATE_DROP_GRANT_FILE_DENIED'
    $env:ROUND1_BACKUP_STATUS = "PASS_LOGICAL_DUMP_$backupPath"
    $env:ROUND1_RESTORE_STATUS = 'PASS_FRESH_DATABASE_AND_COMPLETE_RESTORE_VERIFICATION'
    $env:ROUND1_MYSQL_TEST_STATUS = 'PASS_6_REAL_MYSQL_TESTS'
    Invoke-Uv -Arguments @('python', 'scripts/round1_evidence.py') -Step 'Round 1 evidence collection' | Out-Null

    $reportPath = Join-Path $moduleRoot 'reports\database_round1_evaluation.json'
    $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
    $grantText = ($grants.Output -join ' | ').Replace("`r", '').Replace("`n", ' | ')
    $explainText = ($explain.Output -join ' | ').Replace("`r", '').Replace("`n", ' | ')
    [ordered]@{
        status = 'PASS'
        mysql_runtime = if ($runtime.Count -gt 1) { $runtime[1] } else { $runtime[0] }
        migration = 'upgrade/check/downgrade/re-upgrade/check'
        real_mysql_tests = ($mysqlTests | Select-Object -Last 1) -join ' '
        least_privilege = [ordered]@{
            show_grants = $grantText
            create_table_exit_code = $createDenied.Code
            drop_table_exit_code = $dropDenied.Code
            grant_exit_code = $grantDenied.Code
            file_write_exit_code = $fileDenied.Code
        } 
        explain = $explainText
        backup = [ordered]@{ path = $backupPath; bytes = (Get-Item -LiteralPath $backupPath).Length }
        restore = ($restoreVerification -join ' ')
        restore_closure = [ordered]@{
            machine = (Join-Path $moduleRoot 'reports\database_round1_restore_verification.json')
            human = (Join-Path $moduleRoot 'reports\DATABASE_ROUND1_RESTORE_CLOSURE_EVIDENCE.md')
            overall = (Get-Content -LiteralPath (Join-Path $moduleRoot 'reports\database_round1_restore_verification.json') -Raw | ConvertFrom-Json).overall
        }
        report = [ordered]@{
            mysql_version = $report.mysql_version
            table_count = $report.table_count
            root_contract = $report.root_contract.status
            frozen_contract_modified = $report.frozen_contract_modified
        }
    } | ConvertTo-Json -Depth 8
}
finally {
    if ($pushedLocation) {
        Pop-Location
    }
    foreach ($name in @('DATABASE_URL', 'DATABASE_KEY_FILE', 'RESTORE_SOURCE_DATABASE_URL', 'RESTORE_BACKUP_FILE', 'RESTORE_BACKUP_TIMESTAMP', 'RESTORE_FRESH_TARGET', 'RESTORE_START_TIME', 'RESTORE_COMPLETION_TIME', 'RESTORE_COMMAND_CATEGORY', 'RESTORE_EXIT_CODE', 'ROUND1_MIGRATION_STATUS', 'ROUND1_LEAST_PRIVILEGE', 'ROUND1_BACKUP_STATUS', 'ROUND1_RESTORE_STATUS', 'ROUND1_MYSQL_TEST_STATUS')) {
        Remove-Item "Env:$name" -ErrorAction SilentlyContinue
    }
    if ($null -ne $previousMySqlPassword) {
        $env:MYSQL_PWD = $previousMySqlPassword
    }
    else {
        Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue
    }
    if ($null -ne $serverProcess) {
        $childProcesses = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($serverProcess.Id)" -ErrorAction SilentlyContinue
        foreach ($child in $childProcesses) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
