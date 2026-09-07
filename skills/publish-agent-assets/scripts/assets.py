#!/usr/bin/env python3
"""Portable asset synchronization and repository validation (Python 3.10+)."""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

EXCLUDED = {'.git', '.system', '__pycache__', '.venv', 'venv', 'node_modules',
            '.pytest_cache', '.mypy_cache', '.cache', 'build', 'dist', 'secrets',
            '.DS_Store', 'Thumbs.db'}
SECRET_FILES = {'.env', 'password.txt', 'credentials.json', 'id_rsa', 'id_ed25519'}
SECRET_SUFFIXES = {'.key', '.pem', '.p12', '.pfx'}
PATTERNS = [
    re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'),
    re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    re.compile(r'authorization\s*[:=]\s*[\"\']?(?:bearer|token)\s+[A-Za-z0-9._-]{12,}', re.I),
    re.compile(r'https?://[^\s/]+:[^\s/@]+@', re.I),
    re.compile(r'https://(?:oapi\.dingtalk\.com/robot/send\?access_token|qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key)=[A-Za-z0-9_-]{12,}'),
]


def excluded(path: Path) -> bool:
    return path.name in EXCLUDED or path.suffix in {'.pyc', '.pyo'}


def credential_file(path: Path) -> bool:
    return (path.name in SECRET_FILES or path.suffix.lower() in SECRET_SUFFIXES
            or (path.name.startswith('.env.') and path.name != '.env.example'))


def no_links(path: Path) -> None:
    # Check before resolve(), including existing ancestors and Windows junctions.
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError(f'Refusing symbolic link/reparse point: {part}')


def checkout(path: Path) -> Path:
    no_links(path.absolute())
    root = path.resolve(strict=True)
    result = subprocess.run(['git', '-C', str(root), 'rev-parse', '--show-toplevel'],
                            capture_output=True, text=True)
    if result.returncode or Path(result.stdout.strip()).resolve() != root:
        raise ValueError(f'Not a Git checkout root: {root}')
    return root


def source_files(source: Path):
    no_links(source)
    if source.is_file():
        if credential_file(source):
            raise ValueError(f'Refusing credential file: {source.name}')
        yield source
        return
    for parent, directories, files in os.walk(source, followlinks=False):
        base = Path(parent)
        for name in directories + files:
            no_links(base / name)
        directories[:] = sorted(name for name in directories if not excluded(base / name))
        for name in sorted(files):
            path = base / name
            if credential_file(path):
                raise ValueError(f'Refusing credential file: {path.relative_to(source)}')
            if not excluded(path):
                if not stat.S_ISREG(path.stat().st_mode):
                    raise ValueError(f'Not a regular file: {path}')
                yield path


def sync(args) -> None:
    root = checkout(args.repository_root)
    plan = []
    destinations = set()
    for entry in args.source:
        no_links(entry.absolute())
        source = entry.resolve(strict=True)
        if '.system' in source.parts or ('plugins' in source.parts and 'cache' in source.parts):
            raise ValueError('System skills and plugin caches are not personal assets')
        if args.type == 'skill':
            if not (source.is_dir() and (source / 'SKILL.md').is_file()):
                raise ValueError(f'Skill source must contain SKILL.md: {source}')
            if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', source.name) or len(source.name) > 64:
                raise ValueError(f'Invalid skill directory name: {source.name}')
            destination = root / 'skills' / source.name
        else:
            if not source.is_file() or source.suffix.lower() != '.md':
                raise ValueError('MCP document must be a Markdown file')
            destination = root / 'docs' / 'mcp' / source.name
        no_links(destination)
        if source == destination or source in destination.parents or destination in source.parents:
            raise ValueError('Source and destination overlap')
        if destination in destinations:
            raise ValueError(f'Duplicate destination: {destination}')
        destinations.add(destination)
        if destination.exists() and not args.update:
            raise ValueError(f'Destination exists; review then use --update: {destination}')
        if destination.exists() and destination.is_dir() != source.is_dir():
            raise ValueError(f'Destination type mismatch: {destination}')
        for file in source_files(source):
            target = destination / file.relative_to(source) if source.is_dir() else destination
            no_links(target)
            if any(parent.exists() and not parent.is_dir() for parent in target.parents):
                raise ValueError(f"Destination ancestor is not a directory: {target}")
            if target.exists() and not target.is_file():
                raise ValueError(f'Destination is not a file: {target}')
            plan.append((file, target))
    # Preflight every source and destination before the first write.
    for file, target in plan:
        print(f'{"Would copy" if args.dry_run else "Copy"}: {file} -> {target}')
        if not args.dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    print(f'{len(plan)} file(s); destination-only files retained.')


