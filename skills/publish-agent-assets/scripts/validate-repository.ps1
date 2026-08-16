[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$RepositoryRoot
)

$ErrorActionPreference = "Stop"
$repositoryPath = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$errors = [Collections.Generic.List[string]]::new()

if (-not (Test-Path -LiteralPath (Join-Path $repositoryPath ".git"))) {
    $errors.Add("Not a Git checkout: $repositoryPath")
}

$skillsPath = Join-Path $repositoryPath "skills"
if (-not (Test-Path -LiteralPath $skillsPath -PathType Container)) {
    $errors.Add("Missing skills directory: $skillsPath")
}
else {
    foreach ($skillDirectory in Get-ChildItem -LiteralPath $skillsPath -Directory -Force) {
        $reparsePoints = @(Get-ChildItem -LiteralPath $skillDirectory.FullName -Recurse -Force |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
        if ($reparsePoints.Count -gt 0) {
            $errors.Add("Skill contains symbolic links or reparse points: $($skillDirectory.Name)")
        }

        $skillFile = Join-Path $skillDirectory.FullName "SKILL.md"
        if (-not (Test-Path -LiteralPath $skillFile -PathType Leaf)) {
            $errors.Add("Missing SKILL.md: skills/$($skillDirectory.Name)")
            continue
        }

        $content = Get-Content -LiteralPath $skillFile -Raw
        $frontmatterMatch = [regex]::Match($content, '\A---\r?\n(?<body>.*?)\r?\n---(?:\r?\n|\z)', 'Singleline')
        if (-not $frontmatterMatch.Success) {
            $errors.Add("Invalid YAML frontmatter boundaries: skills/$($skillDirectory.Name)/SKILL.md")
            continue
        }

        $frontmatter = $frontmatterMatch.Groups['body'].Value
        $nameMatch = [regex]::Match($frontmatter, '(?m)^name:\s*["'']?(?<name>[a-z0-9]+(?:-[a-z0-9]+)*)["'']?\s*$')
        $descriptionMatch = [regex]::Match($frontmatter, '(?m)^description:\s*(?<description>.+)$')
        if (-not $nameMatch.Success) {
            $errors.Add("Missing or invalid name: skills/$($skillDirectory.Name)/SKILL.md")
        }
        elseif ($nameMatch.Groups['name'].Value -ne $skillDirectory.Name) {
            $errors.Add("Skill name does not match directory: $($skillDirectory.Name)")
        }
        if (-not $descriptionMatch.Success) {
            $errors.Add("Missing description: skills/$($skillDirectory.Name)/SKILL.md")
        }
        if ($content -match '\[TODO(?:\]|:)') {
            $errors.Add("Unresolved TODO placeholder: skills/$($skillDirectory.Name)/SKILL.md")
        }
    }
}

$textExtensions = @('.md', '.ps1', '.py', '.sh', '.json', '.yaml', '.yml', '.toml', '.txt', '.example')
$textFiles = @(Get-ChildItem -LiteralPath $repositoryPath -File -Recurse -Force |
    Where-Object {
        $_.FullName -notlike "*\.git\*" -and
        $_.Length -le 2MB -and
        $textExtensions -contains $_.Extension.ToLowerInvariant()
    })

$secretPatterns = @(
    '(?i)\bgh[pousr]_[A-Za-z0-9]{20,}\b',
    '(?i)\bgithub_pat_[A-Za-z0-9_]{20,}\b',
    '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    '(?i)authorization\s*[:=].*\btoken\s+[A-Za-z0-9]{12,}'
)
$userProfilePath = [Environment]::GetFolderPath('UserProfile')

foreach ($file in $textFiles) {
    $content = Get-Content -LiteralPath $file.FullName -Raw
    foreach ($pattern in $secretPatterns) {
        if ($content -match $pattern) {
            $relativePath = [IO.Path]::GetRelativePath($repositoryPath, $file.FullName)
            $errors.Add("Possible credential in $relativePath")
            break
        }
    }
    if ($userProfilePath -and $content.IndexOf($userProfilePath, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        $relativePath = [IO.Path]::GetRelativePath($repositoryPath, $file.FullName)
        $errors.Add("Machine-specific user profile path in $relativePath")
    }

    if ($file.Extension -eq '.md') {
        foreach ($linkMatch in [regex]::Matches($content, '\[[^\]]+\]\((?<target>[^)]+)\)')) {
            $target = $linkMatch.Groups['target'].Value.Trim()
            if ($target -match '^(?:https?://|mailto:|#)' -or $target.StartsWith('<')) {
                continue
            }
            $targetPath = ($target -split '#', 2)[0]
            if ([string]::IsNullOrWhiteSpace($targetPath)) {
                continue
            }
            $resolvedTarget = Join-Path $file.DirectoryName ([Uri]::UnescapeDataString($targetPath))
            if (-not (Test-Path -LiteralPath $resolvedTarget)) {
                $relativePath = [IO.Path]::GetRelativePath($repositoryPath, $file.FullName)
                $errors.Add("Broken relative link in ${relativePath}: $target")
            }
        }
    }
}

if ($errors.Count -gt 0) {
    $errors | Sort-Object -Unique | ForEach-Object { Write-Error $_ -ErrorAction Continue }
    exit 1
}

$skillCount = if (Test-Path -LiteralPath $skillsPath) { @(Get-ChildItem -LiteralPath $skillsPath -Directory).Count } else { 0 }
Write-Output "Validation passed: $skillCount skill(s), $($textFiles.Count) text file(s) scanned."
