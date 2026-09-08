param(
    [int]$MySqlPort = 3307
)

$ErrorActionPreference = 'Stop'

$targetRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$sourceRoot = 'D:\Projects\StudentMentalHealthAI'
$evidenceRoot = (Resolve-Path $PSScriptRoot).Path
$logsRoot = Join-Path $evidenceRoot 'logs'
$mysqlRoot = 'D:\Software\MySQLServer8.4'
$mysql = Join-Path $mysqlRoot 'bin\mysql.exe'
$mysqld = Join-Path $mysqlRoot 'bin\mysqld.exe'
$dbPython = Join-Path $sourceRoot '11_database\.venv\Scripts\python.exe'
$dbModule = Join-Path $targetRoot '11_database'
$keyFile = 'D:\Dev\secrets\studentmentalhealthai\database-keys.json'
$gpuOllama = 'D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\ollama-0.33.3\ollama.exe'
$gpuModels = 'D:\Dev\tools\StudentMentalHealthAI\gpu-acceptance\models'
$cpuModels = 'D:\Dev\caches\ollama-models'
$pythonCat = Join-Path $sourceRoot '01_cat-engine\.venv314\Scripts\python.exe'
$pythonRag = Join-Path $sourceRoot '05_rag-engine\.venv\Scripts\python.exe'
$pythonSafety = Join-Path $sourceRoot '08_safety-engine\.venv\Scripts\python.exe'
$pythonRuntime = 'D:\Projects\StudentMentalHealthAI-runtime-reconstruction\06_llm-runtime\.venv\Scripts\python.exe'
$pythonBackend = Join-Path $sourceRoot '09_backend\.venv\Scripts\python.exe'
$harnessPython = $pythonBackend
$ownedPids = [System.Collections.Generic.List[int]]::new()
$mysqlProcess = $null
$runId = Get-Date -Format 'yyyyMMdd_HHmmss'
$runRoot = Join-Path 'D:\Dev\studentmentalhealthai' "mysql-gpi-closure-$runId"
$dataRoot = Join-Path $runRoot 'data'
$database = "smhai_gpi_closure_$runId"
$appUser = "gpi_app_$runId"
$migratorUser = "gpi_mig_$runId"
$appPassword = [Guid]::NewGuid().ToString('N')
$migratorPassword = [Guid]::NewGuid().ToString('N')
$exitCode = 1

if (Test-Path -LiteralPath $logsRoot) {
    foreach ($oldEvidenceFile in (Get-ChildItem -LiteralPath $logsRoot -File)) {
        Remove-Item -LiteralPath $oldEvidenceFile.FullName -Force
    }
}
New-Item -ItemType Directory -Path $logsRoot -Force | Out-Null

function Start-LoggedProcess {
    param(
        [Parameter(Mandatory)][string]$FilePath,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][hashtable]$Environment,
        [Parameter(Mandatory)][string]$StdOut,
        [Parameter(Mandatory)][string]$StdErr
    )
    $backup = @{}
    foreach ($key in $Environment.Keys) {
        $backup[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], 'Process')
    }
    try {
        return Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput $StdOut -RedirectStandardError $StdErr
    }
    finally {
        foreach ($key in $Environment.Keys) {
            if ($null -eq $backup[$key]) {
                [Environment]::SetEnvironmentVariable($key, $null, 'Process')
            }
            else {
                [Environment]::SetEnvironmentVariable($key, $backup[$key], 'Process')
            }
        }
    }
}

function Add-OwnedProcess {
    param([Parameter(Mandatory)]$Process)
    $ownedPids.Add([int]$Process.Id)
    return $Process
}

function Invoke-RootSql {
    param([Parameter(Mandatory)][string]$Sql)
    $result = & $mysql --protocol=tcp --host=127.0.0.1 "--port=$MySqlPort" --user=root --batch --raw -e $Sql 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "isolated MySQL root SQL failed with exit code $LASTEXITCODE"
    }
    return @($result)
}

function Wait-Http {
    param([Parameter(Mandatory)][string]$Url, [int]$TimeoutSeconds = 300)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                return
            }
        }
        catch {
        }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    throw "timeout waiting for $Url"
}

