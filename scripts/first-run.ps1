<#
.SYNOPSIS
First run of the production stack on a fresh checkout (docs/DEPLOYMENT.md, First run).
.DESCRIPTION
Idempotent (every step skips what already exists): .env from .env.production.example, .env.db with a generated
password, a self-signed certificate if none, docker compose build, postgres up, migrate, the whole stack up, the
first administrator, the serving tables, and the URL to open.
.PARAMETER Dev
Also use docker-compose.dev.yml (laptop ports 8443/8080/5434, a paimana_test database).
.PARAMETER SkipAdmin
Do not run the administrator bootstrap (it refuses anyway once an administrator exists).
.PARAMETER SkipServe
Do not load the serving tables (python -m pipeline.run serve).
#>
[CmdletBinding()]
param([switch]$Dev, [switch]$SkipAdmin, [switch]$SkipServe)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$files = @('-f', 'docker-compose.yml')
if ($Dev) { $files += @('-f', 'docker-compose.dev.yml') }

function Compose {
    & docker compose @files @args
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed" }
}

function New-Password([int]$Length = 32) {
    # alphanumeric (URL-safe in DATABASE_URL); bytes >= 248 are rejected so the modulo has no bias
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $out = New-Object System.Text.StringBuilder
    $buf = New-Object byte[] 1
    while ($out.Length -lt $Length) {
        $rng.GetBytes($buf)
        if ($buf[0] -lt 248) { [void]$out.Append($alphabet[$buf[0] % 62]) }
    }
    $out.ToString()
}

function Write-Lf([string]$Path, [string[]]$Lines) {
    [System.IO.File]::WriteAllText($Path, (($Lines -join "`n") + "`n"), (New-Object System.Text.UTF8Encoding $false))
}

function Read-Setting([string]$Name) {
    $line = Get-Content .env | Where-Object { $_ -like "$Name=*" } | Select-Object -First 1
    if ($line) { return $line.Substring($Name.Length + 1) }
    return ''
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running' }

if (-not (Test-Path .env)) {
    Copy-Item .env.production.example .env
    Write-Host '.env written from .env.production.example: set SERVER_NAME, ALLOWED_ORIGINS, ALLOWED_HOSTS for a real server'
}
if (-not (Test-Path .env.db)) {
    $pw = New-Password
    Write-Lf '.env.db' @(
        '# PAIMANA database credentials, written by scripts/first-run (never commit this file; docs/DEPLOYMENT.md).',
        '# Inside the stack the api reaches postgres:5432 (deploy/api-entrypoint.sh builds DATABASE_URL from these lines).',
        '# POSTGRES_PORT and DATABASE_URL are for tools run on the host against the port docker-compose.dev.yml publishes.',
        'POSTGRES_USER=paimana',
        "POSTGRES_PASSWORD=$pw",
        'POSTGRES_DB=paimana',
        'POSTGRES_PORT=5434',
        "DATABASE_URL=postgresql+psycopg://paimana:$pw@localhost:5434/paimana"
    )
    Write-Host '.env.db written with a generated password'
}
foreach ($d in @('backups', 'dataset\raw\inbox', 'dataset\rag', 'temp')) { New-Item -ItemType Directory -Force $d | Out-Null }
$server = Read-Setting 'SERVER_NAME'
if ($server -eq '' -or $server -eq '_') { $server = 'localhost' }
if (-not (Test-Path 'deploy\certs\fullchain.pem')) {
    & (Join-Path $PSScriptRoot 'gen-dev-cert.ps1') -Name $server
}

Write-Host '== building the images'
Compose build
Write-Host '== starting postgres'
Compose up -d postgres
Write-Host '== migrating the database'
Compose run --rm migrate
Write-Host '== starting the stack'
Compose up -d
if (-not $SkipAdmin) {
    Write-Host '== first administrator (the bootstrap asks for the password; it is never written to a file)'
    $email = Read-Host 'Administrator email'
    $name = Read-Host 'Administrator name'
    # one-off commands go through `run`, not `exec`: run starts the image's entrypoint, which points DATABASE_URL
    # at the stack's postgres (deploy/api-entrypoint.sh); exec would see .env.db's host-side URL
    & docker compose @files run --rm --no-deps api python -m backend.auth.bootstrap --email $email --name $name
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'no administrator was created (one may exist already; --force-reset in the bootstrap resets it)'
    }
}
if (-not $SkipServe) {
    Write-Host '== loading the serving tables'
    Compose run --rm --no-deps api python -m pipeline.run serve
}
if ($Dev) {
    $url = 'https://localhost:8443'
} else {
    $port = Read-Setting 'WEB_HTTPS_PORT'
    if ($port -eq '' -or $port -eq '443') { $url = "https://$server" } else { $url = "https://${server}:$port" }
}
Write-Host "== up: open $url  (docker compose ps / logs -f show the state; docs/DEPLOYMENT.md has the rest)"
