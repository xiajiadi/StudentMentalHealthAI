param([switch]$PreflightOnly)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'demo-common.ps1')

$blockers = [System.Collections.Generic.List[string]]::new()
$requiredCommands = @('uv', 'node', 'npm')
foreach ($name in $requiredCommands) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) { $blockers.Add("Missing command: $name") }
}

$projectRoots = @{
    database = Join-Path $DemoRoot '11_database'
    backend = Join-Path $DemoRoot '09_backend'
    cat = Join-Path $DemoRoot '01_cat-engine'
    knowledge = Join-Path $DemoRoot '04_knowledge-pipeline'
    rag = Join-Path $DemoRoot '05_rag-engine'
    llm = Join-Path $DemoRoot '06_llm-runtime'
    safety = Join-Path $DemoRoot '08_safety-engine'
}
$opaBinary = if ([string]::IsNullOrWhiteSpace($env:SMHAI_OPA_BINARY)) {
    'D:\Dev\tools\opa\v1.20.2\opa.exe'
} else {
    try { [IO.Path]::GetFullPath($env:SMHAI_OPA_BINARY) }
    catch { $blockers.Add('SMHAI_OPA_BINARY must resolve to a valid local OPA executable path.'); $null }
}
$opaPolicyDir = Join-Path $projectRoots.safety 'policies'
if (-not $opaBinary -or -not (Test-Path -LiteralPath $opaBinary -PathType Leaf)) {
    $blockers.Add('OPA executable is unavailable; install it locally or set SMHAI_OPA_BINARY to an existing executable.')
}
if (-not (Test-Path -LiteralPath $opaPolicyDir -PathType Container) -or
    @(Get-ChildItem -LiteralPath $opaPolicyDir -Filter '*.rego' -File -ErrorAction SilentlyContinue).Count -eq 0) {
    $blockers.Add('Safety OPA policy directory is unavailable or contains no .rego policy files.')
}
$pythonByProject = @{}
foreach ($entry in $projectRoots.GetEnumerator()) {
    try { $pythonByProject[$entry.Key] = Get-ProjectPython -RelativePath (Split-Path $entry.Value -Leaf) }
    catch { $blockers.Add($_.Exception.Message) }
}

$dependencyImports = @{
    database = 'import sqlalchemy, alembic, aiomysql'
    backend = 'import fastapi, pydantic'
    cat = 'import fastapi, adaptivetesting'
    knowledge = 'import knowledge_pipeline, docling'
    rag = 'import fastapi, bm25s'
    llm = 'import fastapi, httpx'
    safety = 'import fastapi, nemoguardrails, presidio_analyzer, presidio_anonymizer'
}
foreach ($entry in $dependencyImports.GetEnumerator()) {
    if ($pythonByProject.ContainsKey($entry.Key)) {
        Invoke-WithDemoDatabaseEnvironment -Access none -Action {
            & $pythonByProject[$entry.Key] -c $entry.Value *> $null
        }
        if ($LASTEXITCODE -ne 0) { $blockers.Add("Required project-local dependencies are missing for $($entry.Key); use the exact setup command in 13_deployment\LOCAL_DEMO.md.") }
    }
}
$expectedPythonMinor = @{ cat = 14; database = 12; backend = 12; knowledge = 12; rag = 12; llm = 12; safety = 12 }
foreach ($entry in $expectedPythonMinor.GetEnumerator()) {
    if ($pythonByProject.ContainsKey($entry.Key)) {
        Invoke-WithDemoDatabaseEnvironment -Access none -Action {
            & $pythonByProject[$entry.Key] -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, $($entry.Value)) else 1)" *> $null
        }
        if ($LASTEXITCODE -ne 0) { $blockers.Add("Project-local Python version is incompatible for $($entry.Key); expected Python 3.$($entry.Value).") }
    }
}

