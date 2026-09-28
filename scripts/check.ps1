<#
.SYNOPSIS
Every check the build must pass: pytest, then the frontend lint, typecheck and build.
.DESCRIPTION
The same order as .github/workflows/check.yml. Stops at the first failure. Run with the venv active.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
function Step([string]$Name, [scriptblock]$Run) {
    Write-Host "== $Name"
    & $Run
    if ($LASTEXITCODE -ne 0) { throw "$Name failed" }
}
Step 'pytest' { python -m pytest -q }
Set-Location frontend
Step 'lint' { npm run lint }
Step 'typecheck' { npm run typecheck }
Step 'build' { npm run build }
Write-Host 'all checks passed'
