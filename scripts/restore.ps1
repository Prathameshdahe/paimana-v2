<#
.SYNOPSIS
Restore the database from a dump in .\backups.
.DESCRIPTION
The api and backup containers are stopped for the restore, every object in the dump is dropped and recreated
(pg_restore --clean --if-exists), then the containers start again. Asks for a "yes" first.
.PARAMETER File
The dump: backups\paimana-YYYYMMDD-HHMMSS.dump (scripts/backup.ps1 or the backup container wrote it).
#>
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$File)
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
$name = Split-Path $File -Leaf
if (-not (Test-Path (Join-Path 'backups' $name))) { throw "backups\$name not found" }
Write-Host "This replaces the database with backups\$name; the api and backup containers stop while it runs."
$ok = Read-Host 'Type yes to continue'
if ($ok -ne 'yes') { Write-Host 'cancelled'; exit 1 }
& docker compose stop api backup
if ($LASTEXITCODE -ne 0) { throw 'docker compose stop failed' }
$cmd = "pg_restore -U `"`$POSTGRES_USER`" -d `"`$POSTGRES_DB`" --clean --if-exists --no-owner `"/backups/$name`""
& docker compose exec -T postgres sh -c $cmd
$restore = $LASTEXITCODE
& docker compose start api backup
if ($restore -ne 0) { throw 'pg_restore failed (the containers were started again)' }
Write-Host "restored backups\$name"
