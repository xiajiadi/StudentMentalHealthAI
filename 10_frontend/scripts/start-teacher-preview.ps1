[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

$frontendRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$viteEntry = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
$previewUrl = 'http://127.0.0.1:4206/teacher/overview'
$port = 4206

if (-not (Test-Path -LiteralPath $viteEntry -PathType Leaf)) {
    throw "Frontend dependencies are not installed at '$frontendRoot'. Install them once with the documented project-local setup before using this fast start."
}

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    throw 'Node.js is not available on PATH.'
}

function Test-TeacherPreviewReady {
    try {
        $response = Invoke-WebRequest -Uri $previewUrl -TimeoutSec 2 -UseBasicParsing
        return $response.StatusCode -eq 200 -and
            $response.Content.Contains('PsyNova') -and
            $response.Content.Contains('/@vite/client')
    } catch {
        return $false
    }
}

$listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
    Select-Object -First 1

if ($listener) {
    if (Test-TeacherPreviewReady) {
        Write-Host "Teacher development preview is already ready: $previewUrl"
        return
    }

    throw "Port $port is already occupied by PID $($listener.OwningProcess), but it is not the expected PsyNova Vite preview. No process was stopped."
}

$logRoot = Join-Path $env:TEMP 'psynova-teacher-preview'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stdoutPath = Join-Path $logRoot '4206.stdout.log'
$stderrPath = Join-Path $logRoot '4206.stderr.log'
$viteArgument = '"{0}"' -f $viteEntry
$arguments = "$viteArgument --host 127.0.0.1 --port $port --strictPort"

Start-Process `
    -FilePath $nodeCommand.Source `
    -ArgumentList $arguments `
    -WorkingDirectory $frontendRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath | Out-Null

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    if (Test-TeacherPreviewReady) {
        Write-Host "Teacher development preview is ready: $previewUrl"
        Write-Host "Startup output is saved under '$logRoot'."
        return
    }
    Start-Sleep -Milliseconds 300
}

throw "Teacher development preview did not become ready within 20 seconds. Inspect '$stdoutPath' and '$stderrPath'."
