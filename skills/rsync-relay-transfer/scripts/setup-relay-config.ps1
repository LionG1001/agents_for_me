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
        throw 'Host, module, and user values must not contain whitespace or URI delimiter characters.'
    }
}

if ($BasePath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw 'BasePath must not contain parent-directory segments.'
}

if (-not $Password) {
    $Password = Read-Host 'Rsync relay password' -AsSecureString
}

New-Item -ItemType Directory -Force -Path $ConfigDirectory | Out-Null
$passwordFile = Join-Path $ConfigDirectory 'password.txt'
$configFile = Join-Path $ConfigDirectory 'config.json'

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    if ([string]::IsNullOrEmpty($plainPassword)) {
        throw 'Password must not be empty.'
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

Write-Output "Configuration written to $configFile"
Write-Output 'Password stored in a user-only ACL file.'
