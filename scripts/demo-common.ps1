$script:DemoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:DemoRunRoot = if ($env:SMHAI_M0_DATA_ROOT) {
    [IO.Path]::GetFullPath($env:SMHAI_M0_DATA_ROOT)
} elseif ($env:LOCALAPPDATA) {
    Join-Path (Split-Path -Parent $script:DemoRoot) ('.' + (Split-Path $script:DemoRoot -Leaf) + '-runtime')
} else {
    throw 'Set SMHAI_M0_DATA_ROOT to a local runtime-data directory.'
}
$script:ManifestPath = Join-Path $script:DemoRunRoot 'processes.json'

function Get-DemoDatabaseTarget {
    $databaseUrl = $env:DATABASE_URL
    if ($databaseUrl) {
        try {
            $match = [regex]::Match($databaseUrl, '^mysql\+aiomysql://[^@]+@(?<host>[^:/?]+)(?::(?<port>\d+))?/(?<database>[^?]+)')
            if (-not $match.Success) { throw 'unsupported URL form' }
            $hostName = $match.Groups['host'].Value
            $databaseName = [Uri]::UnescapeDataString(($match.Groups['database'].Value -split '/', 2)[0])
            $port = if ($match.Groups['port'].Success) { [int]$match.Groups['port'].Value } else { 3306 }
        } catch {
            throw 'DATABASE_URL must be a valid mysql+aiomysql URL; its value is not displayed.'
        }
    } else {
        if ([string]::IsNullOrWhiteSpace($env:DB_USER) -or [string]::IsNullOrEmpty($env:DB_PASSWORD)) {
            throw 'Configure DB_USER and DB_PASSWORD in the user environment; values are never printed.'
        }
        $hostName = if ($env:DB_HOST) { $env:DB_HOST } else { '127.0.0.1' }
        $port = if ($env:DB_PORT) { [int]$env:DB_PORT } else { 3306 }
        $databaseName = $env:DB_NAME
    }

    if ($hostName -notin @('127.0.0.1', 'localhost') -or $databaseName -cne 'smhai_m0_demo') {
        throw 'M0 requires a loopback database whose schema name is exactly `smhai_m0_demo`; no migration or reset was run.'
    }
    if ($port -lt 1 -or $port -gt 65535) { throw 'Database port is outside the valid TCP range.' }
    return [pscustomobject]@{ Host = $hostName; Port = $port; Name = $databaseName }
}

function New-DemoDatabaseUrlFromEnvironment {
    if ($env:DATABASE_URL) { return $env:DATABASE_URL }
    $user = [Uri]::EscapeDataString($env:DB_USER)
    $password = [Uri]::EscapeDataString($env:DB_PASSWORD)
    $hostName = if ($env:DB_HOST) { $env:DB_HOST } else { '127.0.0.1' }
    $port = if ($env:DB_PORT) { [int]$env:DB_PORT } else { 3306 }
    $database = [Uri]::EscapeDataString($env:DB_NAME)
    return "mysql+aiomysql://${user}:${password}@${hostName}:${port}/${database}?charset=utf8mb4"
}

function Invoke-DemoMigrations {
    param([Parameter(Mandatory)][string]$MigrationScript)
    $previousUrl = [Environment]::GetEnvironmentVariable('DATABASE_URL', 'Process')
    try {
        if (-not $previousUrl) { $env:DATABASE_URL = New-DemoDatabaseUrlFromEnvironment }
        & $MigrationScript -Action upgrade -Revision head
        if ($LASTEXITCODE -ne 0) { throw 'Database migration command failed.' }
    } finally {
        if ($null -eq $previousUrl) { Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue }
        else { $env:DATABASE_URL = $previousUrl }
    }
}

function Get-ProjectPython {
    param([Parameter(Mandatory)][string]$RelativePath)
    $path = Join-Path $script:DemoRoot "$RelativePath\.venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Project environment is missing for $RelativePath. Follow 13_deployment\LOCAL_DEMO.md setup instructions first."
    }
    return (Resolve-Path -LiteralPath $path).Path
}