try {
    if (-not (Test-Path -LiteralPath $mysql) -or -not (Test-Path -LiteralPath $mysqld)) {
        throw 'MySQL 8.4 binaries are missing'
    }
    if (Test-Path -LiteralPath $runRoot) {
        throw "refusing to reuse isolated database directory $runRoot"
    }
    New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
    & $mysqld --initialize-insecure "--datadir=$dataRoot" "--basedir=$mysqlRoot" *> (Join-Path $runRoot 'initialize.log')
    if ($LASTEXITCODE -ne 0) {
        throw 'isolated MySQL initialization failed'
    }
    $mysqlOut = Join-Path $runRoot 'server.out.log'
    $mysqlErr = Join-Path $runRoot 'server.err.log'
    $mysqlArgs = @(
        "--datadir=$dataRoot", "--basedir=$mysqlRoot", "--port=$MySqlPort",
        '--bind-address=127.0.0.1', '--mysqlx=OFF', '--character-set-server=utf8mb4',
        '--collation-server=utf8mb4_0900_ai_ci', '--default-storage-engine=InnoDB', '--max_connections=100'
    )
    $mysqlProcess = Add-OwnedProcess (Start-Process -FilePath $mysqld -ArgumentList $mysqlArgs -WorkingDirectory $mysqlRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $mysqlOut -RedirectStandardError $mysqlErr)
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        & $mysql --protocol=tcp --host=127.0.0.1 "--port=$MySqlPort" --user=root -e 'SELECT 1' *> $null
        if ($LASTEXITCODE -eq 0) { break }
        Start-Sleep -Seconds 1
    }
    & $mysql --protocol=tcp --host=127.0.0.1 "--port=$MySqlPort" --user=root -e 'SELECT 1' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'isolated MySQL did not become ready' }

    $sql = @"