$keyFile = if ($env:DATABASE_KEY_FILE) { [IO.Path]::GetFullPath($env:DATABASE_KEY_FILE) } else { 'D:\Dev\secrets\studentmentalhealthai\database-keys.json' }
if (-not (Test-Path -LiteralPath $keyFile -PathType Leaf)) { $blockers.Add('Database encryption key file is unavailable; configure DATABASE_KEY_FILE to an existing file outside the repository.') }
else {
    $repositoryRoot = [IO.Path]::GetFullPath($DemoRoot).TrimEnd([char[]]@('\', '/'))
    $repositoryPrefix = $repositoryRoot + [IO.Path]::DirectorySeparatorChar
    if ($keyFile.Equals($repositoryRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $keyFile.StartsWith($repositoryPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $blockers.Add('Database encryption key file must be outside this repository.')
    }
}

try { $dbTarget = Get-DemoDatabaseTarget }
catch { $blockers.Add($_.Exception.Message) }
$databasePort = if ($dbTarget) { $dbTarget.Port } elseif ($env:DB_PORT) { [int]$env:DB_PORT } else { 3306 }
$databaseListener = @(Get-NetTCPConnection -State Listen -LocalPort $databasePort -ErrorAction SilentlyContinue)
if ($dbTarget -and -not $databaseListener) { $blockers.Add("Dedicated MySQL loopback port $($dbTarget.Port) is not listening.") }
if (@($databaseListener | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1', '::ffff:127.0.0.1') }).Count -gt 0) {
    $blockers.Add('MySQL must bind only to loopback; a wildcard or non-loopback listener is not accepted.')
}

$expectedFiles = @(
    '01_cat-engine\fixtures\demo_cat_config.v1.json',
    '01_cat-engine\fixtures\synthetic_item_bank.v1.json',
    '04_knowledge-pipeline\fixtures\m0_demo\freshman_study_routine.md',
    '05_rag-engine\config\rag.m0-demo-bm25.v1.json'
)
foreach ($relative in $expectedFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $DemoRoot $relative) -PathType Leaf)) {
        $blockers.Add("M0 integration asset is not present in this worktree: $relative")
    }
}

$ragApp = Join-Path $DemoRoot '05_rag-engine\src\rag_engine\api\app.py'
if ((Test-Path -LiteralPath $ragApp) -and -not (Select-String -LiteralPath $ragApp -Pattern 'SMHAI_RAG_CORPUS' -Quiet)) {
    $blockers.Add('RAG service does not yet honor an explicit M0 corpus path; refusing its Round 1 default corpus.')
}

$ragProfilePath = Join-Path $DemoRoot '05_rag-engine\config\rag.m0-demo-bm25.v1.json'
if (Test-Path -LiteralPath $ragProfilePath) {
    try {
        $ragProfile = Get-Content -LiteralPath $ragProfilePath -Raw | ConvertFrom-Json
        if ($ragProfile.retrieval_mode -ne 'bm25') { $blockers.Add('M0 RAG profile must explicitly select BM25S-only mode.') }
    } catch { $blockers.Add('M0 RAG profile is not valid JSON.') }
}

$frontendRoot = Join-Path $DemoRoot '10_frontend'
$nodeModules = Join-Path $frontendRoot 'node_modules'
$viteEntrypoint = Join-Path $nodeModules 'vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $nodeModules -PathType Container) -or -not (Test-Path -LiteralPath $viteEntrypoint -PathType Leaf)) {
    $blockers.Add('Frontend dependencies are unavailable; run the documented project-local npm setup first.')
}

foreach ($service in @(@('CAT', 8180), @('RAG', 8170), @('LLM Runtime', 8160), @('OPA', 8181), @('Safety', 8190), @('Backend', 8080), @('Frontend', 4173))) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort $service[1] -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) { $blockers.Add("Port $($service[1]) for $($service[0]) is already occupied; no process was started.") }
}
$ollamaCommand = Get-Command ollama -ErrorAction SilentlyContinue
$ollamaListener = @(Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction SilentlyContinue)
if (@($ollamaListener | Where-Object { $_.LocalAddress -notin @('127.0.0.1', '::1', '::ffff:127.0.0.1') }).Count -gt 0) {
    $blockers.Add('Ollama must bind only to loopback; a wildcard or non-loopback listener is not accepted.')
}
if (-not (Test-LocalReady -Url 'http://127.0.0.1:11434/api/version') -and -not $ollamaCommand) {
    $blockers.Add('Ollama is neither ready on loopback nor installed as a local command.')
} elseif ((Test-LocalReady -Url 'http://127.0.0.1:11434/api/version') -and -not (Test-LocalModel)) {
    $blockers.Add('Required local model qwen2.5:0.5b is unavailable in Ollama; install it locally before launch.')
}