def validate(args) -> None:
    try:
        import yaml
    except ImportError as exc:
        raise ValueError('Validation requires PyYAML in the selected Python environment') from exc
    root = checkout(args.repository_root)
    errors = []
    skills = root / 'skills'
    no_links(skills)
    if not skills.is_dir():
        raise ValueError('Missing skills directory')
    directories = sorted(p for p in skills.iterdir() if p.is_dir())
    for directory in directories:
        no_links(directory)
        entry = directory / 'SKILL.md'
        if not entry.is_file():
            errors.append(f'Missing SKILL.md: {directory.name}')
            continue
        no_links(entry)
        content = entry.read_text(encoding='utf-8-sig')
        match = re.match(r'\A---\n(.*?)\n---(?:\n|\Z)', content, re.S)
        try:
            front = yaml.safe_load(match[1]) if match else None
            if not isinstance(front, dict):
                raise ValueError('frontmatter must be a mapping')
            name = front.get('name')
            if name != directory.name or not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
                raise ValueError('name must match the kebab-case directory (max 64 characters)')
            description = front.get('description')
            if not isinstance(description, str) or not description.strip():
                raise ValueError('description must be a nonempty string')
        except (ValueError, yaml.YAMLError):
            errors.append(f'Invalid YAML frontmatter: {entry.relative_to(root)}')
        ui = directory / 'agents' / 'openai.yaml'
        if ui.exists():
            no_links(ui)
            try:
                data = yaml.safe_load(ui.read_text(encoding='utf-8-sig'))
                if not isinstance(data, dict) or not isinstance(data.get('interface'), dict):
                    raise ValueError('missing interface')
            except (ValueError, yaml.YAMLError):
                errors.append(f'Invalid UI metadata: {ui.relative_to(root)}')
    count = 0
    for parent, folders, files in os.walk(root, followlinks=False):
        base = Path(parent)
        for name in folders + files:
            if name == '.git' and base == root:
                continue  # A worktree has a .git file, an ordinary checkout a directory.
            no_links(base / name)
            if excluded(base / name) or credential_file(base / name):
                errors.append(f'Excluded or credential artifact: {(base / name).relative_to(root)}')
        folders[:] = [n for n in folders if n != '.git' and not excluded(base / n)]
        for name in files:
            file = base / name
            if name == '.git' and base == root:
                continue
            if not stat.S_ISREG(file.stat().st_mode):
                errors.append(f'Nonregular file: {file.relative_to(root)}')
                continue
            raw = file.read_bytes()
            try:
                content = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                # Binary assets require manual review, and are not silently certified.
                print(f'Manual binary review required: {file.relative_to(root)}')
                errors.append(f'Unreviewed binary asset: {file.relative_to(root)}')
                continue
            count += 1
            rel = file.relative_to(root)
            if any(p.search(content) for p in PATTERNS):
                errors.append(f'Possible credential: {rel}')
            if str(Path.home()) in content:
                errors.append(f'Machine-specific home path: {rel}')
            if file.suffix == '.md':
                if re.search(r'\[TODO(?:\]|:)', content):
                    errors.append(f'Unfinished scaffold: {rel}')
                # Ignore code fences: templates intentionally contain example links.
                prose = re.sub(r'(?ms)^(`{3,}|~{3,}).*?^\1[^\n]*(?:\n|$)', '', content)
                for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', prose):
                    target = target.strip()
                    target = target[1:target.index('>')] if target.startswith('<') and '>' in target else target.split(' "', 1)[0]
                    if urlsplit(target).scheme or target.startswith('#'):
                        continue
                    path = unquote(target.split('#', 1)[0])
                    if path:
                        resolved = (file.parent / path).resolve()
                        if not resolved.is_relative_to(root) or not resolved.exists():
                            errors.append(f'Broken or out-of-repository link: {rel}')
    if not directories:
        errors.append('No skills found')
    if errors:
        raise ValueError('\n'.join(sorted(set(errors))))
    print(f'Validation passed: {len(directories)} skills, {count} UTF-8 files; review diff for other secrets.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('validate')
    check.add_argument('repository_root', type=Path)
    copy = commands.add_parser('sync')
    copy.add_argument('--repository-root', type=Path, required=True)
    copy.add_argument('--type', choices=['skill', 'mcp-doc'], required=True)
    copy.add_argument('--source', type=Path, action='append', required=True)
    copy.add_argument('--update', action='store_true')
    copy.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        (sync if args.command == 'sync' else validate)(args)
    except (ValueError, OSError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
