#!/usr/bin/env bash
set -euo pipefail

if (($# != 1)); then
  printf 'Usage: validate-repository.sh REPOSITORY_ROOT\n' >&2
  exit 2
fi

repository_root=$(realpath "$1")
python3 - "$repository_root" <<'PY'
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

root = Path(sys.argv[1])
errors: set[str] = set()
if not (root / ".git").is_dir():
    errors.add(f"Not a Git checkout: {root}")

skills = root / "skills"
if not skills.is_dir():
    errors.add(f"Missing skills directory: {skills}")
else:
    for directory in sorted(path for path in skills.iterdir() if path.is_dir()):
        if any(path.is_symlink() for path in directory.rglob("*")):
            errors.add(f"Skill contains symbolic links: {directory.name}")
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            errors.add(f"Missing SKILL.md: skills/{directory.name}")
            continue
        content = skill_file.read_text(encoding="utf-8")
        match = re.match(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", content, re.S)
        if not match:
            errors.add(f"Invalid YAML frontmatter boundaries: skills/{directory.name}/SKILL.md")
            continue
        frontmatter = match.group("body")
        name_match = re.search(r'^name:\s*["\']?([a-z0-9]+(?:-[a-z0-9]+)*)["\']?\s*$', frontmatter, re.M)
        if not name_match:
            errors.add(f"Missing or invalid name: skills/{directory.name}/SKILL.md")
        elif name_match.group(1) != directory.name:
            errors.add(f"Skill name does not match directory: {directory.name}")
        if not re.search(r"^description:\s*.+$", frontmatter, re.M):
            errors.add(f"Missing description: skills/{directory.name}/SKILL.md")
        if re.search(r"\[TODO(?:\]|:)", content):
            errors.add(f"Unresolved TODO placeholder: skills/{directory.name}/SKILL.md")

extensions = {".md", ".ps1", ".py", ".sh", ".json", ".yaml", ".yml", ".toml", ".txt", ".example"}
secret_patterns = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b", re.I),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b", re.I),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"authorization\s*[:=].*\btoken\s+[A-Za-z0-9]{12,}", re.I),
]
text_files: list[Path] = []
home = str(Path.home())
for file in root.rglob("*"):
    if not file.is_file() or ".git" in file.parts or file.stat().st_size > 2 * 1024 * 1024 or file.suffix.lower() not in extensions:
        continue
    text_files.append(file)
    try:
        content = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        errors.add(f"Text file is not valid UTF-8: {file.relative_to(root)}")
        continue
    relative = file.relative_to(root)
    if any(pattern.search(content) for pattern in secret_patterns):
        errors.add(f"Possible credential in {relative}")
    if home and home in content:
        errors.add(f"Machine-specific user profile path in {relative}")
    if file.suffix.lower() == ".md":
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            target = target.strip()
            if re.match(r"^(?:https?://|mailto:|#)", target) or target.startswith("<"):
                continue
            target_path = target.split("#", 1)[0]
            if target_path and not (file.parent / unquote(target_path)).exists():
                errors.add(f"Broken relative link in {relative}: {target}")

if errors:
    for error in sorted(errors):
        print(f"Error: {error}", file=sys.stderr)
    raise SystemExit(1)
print(f"Validation passed: {sum(1 for p in skills.iterdir() if p.is_dir()) if skills.is_dir() else 0} skill(s), {len(text_files)} text file(s) scanned.")
PY
