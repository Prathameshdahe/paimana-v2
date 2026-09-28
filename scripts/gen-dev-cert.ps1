<#
.SYNOPSIS
Self-signed TLS certificate for a laptop or LAN demo: deploy/certs/fullchain.pem and privkey.pem.
.DESCRIPTION
CN and subject alternative names from -Name (default localhost; localhost and 127.0.0.1 are always included).
Uses openssl from PATH or from Git for Windows, else the one inside the pgvector/pgvector:pg16 image through
Docker. Browsers warn once about it; a real server needs a CA certificate (docs/DEPLOYMENT.md, Real server).
.PARAMETER Name
The host name to certify.
.PARAMETER Force
Replace an existing pair.
#>
[CmdletBinding()]
param([string]$Name = 'localhost', [switch]$Force)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$dir = Join-Path $root 'deploy\certs'
New-Item -ItemType Directory -Force $dir | Out-Null
$full = Join-Path $dir 'fullchain.pem'
$key = Join-Path $dir 'privkey.pem'
if ((Test-Path $full) -and (Test-Path $key) -and -not $Force) {
    Write-Host 'deploy/certs already has a certificate (-Force to replace it)'
    exit 0
}
$san = 'subjectAltName=DNS:localhost,IP:127.0.0.1'
if ($Name -ne 'localhost') { $san = "subjectAltName=DNS:$Name,DNS:localhost,IP:127.0.0.1" }
$req = @('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '825', '-subj', "/CN=$Name", '-addext', $san)
$openssl = $null
$cmd = Get-Command openssl -ErrorAction SilentlyContinue
if ($cmd) { $openssl = $cmd.Source }
if (-not $openssl) {
    foreach ($p in @("$env:ProgramFiles\Git\usr\bin\openssl.exe", "$env:ProgramFiles\Git\mingw64\bin\openssl.exe")) {
        if (Test-Path $p) { $openssl = $p; break }
    }
}
# openssl reports key-generation progress on stderr; Windows PowerShell would treat that as an error under 'Stop'
$ErrorActionPreference = 'Continue'
if ($openssl) {
    & $openssl @req -keyout $key -out $full 2>&1 | Out-Null
} else {
    Write-Host 'openssl not found; using the one in the pgvector/pgvector:pg16 image'
    & docker run --rm -v "${dir}:/certs" pgvector/pgvector:pg16 openssl @req -keyout /certs/privkey.pem -out /certs/fullchain.pem 2>&1 | Out-Null
}
$ErrorActionPreference = 'Stop'
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $full) -or -not (Test-Path $key)) { throw 'openssl failed' }
Write-Host "wrote deploy/certs/fullchain.pem and privkey.pem for $Name (self-signed, 825 days)"
