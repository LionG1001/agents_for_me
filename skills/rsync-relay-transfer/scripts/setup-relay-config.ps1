[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $RelayHost,
    [Parameter(Mandatory)] [ValidateRange(1, 65535)] [int] $Port,
    [Parameter(Mandatory)] [string] $Module,
    [Parameter(Mandatory)] [string] $User,
    [string] $BasePath = '',
    [string] $ConfigDirectory = (Join-Path ([Environment]::GetFolderPath('UserProfile')) '.config\rsync-relay-transfer'),
    [Security.SecureString] $Password
)

$ErrorActionPreference = 'Stop'

foreach ($value in @($RelayHost, $Module, $User)) {
    if ($value -match '[\s/@:]') {
        throw '主机、模块和用户名不能包含空白字符或 URI 分隔符。'
    }
}

if ($BasePath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw 'BasePath 不能包含父目录片段。'
}

if (-not $Password) {
    $Password = Read-Host '请输入 rsync 中转站密码' -AsSecureString
}

New-Item -ItemType Directory -Force -Path $ConfigDirectory | Out-Null
$passwordFile = Join-Path $ConfigDirectory 'password.txt'
$configFile = Join-Path $ConfigDirectory 'config.json'

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrEmpty($plainPassword)) {
        throw '密码不能为空。'
    }
    [IO.File]::WriteAllText($passwordFile, $plainPassword + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}
finally {
    if ($bstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainPassword = $null
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$acl = New-Object Security.AccessControl.FileSecurity
$acl.SetAccessRuleProtection($true, $false)
$rule = New-Object Security.AccessControl.FileSystemAccessRule($identity, 'FullControl', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $passwordFile -AclObject $acl

$config = [ordered]@{
    host = $RelayHost
    port = $Port
    module = $Module
    user = $User
    base_path = $BasePath.Trim('/\')
    password_file = $passwordFile
}
[IO.File]::WriteAllText($configFile, ($config | ConvertTo-Json) + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))

Write-Output "配置已写入：$configFile"
Write-Output '密码已保存到仅当前用户可访问的 ACL 文件。'
