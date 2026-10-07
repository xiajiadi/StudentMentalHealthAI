$script:DemoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:DemoRunRoot = if ($env:SMHAI_M0_DATA_ROOT) {
    [IO.Path]::GetFullPath($env:SMHAI_M0_DATA_ROOT)
} elseif ($env:LOCALAPPDATA) {
    Join-Path (Split-Path -Parent $script:DemoRoot) ('.' + (Split-Path $script:DemoRoot -Leaf) + '-runtime')
} else {
    throw 'Set SMHAI_M0_DATA_ROOT to a local runtime-data directory.'
}
$script:ManifestPath = Join-Path $script:DemoRunRoot 'processes.json'
$script:DatabaseEnvironmentNames = @('DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT', 'DB_NAME', 'DATABASE_URL', 'DATABASE_KEY_FILE')

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

function Set-DemoExitCode {
    param([Parameter(Mandatory)][ValidateRange(0, 255)][int]$Code)
    $global:SMHAI_M0_DEMO_EXIT_CODE = $Code
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

function Get-DemoDatabaseEnvironmentNames {
    param([ValidateSet('none', 'backend', 'bootstrap', 'migration')][string]$Access)
    $useUrl = -not [string]::IsNullOrEmpty($env:DATABASE_URL) -or $Access -eq 'migration'
    if ($useUrl) {
        if ($Access -eq 'backend') { return @('DATABASE_URL', 'DATABASE_KEY_FILE') }
        if ($Access -in @('bootstrap', 'migration')) { return @('DATABASE_URL') }
        return @()
    }
    if ($Access -eq 'backend') { return @('DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT', 'DB_NAME', 'DATABASE_KEY_FILE') }
    if ($Access -eq 'bootstrap') { return @('DB_USER', 'DB_PASSWORD', 'DB_HOST', 'DB_PORT', 'DB_NAME') }
    return @()
}

function Invoke-WithDemoDatabaseEnvironment {
    param(
        [Parameter(Mandatory)][ValidateSet('none', 'backend', 'bootstrap', 'migration')][string]$Access,
        [Parameter(Mandatory)][scriptblock]$Action,
        [hashtable]$Overrides = @{}
    )
    $original = @{}
    foreach ($name in $script:DatabaseEnvironmentNames) {
        $original[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    $scopedNames = @($script:DatabaseEnvironmentNames + @($Overrides.Keys) | Select-Object -Unique)
    foreach ($name in $Overrides.Keys) {
        if (-not $original.ContainsKey($name)) { $original[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
    }
    $migrationUrl = if ($Access -eq 'migration' -and [string]::IsNullOrEmpty($original['DATABASE_URL'])) {
        New-DemoDatabaseUrlFromEnvironment
    } else { $null }
    $allowedNames = @(Get-DemoDatabaseEnvironmentNames -Access $Access)
    try {
        foreach ($name in $scopedNames) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
        foreach ($name in $allowedNames) {
            if ($null -ne $original[$name]) { [Environment]::SetEnvironmentVariable($name, $original[$name], 'Process') }
        }
        if ($migrationUrl) { $env:DATABASE_URL = $migrationUrl }
        foreach ($key in $Overrides.Keys) { [Environment]::SetEnvironmentVariable($key, [string]$Overrides[$key], 'Process') }
        & $Action
    } finally {
        foreach ($name in $scopedNames) {
            if ($null -eq $original[$name]) { Remove-Item "Env:$name" -ErrorAction SilentlyContinue }
            else { [Environment]::SetEnvironmentVariable($name, $original[$name], 'Process') }
        }
    }
}

function Invoke-DemoMigrations {
    param([Parameter(Mandatory)][string]$MigrationScript)
    Invoke-WithDemoDatabaseEnvironment -Access migration -Action {
        & $MigrationScript -Action upgrade -Revision head
        if ($LASTEXITCODE -ne 0) { throw 'Database migration command failed.' }
    }
}

function ConvertTo-Utf8JsonNoBomBytes {
    param([Parameter(Mandatory)][string]$Json)
    $encoding = [System.Text.UTF8Encoding]::new($false)
    return ,$encoding.GetBytes($Json + [Environment]::NewLine)
}

function Write-Utf8JsonNoBom {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Json)
    $bytes = ConvertTo-Utf8JsonNoBomBytes -Json $Json
    [System.IO.File]::WriteAllBytes($Path, $bytes)
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

function Test-ManagedDemoProcessStartTime {
    param(
        [Parameter(Mandatory)][object]$Expected,
        [AllowNull()][DateTime]$Actual
    )

    try {
        if ($Expected -is [DateTimeOffset]) {
            $expectedUtcTicks = $Expected.UtcDateTime.Ticks
        } elseif ($Expected -is [DateTime]) {
            if ($Expected.Kind -eq [DateTimeKind]::Unspecified) { return $false }
            $expectedUtcTicks = $Expected.ToUniversalTime().Ticks
        } else {
            $parsedExpected = [DateTimeOffset]::MinValue
            $parsed = [DateTimeOffset]::TryParseExact(
                [string]$Expected,
                'o',
                [Globalization.CultureInfo]::InvariantCulture,
                [Globalization.DateTimeStyles]::RoundtripKind,
                [ref]$parsedExpected
            )
            if (-not $parsed) { return $false }
            $expectedUtcTicks = $parsedExpected.UtcDateTime.Ticks
        }
        if ($null -eq $Actual -or $Actual.Kind -eq [DateTimeKind]::Unspecified) { return $false }
        return $Actual.ToUniversalTime().Ticks -eq $expectedUtcTicks
    } catch {
        return $false
    }
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
        $actualStart = try { $process.StartTime } catch { $null }
        $nativeProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($entry.pid)" -ErrorAction SilentlyContinue
        $expectedArgv = @($entry.expected_argv)
        $commandLine = if ($nativeProcess) { [string]$nativeProcess.CommandLine } else { '' }
        $argumentsMatch = -not [string]::IsNullOrWhiteSpace($commandLine) -and $expectedArgv.Count -gt 0 -and @($expectedArgv | Where-Object { -not $commandLine.Contains([string]$_) }).Count -eq 0
        if ($actualPath -ne $entry.executable -or -not (Test-ManagedDemoProcessStartTime -Expected $entry.started_at -Actual $actualStart) -or -not $argumentsMatch) {
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
        [ValidateSet('none', 'backend', 'bootstrap', 'migration')][string]$DatabaseAccess = 'none',
        [Parameter(Mandatory)][int]$StopOrder,
        [Parameter(Mandatory)][AllowEmptyCollection()][System.Collections.Generic.List[object]]$Started
    )
    $process = Invoke-WithDemoDatabaseEnvironment -Access $DatabaseAccess -Overrides $Environment -Action {
        $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru
        $process
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
