<#
.SYNOPSIS
A database dump now: pg_dump -Fc into .\backups\paimana-<UTC stamp>.dump.
.DESCRIPTION
Runs the backup container's script (deploy/backup.sh once), so it needs no client tools on the host. The daily
dump and the retention are the backup container's job (docker-compose.yml). Restore with scripts/restore.ps1.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
New-Item -ItemType Directory -Force 'backups' | Out-Null
& docker compose run --rm backup once
if ($LASTEXITCODE -ne 0) { throw 'backup failed' }
