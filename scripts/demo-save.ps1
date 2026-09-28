<#
.SYNOPSIS
The demo stack's three images in one file, for a machine without internet: .\paimana-demo-images.tar.gz.
.DESCRIPTION
Builds the demo images (docker-compose.demo.yml), pulls postgres, saves the three images and gzips them (the file is
gitignored). On the other machine, next to a copy of the repository:
    docker load -i paimana-demo-images.tar.gz
    docker compose -f docker-compose.demo.yml up -d
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
& docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker is not running' }
& docker compose -f docker-compose.demo.yml build
if ($LASTEXITCODE -ne 0) { throw 'build failed' }
& docker compose -f docker-compose.demo.yml pull postgres
if ($LASTEXITCODE -ne 0) { throw 'pull failed' }
$tar = Join-Path (Get-Location) 'paimana-demo-images.tar'
& docker save -o $tar paimana-demo-api paimana-demo-web pgvector/pgvector:pg16
if ($LASTEXITCODE -ne 0) { throw 'save failed' }
$src = [System.IO.File]::OpenRead($tar)
$dst = [System.IO.File]::Create("$tar.gz")
$gz = New-Object System.IO.Compression.GZipStream($dst, [System.IO.Compression.CompressionLevel]::Optimal)
try { $src.CopyTo($gz) } finally { $gz.Dispose(); $dst.Dispose(); $src.Dispose() }
Remove-Item $tar
$mb = [math]::Round((Get-Item "$tar.gz").Length / 1MB)
Write-Host "wrote paimana-demo-images.tar.gz ($mb MB)"
