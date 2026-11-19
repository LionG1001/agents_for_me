[CmdletBinding()]
param(
    [ValidateSet('siyuan', 'atlassian', 'all')][string]$Service = 'all',
    [string]$CodexDirectory = $(if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path ([Environment]::GetFolderPath('UserProfile')) '.codex' }),
    [string]$PythonExecutable = 'python'
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
$services = if ($Service -eq 'all') { @('siyuan', 'atlassian') } else { @($Service) }
foreach ($name in $services) {
    $directory = Join-Path $CodexDirectory "mcp\$name"
    # Reject reparse points in every existing ancestor before creating files.
    $cursor = [IO.Path]::GetFullPath($directory)
    while ($cursor) {
        if ((Test-Path -LiteralPath $cursor) -and ((Get-Item -LiteralPath $cursor).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Refusing reparse-point installation path.' }
        $cursor = Split-Path $cursor -Parent
    }
    New-Item -ItemType Directory -Force -Path $directory | Out-Null
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true, $false)
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($identity, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
    # Set only the modified DACL; Set-Acl may request unavailable SACL privileges.
    if ($PSVersionTable.PSEdition -eq 'Core') {
        [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($directory), $acl)
    } else {
        [IO.DirectoryInfo]::new($directory).SetAccessControl($acl)
    }
    $venv = Join-Path $directory 'venv'
    $python = Join-Path $venv 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        if (Test-Path -LiteralPath $venv) { throw 'Existing incomplete virtual environment; inspect before retrying.' }
        & $PythonExecutable -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    if ($name -eq 'siyuan') {
        foreach ($file in @('bridge.py', 'check_connection.py', 'requirements.txt')) {
            $target = Join-Path $directory $file
            $source = Join-Path $repoRoot "docs\mcp\siyuan\$file"
            if ((Test-Path -LiteralPath $target) -and ((Get-FileHash -LiteralPath $source).Hash -ne (Get-FileHash -LiteralPath $target).Hash)) {
                Copy-Item -LiteralPath $target -Destination ($target + '.backup-' + [guid]::NewGuid().ToString('N'))
            }
            Copy-Item -LiteralPath $source -Destination $target -Force
        }
        & $python -m pip install --disable-pip-version-check --timeout 30 --retries 2 -r (Join-Path $directory 'requirements.txt')
    } else {
        & $python -m pip install --disable-pip-version-check --timeout 30 --retries 2 'mcp-atlassian==0.23.1'
    }
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed: $name" }
    Write-Output "Prepared $name at $directory; configure the verified endpoint and credential references separately."
}
