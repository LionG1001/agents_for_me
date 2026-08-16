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
    throw "未找到中转站配置：$ConfigPath"
}

$config = Get-Content -Raw -LiteralPath $ConfigPath | ConvertFrom-Json
foreach ($name in @('host', 'port', 'module', 'user', 'password_file')) {
    if (-not $config.$name) {
        throw "中转站配置缺少字段 '$name'。"
    }
}
if (-not (Test-Path -LiteralPath $config.password_file -PathType Leaf)) {
    throw '配置中指定的密码文件不存在。'
}
if ($RemotePath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw 'RemotePath 不能包含父目录片段。'
}
if ($RemotePath -match '[\r\n?#]') {
    throw 'RemotePath 不能包含控制字符、查询字符或片段字符。'
}

$rsync = if ($RsyncExecutable) {
    Get-Command -Name $RsyncExecutable -ErrorAction SilentlyContinue
} else {
    Get-Command rsync -ErrorAction SilentlyContinue
}
if (-not $rsync) {
    if ($Action -eq 'check') {
        Write-Output '配置文件和密码文件存在。'
        Write-Output 'Rsync 可执行文件：未找到'
        exit 2
    }
    throw '在 PATH 中未找到 rsync 可执行文件。'
}

$remoteParts = @()
if ($config.base_path) { $remoteParts += $config.base_path.Trim('/\') }
if ($RemotePath) { $remoteParts += $RemotePath.TrimStart('/\') }
$remoteSuffix = ($remoteParts -join '/').Replace('\', '/')
$remoteUri = "rsync://$($config.user)@$($config.host):$($config.port)/$($config.module)"
if ($remoteSuffix) { $remoteUri += "/$remoteSuffix" }

if ($Action -eq 'check') {
    Write-Output '配置文件和密码文件存在。'
    Write-Output "Rsync 可执行文件：$($rsync.Source)"
    exit 0
}

$common = @('--password-file', $config.password_file, '--human-readable')
switch ($Action) {
    'list' {
        & $rsync.Source @common $remoteUri
    }
    'upload' {
        if (-not $LocalPath) { throw '上传操作必须提供 LocalPath。' }
        $resolved = Resolve-Path -LiteralPath $LocalPath -ErrorAction Stop
        $arguments = @('-a', '--itemize-changes', '--partial') + $common
        if (-not $Execute) { $arguments += '--dry-run' }
        $arguments += @('--', $resolved.Path, $remoteUri)
        & $rsync.Source @arguments
    }
    'download' {
        if (-not $LocalPath) { throw '下载操作必须提供 LocalPath。' }
        if (-not (Test-Path -LiteralPath $LocalPath -PathType Container)) {
            throw '下载操作的 LocalPath 必须是已存在的目录。'
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
