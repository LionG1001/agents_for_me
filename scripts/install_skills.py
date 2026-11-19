#!/usr/bin/env python3
"""Install reviewed repository skills; updates retain a complete rollback copy."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import os
import re
from pathlib import Path
import shutil
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('assets', ROOT / 'skills/publish-agent-assets/scripts/assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def files(path):
    return {p.relative_to(path): p for p in assets.source_files(path)}


def hashes(entries):
    return {str(k): hashlib.sha256(v.read_bytes()).hexdigest() for k, v in entries.items()}


@contextmanager
def installation_lock(path):
    handle = path.open('x', encoding='utf-8')
    try:
        yield
    finally:
        handle.close()
        path.unlink()


def install(destination: Path, update=False, dry_run=False):
    destination = destination.expanduser().absolute()
    assets.no_links(destination)
    destination = destination.resolve()
    if destination == ROOT or ROOT in destination.parents or destination in ROOT.parents:
        raise ValueError('Installation and repository paths must not overlap')
    plan = []
    for source in sorted((ROOT / 'skills').iterdir()):
        if not source.is_dir():
            continue
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', source.name) or len(source.name) > 64:
            raise ValueError(f'Invalid personal skill name: {source.name}')
        if not (source / 'SKILL.md').is_file():
            raise ValueError(f'Missing SKILL.md: {source.name}')
        incoming = files(source)
        target = destination / source.name
        assets.no_links(target)
        if target.exists() and not target.is_dir():
            raise ValueError(f'Installation target is not a directory: {target}')
        current = files(target) if target.exists() else {}
        before = hashes(current)
        wanted = hashes(incoming)
        if target.exists() and all(before.get(k) == v for k, v in wanted.items()):
            print(f'Unchanged: {source.name}')
            continue
        if target.exists() and not update:
            raise ValueError(f'Existing skill differs; review and use --update: {source.name}')
        plan.append((source, incoming, target, current, before, wanted, target.exists()))
    if dry_run:
        for source, _, target, _, _, _, _ in plan:
            print(f'Would install: {source.name} -> {target}')
        return
    destination.mkdir(parents=True, exist_ok=True)
    lock = destination / '.agents-for-me-install.lock'
    with installation_lock(lock):
        backup = destination.parent / 'backups' / ('agents-for-me-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
        assets.no_links(backup)
        for source, incoming, target, current, before, wanted, existed in plan:
            stage = Path(tempfile.mkdtemp(prefix='.agents-for-me-stage-', dir=destination))
            for relative, file in {**current, **incoming}.items():
                output = stage / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, output)
            if hashes(files(stage)) != {**before, **wanted}:
                raise ValueError(f'Staging verification failed: {source.name}')
            assets.no_links(target)
            if (target.exists() != existed) or (target.exists() and hashes(files(target)) != before):
                raise ValueError(f'Installation changed during review: {source.name}')
            previous = backup / source.name
            if target.exists():
                backup.mkdir(parents=True, exist_ok=True)
                target.rename(previous)
            try:
                stage.rename(target)
            except OSError:
                if previous.exists() and not target.exists():
                    previous.rename(target)
                raise
            print(f'Installed: {source.name}')
        if backup.exists():
            print(f'Rollback copy: {backup}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    codex_dir = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    parser.add_argument('--dest', type=Path, default=codex_dir / 'skills')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        assets.validate(argparse.Namespace(repository_root=ROOT))
        install(args.dest, args.update, args.dry_run)
    except (OSError, ValueError) as error:
        print(f'Error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