function Test-LocalReady {
    param([Parameter(Mandatory)][string]$Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 3 -UseBasicParsing
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Test-LocalModel {
    try {
        $response = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3
        return @($response.models | Where-Object { $_.name -match '^qwen2\.5:0\.5b(?:$|[-])' }).Count -gt 0
    } catch {
        return $false
    }
}

function Save-DemoManifest {
    param([Parameter(Mandatory)][object[]]$Processes)
    New-Item -ItemType Directory -Path $script:DemoRunRoot -Force | Out-Null
    $manifest = [ordered]@{
        schema_version = 'm0-demo-processes.v1'
        created_at = [DateTime]::UtcNow.ToString('o')
        repository_root = $script:DemoRoot
        processes = @($Processes)
    }
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $script:ManifestPath -Encoding utf8
}

function Stop-ManagedDemoProcesses {
    if (-not (Test-Path -LiteralPath $script:ManifestPath)) { return }
    $manifest = Get-Content -LiteralPath $script:ManifestPath -Raw | ConvertFrom-Json
    if ($manifest.schema_version -ne 'm0-demo-processes.v1' -or $manifest.repository_root -ne $script:DemoRoot) {
        throw 'Demo process manifest does not match this worktree; refusing to stop processes.'
    }
    foreach ($entry in @($manifest.processes | Sort-Object -Property stop_order -Descending)) {
        $process = Get-Process -Id ([int]$entry.pid) -ErrorAction SilentlyContinue
        if ($null -eq $process) { continue }
        $actualPath = try { (Resolve-Path -LiteralPath $process.Path).Path } catch { '' }
        $actualStart = try { $process.StartTime.ToUniversalTime().ToString('o') } catch { '' }
        $nativeProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)" -ErrorAction SilentlyContinue
        $expectedArgv = @($entry.expected_argv)
        $commandLine = if ($nativeProcess) { [string]$nativeProcess.CommandLine } else { '' }
        $argumentsMatch = -not [string]::IsNullOrWhiteSpace($commandLine) -and $expectedArgv.Count -gt 0 -and @($expectedArgv | Where-Object { -not $commandLine.Contains([string]$_) }).Count -eq 0
        if ($actualPath -ne $entry.executable -or $actualStart -ne $entry.started_at -or -not $argumentsMatch) {
            throw "PID $($entry.pid) no longer matches the recorded demo process; refusing to stop it."
        }
        Stop-Process -Id $process.Id -ErrorAction Stop
        try { $process.WaitForExit(10000) | Out-Null } catch { }
    }
    Remove-Item -LiteralPath $script:ManifestPath -Force
}

function Start-ManagedDemoProcess {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Executable,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [Parameter(Mandatory)][string[]]$Arguments,
        [Parameter(Mandatory)][hashtable]$Environment,
        [Parameter(Mandatory)][int]$StopOrder,
        [Parameter(Mandatory)][System.Collections.Generic.List[object]]$Started
    )
    $previous = @{}
    foreach ($key in $Environment.Keys) {
        $previous[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
        [Environment]::SetEnvironmentVariable($key, [string]$Environment[$key], 'Process')
    }
    try {
        $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
    } finally {
        foreach ($key in $Environment.Keys) {
            [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
        }
    }
    Start-Sleep -Milliseconds 300
    if ($process.HasExited) { throw "$Name exited during startup (exit code $($process.ExitCode))." }
    $Started.Add([pscustomobject]@{
        name = $Name
        pid = $process.Id
        executable = (Resolve-Path -LiteralPath $Executable).Path
        started_at = $process.StartTime.ToUniversalTime().ToString('o')
        expected_argv = @($Arguments)
        stop_order = $StopOrder
    })
    Save-DemoManifest -Processes $Started.ToArray()
}

function Wait-LocalReady {
    param([Parameter(Mandatory)][string]$Name, [Parameter(Mandatory)][string]$Url, [int]$TimeoutSeconds = 30)
    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-LocalReady -Url $Url) { return }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name did not become ready at $Url. Check its local dependencies; no fake fallback is enabled."
}
