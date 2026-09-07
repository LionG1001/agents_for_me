[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [string]$PythonExecutable = 'python'
)
$ErrorActionPreference = 'Stop'
& $PythonExecutable (Join-Path $PSScriptRoot 'assets.py') validate $RepositoryRoot
if ($LASTEXITCODE -ne 0) { throw "Repository validation failed (exit $LASTEXITCODE)." }
