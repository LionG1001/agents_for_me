[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidateSet("Skill", "McpDoc")]
    [string]$Type,

    [Parameter(Mandatory)]
    [string[]]$Source,

    [Parameter(Mandatory)]
    [string]$RepositoryRoot,

    [switch]$Update
)

$ErrorActionPreference = "Stop"

$repositoryPath = (Resolve-Path -LiteralPath $RepositoryRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $repositoryPath ".git"))) {
    throw "RepositoryRoot is not a Git checkout: $repositoryPath"
}

foreach ($sourceItem in $Source) {
    $sourcePath = (Resolve-Path -LiteralPath $sourceItem).Path
    $reparsePoints = @(Get-ChildItem -LiteralPath $sourcePath -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    if ($reparsePoints.Count -gt 0) {
        throw "Refusing to copy a source containing symbolic links or reparse points: $sourcePath"
    }

    if ($Type -eq "Skill") {
        if (-not (Test-Path -LiteralPath (Join-Path $sourcePath "SKILL.md") -PathType Leaf)) {
            throw "Skill source does not contain SKILL.md: $sourcePath"
        }

        $assetName = Split-Path -Leaf $sourcePath
        if ($assetName -notmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$') {
            throw "Skill directory must use lowercase kebab-case: $assetName"
        }
        $destinationPath = Join-Path $repositoryPath ("skills\" + $assetName)
    }
    else {
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf) -or
            [IO.Path]::GetExtension($sourcePath) -ne ".md") {
            throw "MCP document must be a Markdown file: $sourcePath"
        }
        $assetName = Split-Path -Leaf $sourcePath
        $destinationPath = Join-Path $repositoryPath ("docs\mcp\" + $assetName)
    }

    if ([IO.Path]::GetFullPath($sourcePath) -eq [IO.Path]::GetFullPath($destinationPath)) {
        throw "Source and destination are the same path: $sourcePath"
    }

    $destinationExists = Test-Path -LiteralPath $destinationPath
    if ($destinationExists -and -not $Update) {
        throw "Destination already exists. Review it, then rerun with -Update: $destinationPath"
    }

    if ($PSCmdlet.ShouldProcess($destinationPath, "Synchronize $Type from $sourcePath")) {
        if ($Type -eq "Skill") {
            if (-not $destinationExists) {
                New-Item -ItemType Directory -Path $destinationPath -Force | Out-Null
            }
            Get-ChildItem -LiteralPath $sourcePath -Force |
                Copy-Item -Destination $destinationPath -Recurse -Force
        }
        else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $destinationPath) -Force | Out-Null
            Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
        }
        Write-Output "Synchronized $Type '$assetName' to '$destinationPath'."
    }
}
