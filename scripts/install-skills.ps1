[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$Destination,
    [switch]$Update,
    [switch]$DryRun,
    [string]$PythonExecutable = 'python'
)
$ErrorActionPreference = 'Stop'
$arguments = @('-X', 'utf8', (Join-Path $PSScriptRoot 'install_skills.py'))
if ($Destination) { $arguments += @('--dest', $Destination) }
if ($Update) { $arguments += '--update' }
if ($DryRun -or $WhatIfPreference) { $arguments += '--dry-run' }
if ($DryRun -or $WhatIfPreference -or $PSCmdlet.ShouldProcess('Codex user skills', 'Install repository skills with rollback copies')) {
    & $PythonExecutable @arguments
    if ($LASTEXITCODE -ne 0) { throw "Skill installation failed (exit $LASTEXITCODE)." }
}
