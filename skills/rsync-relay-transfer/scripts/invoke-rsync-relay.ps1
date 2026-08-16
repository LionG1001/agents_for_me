[CmdletBinding()]
param(
    [Parameter(Mandatory)] [ValidateSet('check', 'list', 'upload', 'download')] [string] $Action,
    [string] $LocalPath,
    [string] $RemotePath = '',
    [switch] $Execute,
    [string] $ConfigPath = (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.config\rsync-relay-transfer\config.json'),
    [string] $RsyncExecutable
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Relay configuration not found: $ConfigPath"
}

$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
foreach ($name in @('host', 'port', 'module', 'user', 'password_file')) {
    if (-not $config.$name) {
        throw "Relay configuration is missing '$name'."
    }
}
if (-not (Test-Path -LiteralPath $config.password_file -PathType Leaf)) {
    throw 'Configured password file does not exist.'
}
if ($RemotePath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw 'RemotePath must not contain parent-directory segments.'
}
if ($RemotePath -match '[\r\n?#]') {
    throw 'RemotePath must not contain control, query, or fragment characters.'
}

$rsync = if ($RsyncExecutable) {
    Get-Command -Name $RsyncExecutable -ErrorAction SilentlyContinue
} else {
    Get-Command rsync -ErrorAction SilentlyContinue
}
if (-not $rsync) {
    if ($Action -eq 'check') {
        Write-Output 'Configuration and password file are present.'
        Write-Output 'Rsync executable: not found'
        exit 2
    }
    throw 'The rsync executable was not found in PATH.'
}

$remoteParts = @()
if ($config.base_path) { $remoteParts += $config.base_path.Trim('/\') }
if ($RemotePath) { $remoteParts += $RemotePath.TrimStart('/\') }
$remoteSuffix = ($remoteParts -join '/').Replace('\', '/')
$remoteUri = "rsync://$($config.user)@$($config.host):$($config.port)/$($config.module)"
if ($remoteSuffix) { $remoteUri += "/$remoteSuffix" }

if ($Action -eq 'check') {
    Write-Output 'Configuration and password file are present.'
    Write-Output "Rsync executable: $($rsync.Source)"
    exit 0
}

$common = @('--password-file', $config.password_file, '--human-readable')
switch ($Action) {
    'list' {
        & $rsync.Source @common $remoteUri
    }
    'upload' {
        if (-not $LocalPath) { throw 'LocalPath is required for upload.' }
        $resolved = Resolve-Path -LiteralPath $LocalPath -ErrorAction Stop
        $arguments = @('-a', '--itemize-changes', '--partial') + $common
        if (-not $Execute) { $arguments += '--dry-run' }
        $arguments += @('--', $resolved.Path, $remoteUri)
        & $rsync.Source @arguments
    }
    'download' {
        if (-not $LocalPath) { throw 'LocalPath is required for download.' }
        if (-not (Test-Path -LiteralPath $LocalPath -PathType Container)) {
            throw 'Download LocalPath must be an existing directory.'
        }
        $resolved = Resolve-Path -LiteralPath $LocalPath -ErrorAction Stop
        $arguments = @('-a', '--itemize-changes', '--partial') + $common
        if (-not $Execute) { $arguments += '--dry-run' }
        $arguments += @('--', $remoteUri, $resolved.Path)
        & $rsync.Source @arguments
    }
}

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
