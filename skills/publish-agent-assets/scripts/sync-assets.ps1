[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)][ValidateSet('Skill', 'McpDoc')][string]$Type,
    [Parameter(Mandatory)][string[]]$Source,
    [Parameter(Mandatory)][string]$RepositoryRoot,
    [switch]$Update,
    [switch]$DryRun,
    [string]$PythonExecutable = 'python'
)
$ErrorActionPreference = 'Stop'
$assetType = if ($Type -eq 'Skill') { 'skill' } else { 'mcp-doc' }
$arguments = @((Join-Path $PSScriptRoot 'assets.py'), 'sync', '--type', $assetType, '--repository-root', $RepositoryRoot)
foreach ($item in $Source) { $arguments += @('--source', $item) }
if ($Update) { $arguments += '--update' }
if ($DryRun -or $WhatIfPreference) { $arguments += '--dry-run' }
if ($DryRun -or $WhatIfPreference -or $PSCmdlet.ShouldProcess($RepositoryRoot, 'Synchronize assets')) {
    & $PythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) { throw "Asset synchronization failed (exit $LASTEXITCODE)." }
}
