param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$output = (New-Item -ItemType Directory -Force -Path $OutputDirectory).FullName
$archive = Join-Path $output 'PsyNova-School-source.zip'
$installer = Join-Path $output 'PsyNova-School-Windows-x64-Preview.exe'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework/v4.0.30319/csc.exe'

# Select versioned runtime files and exclude historical artifacts from the installer payload.
$payload = @(
    '00_architecture', '01_cat-engine/src', '01_cat-engine/fixtures',
    '01_cat-engine/README.md', '01_cat-engine/pyproject.toml', '01_cat-engine/uv.lock',
    '05_rag-engine/src', '07_prompt-engine',
    '09_backend/src', '09_backend/README.md', '09_backend/pyproject.toml', '09_backend/uv.lock',
    '10_frontend/src', '10_frontend/public', '10_frontend/index.html',
    '10_frontend/package.json', '10_frontend/package-lock.json',
    '10_frontend/vite.config.ts', '10_frontend/tsconfig.json',
    '10_frontend/tsconfig.app.json', '10_frontend/tsconfig.node.json',
    '11_database/database_layer', '11_database/migrations', '11_database/alembic.ini',
    '11_database/README.md', '11_database/pyproject.toml', '11_database/uv.lock',
    '13_deployment', ':(exclude)13_deployment/tests', ':(exclude)13_deployment/reports',
    'README.md', 'CONTRACTS.md'
)

git -C $repo archive --format=zip --output=$archive HEAD -- @payload
if ($LASTEXITCODE) { throw 'Could not archive the checked-in school preview source' }
$compilerArgs = @(
    '/nologo', '/target:exe', '/platform:x64', '/codepage:65001',
    '/reference:System.IO.Compression.dll', '/reference:System.IO.Compression.FileSystem.dll',
    "/out:$installer", "/resource:$archive,psynova-source.zip", (Join-Path $PSScriptRoot 'Setup.cs')
)
& $compiler @compilerArgs
if ($LASTEXITCODE) { throw 'Could not compile the Windows setup executable' }
Get-FileHash -Algorithm SHA256 -LiteralPath $installer