if (Test-Path -LiteralPath $ManifestPath) {
    $blockers.Add('A demo process manifest already exists; run .\stop-demo.ps1 before starting again.')
}
$dataFullPath = [IO.Path]::GetFullPath($DemoRunRoot)
if ($dataFullPath.StartsWith($DemoRoot, [StringComparison]::OrdinalIgnoreCase)) {
    $blockers.Add('M0 runtime data must be stored outside the repository; set SMHAI_M0_DATA_ROOT to an external local directory.')
}

if ($blockers.Count -gt 0) {
    Write-Host 'M0 local launch preflight: BLOCKED'
    foreach ($blocker in $blockers) { Write-Host "- $blocker" }
    Set-DemoExitCode -Code 2
    return
}
Write-Host 'M0 local launch preflight: PASS (loopback-only prerequisites are present).'
if ($PreflightOnly) { Set-DemoExitCode -Code 0; return }

$started = [System.Collections.Generic.List[object]]::new()
try {
    if (-not (Test-LocalReady -Url 'http://127.0.0.1:11434/api/version')) {
        $ollamaExecutable = (Get-Command ollama -ErrorAction Stop).Source
        Start-ManagedDemoProcess -Name 'Ollama' -Executable $ollamaExecutable -WorkingDirectory $DemoRoot -Arguments @('serve') -Environment @{ OLLAMA_HOST='127.0.0.1:11434' } -StopOrder 0 -Started $started
        Wait-LocalReady -Name 'Ollama' -Url 'http://127.0.0.1:11434/api/version' -TimeoutSeconds 30
    }
    if (-not (Test-LocalModel)) { throw 'Required local model qwen2.5:0.5b is unavailable; install it locally before launch.' }

    $migration = Join-Path $DemoRoot '11_database\scripts\run_migrations.ps1'
    Invoke-WithDemoDatabaseEnvironment -Access bootstrap -Action {
        & $pythonByProject['database'] (Join-Path $PSScriptRoot 'ensure_m0_database.py')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Dedicated local demo database bootstrap failed.' }
    Invoke-DemoMigrations -MigrationScript $migration

    $dataRoot = [IO.Path]::GetFullPath($DemoRunRoot)
    $published = Join-Path $dataRoot 'knowledge'
    $pipelinePython = $pythonByProject['knowledge']
    $pipelineRoot = $projectRoots['knowledge']
    Invoke-WithDemoDatabaseEnvironment -Access none -Action {
        & $pipelinePython -m knowledge_pipeline.cli --input (Join-Path $pipelineRoot 'fixtures\m0_demo\freshman_study_routine.md') --output $published --schema-root $DemoRoot
    }
    if ($LASTEXITCODE -ne 0) { throw 'M0 synthetic knowledge corpus bootstrap failed.' }

    $profile = Get-Content -LiteralPath $ragProfilePath -Raw | ConvertFrom-Json
    $profile.stores.bm25_path = Join-Path $dataRoot 'indexes\bm25'
    $runtimeProfile = Join-Path $dataRoot 'rag.m0-demo-bm25.v1.json'
    New-Item -ItemType Directory -Path (Split-Path -Parent $runtimeProfile) -Force | Out-Null
    Write-Utf8JsonNoBom -Path $runtimeProfile -Json ($profile | ConvertTo-Json -Depth 20)

    $pipelineArtifacts = @{
        'SMHAI_RAG_CONFIG' = $runtimeProfile
        'SMHAI_RAG_CORPUS' = Join-Path $published 'embedding_ready.jsonl'
        'SMHAI_RAG_DOCUMENTS' = Join-Path $published 'knowledge_documents.jsonl'
        'SMHAI_RAG_REVIEW_QUEUE' = Join-Path $published 'review_queue.jsonl'
    }
    $modulePlan = @(
        @{ name='CAT'; project='cat'; module='cat_engine.api.app'; port=8180; order=10; env=@{ SMHAI_CAT_PORT='8180' } },
        @{ name='RAG'; project='rag'; module='rag_engine.api.app'; port=8170; order=20; env=$pipelineArtifacts + @{ SMHAI_RAG_PORT='8170' } },
        @{ name='LLM Runtime'; project='llm'; module='llm_runtime.api.app'; port=8160; order=30; env=@{ SMHAI_LLM_PORT='8160' } },
        @{ name='Safety'; project='safety'; module='safety_engine.api.app'; port=8190; order=40; env=@{ SMHAI_OPA_URL='http://127.0.0.1:8181'; SMHAI_MANAGE_OPA='0' } }
    )
    Start-ManagedDemoProcess -Name 'OPA' -Executable $opaBinary -WorkingDirectory $projectRoots.safety -Arguments @('run', '--server', '--addr=127.0.0.1:8181', '--skip-version-check', $opaPolicyDir) -Environment @{} -StopOrder 35 -Started $started
    Wait-LocalReady -Name 'OPA' -Url 'http://127.0.0.1:8181/health' -TimeoutSeconds 15
    foreach ($service in $modulePlan) {
        $python = $pythonByProject[$service.project]
        Start-ManagedDemoProcess -Name $service.name -Executable $python -WorkingDirectory $projectRoots[$service.project] -Arguments @('-m', $service.module) -Environment $service.env -StopOrder $service.order -Started $started
        Wait-LocalReady -Name $service.name -Url "http://127.0.0.1:$($service.port)/health/ready"
    }

    $backendEnv = @{
        SMHAI_ENVIRONMENT='demo'; SMHAI_HOST='127.0.0.1'; SMHAI_PORT='8080'; SMHAI_PERSISTENCE_MODE='mysql'
        SMHAI_ALLOWED_ORIGINS='["http://127.0.0.1:4173"]'
        SMHAI_CAT__MODE='http'; SMHAI_CAT__BASE_URL='http://127.0.0.1:8180'
        SMHAI_RAG__MODE='http'; SMHAI_RAG__BASE_URL='http://127.0.0.1:8170'
        SMHAI_LLM__MODE='http'; SMHAI_LLM__BASE_URL='http://127.0.0.1:8160'
        SMHAI_SAFETY__MODE='http'; SMHAI_SAFETY__BASE_URL='http://127.0.0.1:8190'
        PYTHONPATH=(Join-Path $DemoRoot '11_database') + ';' + (Join-Path $projectRoots.backend 'src') + ';' + (Join-Path $DemoRoot '11_database\.venv\Lib\site-packages')
    }
    Start-ManagedDemoProcess -Name 'Backend' -Executable $pythonByProject['backend'] -WorkingDirectory $projectRoots.backend -Arguments @('-m', 'smhai_backend.main') -Environment $backendEnv -DatabaseAccess backend -StopOrder 50 -Started $started
    Wait-LocalReady -Name 'Backend' -Url 'http://127.0.0.1:8080/health/ready' -TimeoutSeconds 60

    $node = (Get-Command node -ErrorAction Stop).Source
    $viteArguments = @($viteEntrypoint, '--host', '127.0.0.1', '--port', '4173', '--strictPort')
    Start-ManagedDemoProcess -Name 'Frontend' -Executable $node -WorkingDirectory $frontendRoot -Arguments $viteArguments -Environment @{ VITE_API_MODE='real'; VITE_API_BASE_URL='http://127.0.0.1:8080' } -StopOrder 60 -Started $started
    Wait-LocalReady -Name 'Frontend' -Url 'http://127.0.0.1:4173/'
    Write-Host 'M0 local services are ready on loopback: frontend 4173, backend 8080, CAT 8180, RAG 8170, Runtime 8160, Safety 8190.'
    Set-DemoExitCode -Code 0
} catch {
    try { Stop-ManagedDemoProcesses } catch { Write-Host "Cleanup needs attention: $($_.Exception.Message)" }
    Write-Host "M0 startup failed: $($_.Exception.Message)"
    Set-DemoExitCode -Code 1
    return
}