CREATE DATABASE $database CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER '$migratorUser'@'127.0.0.1' IDENTIFIED BY '$migratorPassword';
CREATE USER '$appUser'@'127.0.0.1' IDENTIFIED BY '$appPassword';
GRANT ALL PRIVILEGES ON $database.* TO '$migratorUser'@'127.0.0.1';
GRANT SELECT, INSERT, UPDATE, DELETE ON $database.* TO '$appUser'@'127.0.0.1';
FLUSH PRIVILEGES;
"@
    Invoke-RootSql $sql | Out-Null

    $migratorUrl = "mysql+aiomysql://$migratorUser`:$migratorPassword@127.0.0.1`:$MySqlPort/$database`?charset=utf8mb4"
    $appUrl = "mysql+aiomysql://$appUser`:$appPassword@127.0.0.1`:$MySqlPort/$database`?charset=utf8mb4"
    if (-not (Test-Path -LiteralPath $keyFile)) {
        Push-Location $dbModule
        try {
            $env:DATABASE_KEY_FILE = $keyFile
            & $dbPython scripts/init_dev_key.py *> (Join-Path $logsRoot 'database-key-init.log')
            if ($LASTEXITCODE -ne 0) { throw 'database development key initialization failed' }
        }
        finally {
            Pop-Location
            Remove-Item Env:DATABASE_KEY_FILE -ErrorAction SilentlyContinue
        }
    }
    Push-Location $dbModule
    try {
        $env:DATABASE_URL = $migratorUrl
        $env:DATABASE_KEY_FILE = $keyFile
        & $dbPython -m alembic upgrade head *> (Join-Path $logsRoot 'database-migration.log')
        if ($LASTEXITCODE -ne 0) { throw 'Alembic migration failed' }
    }
    finally {
        Pop-Location
        Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
        Remove-Item Env:DATABASE_KEY_FILE -ErrorAction SilentlyContinue
    }

    $commonEnv = @{
        OLLAMA_NUM_PARALLEL = '1'
        OLLAMA_KEEP_ALIVE = '5m'
    }
    $gpuEnv = @{
        OLLAMA_HOST = '127.0.0.1:11435'
        OLLAMA_MODELS = $gpuModels
        OLLAMA_CONTEXT_LENGTH = '8192'
        OLLAMA_NUM_PARALLEL = '1'
        OLLAMA_KEEP_ALIVE = '5m'
    }
    $cpuEnv = @{
        OLLAMA_HOST = '127.0.0.1:11436'
        OLLAMA_MODELS = $cpuModels
        OLLAMA_LLM_LIBRARY = 'cpu_avx2'
        OLLAMA_CONTEXT_LENGTH = '8192'
        OLLAMA_NUM_PARALLEL = '1'
        OLLAMA_KEEP_ALIVE = '5m'
    }
    $ollamaGpu = Add-OwnedProcess (Start-LoggedProcess -FilePath $gpuOllama -Arguments @('serve') -WorkingDirectory (Split-Path $gpuOllama) -Environment $gpuEnv -StdOut (Join-Path $logsRoot 'ollama-gpu.out.log') -StdErr (Join-Path $logsRoot 'ollama-gpu.err.log'))
    $ollamaCpu = Add-OwnedProcess (Start-LoggedProcess -FilePath $gpuOllama -Arguments @('serve') -WorkingDirectory (Split-Path $gpuOllama) -Environment $cpuEnv -StdOut (Join-Path $logsRoot 'ollama-cpu.out.log') -StdErr (Join-Path $logsRoot 'ollama-cpu.err.log'))
    Wait-Http 'http://127.0.0.1:11435/api/version' 90
    Wait-Http 'http://127.0.0.1:11436/api/version' 90

    $observerScript = Join-Path $evidenceRoot 'observer_proxy.py'
    $observerPython = $pythonBackend
    $ollamaProxy = Add-OwnedProcess (Start-LoggedProcess -FilePath $observerPython -Arguments @($observerScript) -WorkingDirectory $targetRoot -Environment @{ GPI_PROXY_NAME = 'ollama'; GPI_UPSTREAM_URL = 'http://127.0.0.1:11435'; GPI_PROXY_PORT = '11535'; GPI_PROXY_LOG = (Join-Path $logsRoot 'ollama.jsonl') } -StdOut (Join-Path $logsRoot 'ollama-proxy.out.log') -StdErr (Join-Path $logsRoot 'ollama-proxy.err.log'))
    Wait-Http 'http://127.0.0.1:11535/health' 60

    $catEnv = @{ PYTHONPATH = (Join-Path $targetRoot '01_cat-engine\src'); SMHAI_CAT_PORT = '8180' }
    $ragEnv = @{ PYTHONPATH = (Join-Path $targetRoot '05_rag-engine\src'); SMHAI_RAG_PORT = '8170' }
    $safetyEnv = @{
        PYTHONPATH = (Join-Path $targetRoot '08_safety-engine\src')
        SMHAI_MANAGE_OPA = '1'
        SMHAI_OPA_BINARY = 'D:\Dev\tools\opa\v1.20.2\opa.exe'
        SMHAI_OPA_URL = 'http://127.0.0.1:8181'
        SMHAI_HF_HOME = 'D:\Dev\caches\huggingface'
        HF_HOME = 'D:\Dev\caches\huggingface'
        SMHAI_REVIEW_DB = (Join-Path $logsRoot 'safety-review.sqlite')
    }
    $runtimeEnv = @{
        PYTHONPATH = (Join-Path $targetRoot '06_llm-runtime\src')
        SMHAI_GPI_RUNTIME_MODE = 'primary'
        SMHAI_GPI_GPU_OLLAMA_URL = 'http://127.0.0.1:11535'
        SMHAI_GPI_CPU_OLLAMA_URL = 'http://127.0.0.1:11436'
        SMHAI_LLM_PORT = '8160'
        SMHAI_GPI_RUNTIME_LOG = (Join-Path $logsRoot 'runtime-service-primary.jsonl')
    }
    $observerScript = Join-Path $evidenceRoot 'observer_proxy.py'
    $observerPython = $pythonBackend
    $cat = Add-OwnedProcess (Start-LoggedProcess -FilePath $pythonCat -Arguments @('-m', 'cat_engine.api.app') -WorkingDirectory (Join-Path $targetRoot '01_cat-engine') -Environment $catEnv -StdOut (Join-Path $logsRoot 'cat.out.log') -StdErr (Join-Path $logsRoot 'cat.err.log'))
    $rag = Add-OwnedProcess (Start-LoggedProcess -FilePath $pythonRag -Arguments @('-m', 'rag_engine.api.app') -WorkingDirectory (Join-Path $targetRoot '05_rag-engine') -Environment $ragEnv -StdOut (Join-Path $logsRoot 'rag.out.log') -StdErr (Join-Path $logsRoot 'rag.err.log'))
    $safety = Add-OwnedProcess (Start-LoggedProcess -FilePath $pythonSafety -Arguments @((Join-Path $evidenceRoot 'safety_server_launcher.py')) -WorkingDirectory (Join-Path $targetRoot '08_safety-engine') -Environment $safetyEnv -StdOut (Join-Path $logsRoot 'safety.out.log') -StdErr (Join-Path $logsRoot 'safety.err.log'))
    $runtime = Add-OwnedProcess (Start-LoggedProcess -FilePath $pythonRuntime -Arguments @((Join-Path $evidenceRoot 'runtime_acceptance_server.py')) -WorkingDirectory (Join-Path $targetRoot '06_llm-runtime') -Environment $runtimeEnv -StdOut (Join-Path $logsRoot 'runtime-primary.out.log') -StdErr (Join-Path $logsRoot 'runtime-primary.err.log'))
    $safety.Id | Set-Content -LiteralPath (Join-Path $logsRoot 'safety-current.pid') -Encoding ascii
    $runtime.Id | Set-Content -LiteralPath (Join-Path $logsRoot 'runtime-current.pid') -Encoding ascii

    Wait-Http 'http://127.0.0.1:8180/health/ready' 120
    Wait-Http 'http://127.0.0.1:8170/health/ready' 600
    Wait-Http 'http://127.0.0.1:8190/health/ready' 600
    Wait-Http 'http://127.0.0.1:8160/health/ready' 180

    $catProxy = Add-OwnedProcess (Start-LoggedProcess -FilePath $observerPython -Arguments @($observerScript) -WorkingDirectory $targetRoot -Environment @{ GPI_PROXY_NAME = 'cat'; GPI_UPSTREAM_URL = 'http://127.0.0.1:8180'; GPI_PROXY_PORT = '8280'; GPI_PROXY_LOG = (Join-Path $logsRoot 'cat.jsonl') } -StdOut (Join-Path $logsRoot 'cat-proxy.out.log') -StdErr (Join-Path $logsRoot 'cat-proxy.err.log'))
    $ragProxy = Add-OwnedProcess (Start-LoggedProcess -FilePath $observerPython -Arguments @($observerScript) -WorkingDirectory $targetRoot -Environment @{ GPI_PROXY_NAME = 'rag'; GPI_UPSTREAM_URL = 'http://127.0.0.1:8170'; GPI_PROXY_PORT = '8270'; GPI_PROXY_LOG = (Join-Path $logsRoot 'rag.jsonl') } -StdOut (Join-Path $logsRoot 'rag-proxy.out.log') -StdErr (Join-Path $logsRoot 'rag-proxy.err.log'))
    $llmProxy = Add-OwnedProcess (Start-LoggedProcess -FilePath $observerPython -Arguments @($observerScript) -WorkingDirectory $targetRoot -Environment @{ GPI_PROXY_NAME = 'llm'; GPI_UPSTREAM_URL = 'http://127.0.0.1:8160'; GPI_PROXY_PORT = '8260'; GPI_PROXY_LOG = (Join-Path $logsRoot 'llm.jsonl') } -StdOut (Join-Path $logsRoot 'llm-proxy.out.log') -StdErr (Join-Path $logsRoot 'llm-proxy.err.log'))
    $safetyProxy = Add-OwnedProcess (Start-LoggedProcess -FilePath $observerPython -Arguments @($observerScript) -WorkingDirectory $targetRoot -Environment @{ GPI_PROXY_NAME = 'safety'; GPI_UPSTREAM_URL = 'http://127.0.0.1:8190'; GPI_PROXY_PORT = '8290'; GPI_PROXY_LOG = (Join-Path $logsRoot 'safety.jsonl') } -StdOut (Join-Path $logsRoot 'safety-proxy.out.log') -StdErr (Join-Path $logsRoot 'safety-proxy.err.log'))
    Wait-Http 'http://127.0.0.1:8280/health' 60
    Wait-Http 'http://127.0.0.1:8270/health' 60
    Wait-Http 'http://127.0.0.1:8260/health' 60
    Wait-Http 'http://127.0.0.1:8290/health' 60
    Wait-Http 'http://127.0.0.1:11535/health' 60

    $backendEnv = @{
        PYTHONPATH = "$(Join-Path $targetRoot '09_backend\src');$(Join-Path $targetRoot '11_database');$(Join-Path $sourceRoot '11_database\.venv\Lib\site-packages')"
        SMHAI_ENVIRONMENT = 'local'
        SMHAI_HOST = '127.0.0.1'
        SMHAI_PORT = '8080'
        SMHAI_PERSISTENCE_MODE = 'mysql'
        SMHAI_CAT__MODE = 'http'
        SMHAI_CAT__BASE_URL = 'http://127.0.0.1:8280'
        SMHAI_RAG__MODE = 'http'
        SMHAI_RAG__BASE_URL = 'http://127.0.0.1:8270'
        SMHAI_LLM__MODE = 'http'
        SMHAI_LLM__BASE_URL = 'http://127.0.0.1:8260'
        SMHAI_SAFETY__MODE = 'http'
        SMHAI_SAFETY__BASE_URL = 'http://127.0.0.1:8290'
        SMHAI_CAT__TIMEOUT__READ = '120'
        SMHAI_RAG__TIMEOUT__READ = '240'
        SMHAI_LLM__TIMEOUT__READ = '240'
        SMHAI_SAFETY__TIMEOUT__READ = '240'
        SMHAI_SUPPORT_DEADLINE_SECONDS = '120'
        SMHAI_RATE_LIMIT__LOGIN_MAX_REQUESTS = '100'
        SMHAI_RATE_LIMIT__SUPPORT_MAX_REQUESTS = '100'
        SMHAI_RATE_LIMIT__WINDOW_SECONDS = '600'
        DATABASE_URL = $appUrl
        DATABASE_KEY_FILE = $keyFile
    }
    $backend = Add-OwnedProcess (Start-LoggedProcess -FilePath $pythonBackend -Arguments @('-m', 'smhai_backend.main') -WorkingDirectory (Join-Path $targetRoot '09_backend') -Environment $backendEnv -StdOut (Join-Path $logsRoot 'backend.out.log') -StdErr (Join-Path $logsRoot 'backend.err.log'))

    $env:GPI_DB_PORT = [string]$MySqlPort
    $env:GPI_DB_NAME = $database
    $env:GPI_DB_USER = $appUser
    $env:GPI_DB_PASSWORD = $appPassword
    $env:SMHAI_BACKEND_URL = 'http://127.0.0.1:8080'
    $env:SMHAI_GPI_GPU_OLLAMA_URL = 'http://127.0.0.1:11535'
    $env:SMHAI_GPI_CPU_OLLAMA_URL = 'http://127.0.0.1:11436'
    $env:GPI_GPU_OLLAMA_REAL_URL = 'http://127.0.0.1:11435'
    Wait-Http 'http://127.0.0.1:8080/api/v1/health' 180

    $ownedPids | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logsRoot 'owned-pids.json') -Encoding utf8
    & $harnessPython (Join-Path $evidenceRoot 'closure_harness.py')
    $exitCode = $LASTEXITCODE
}
catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $logsRoot 'orchestration-error.log') -Encoding utf8
    $exitCode = 1
}
finally {
    $dynamicPidFiles = @('safety-current.pid', 'runtime-current.pid')
    foreach ($file in $dynamicPidFiles) {
        $path = Join-Path $logsRoot $file
        if (Test-Path -LiteralPath $path) {
            try { $ownedPids.Add([int](Get-Content -Raw -LiteralPath $path)) } catch { }
        }
    }
    foreach ($ownedPid in ($ownedPids | Select-Object -Unique)) {
        taskkill.exe /PID $ownedPid /T /F *> $null
    }
    [ordered]@{
        completed_at = (Get-Date).ToUniversalTime().ToString('o')
        exit_code = $exitCode
        owned_pids = @($ownedPids | Select-Object -Unique)
        mysql_run_root = $runRoot
        database = $database
        processes_cleaned_by_explicit_pid = $true
    } | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $logsRoot 'cleanup.json') -Encoding utf8
    Remove-Item Env:GPI_DB_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:GPI_DB_USER -ErrorAction SilentlyContinue
    Remove-Item Env:GPI_DB_NAME -ErrorAction SilentlyContinue
    Remove-Item Env:GPI_DB_PORT -ErrorAction SilentlyContinue
}
exit $exitCode
