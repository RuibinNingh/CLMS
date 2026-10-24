#!/usr/bin/env python3
"""Explicit, snapshot-first removal of one confirmed CLMS legacy data directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
from pathlib import Path

MARKER = '.clms-legacy-data.json'


def reject_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError('symlink path components are forbidden: ' + str(component))


def boundary(root: Path, clms_root: Path) -> tuple[Path, Path]:
    if not root.is_absolute() or not clms_root.is_absolute():
        raise ValueError('both paths must be explicit absolute paths')
    reject_symlink_components(root)
    reject_symlink_components(clms_root)
    root, clms_root = root.resolve(strict=True), clms_root.resolve(strict=True)
    if clms_root.name.casefold() != 'clms' or clms_root in (Path('/'), Path.home()):
        raise ValueError('confirmed CLMS root must be a dedicated directory named CLMS')
    if root == clms_root or clms_root not in root.parents:
        raise ValueError('legacy data must be strictly inside the confirmed CLMS root')
    if any(part.casefold() == 'omrs' for part in root.parts):
        raise ValueError('OMRS boundaries are forbidden')
    marker = root / MARKER
    if marker.is_symlink() or json.loads(marker.read_text()) != {'application': 'CLMS', 'purpose': 'legacy-data'}:
        raise ValueError('operator-created legacy boundary marker is required')
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('symlink or special file in legacy data: ' + str(path))
    return root, clms_root


def inventory(root: Path) -> dict:
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            files.append({'path': str(path.relative_to(root)), 'bytes': path.stat().st_size,
                          'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'root': str(root), 'file_count': len(files), 'total_bytes': sum(item['bytes'] for item in files), 'files': files}


def execute(root: Path, clms_root: Path, snapshot: Path, manifest: dict, confirmed: str) -> dict:
    if confirmed != str(root):
        raise ValueError('--confirm-root must exactly match the canonical legacy root')
    if not snapshot.is_absolute() or snapshot.exists() or snapshot.parent.is_symlink():
        raise ValueError('snapshot must be a new absolute file in a non-symlink directory')
    reject_symlink_components(snapshot)
    parent = snapshot.parent.resolve(strict=True)
    if parent == clms_root or clms_root in parent.parents:
        raise ValueError('snapshot must be outside CLMS root')
    boundary(root, clms_root)
    current = inventory(root)
    if current != manifest:
        raise ValueError('inventory changed since dry-run; regenerate and review the manifest')
    fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            with tarfile.open(fileobj=output, mode='w:gz') as archive:
                archive.add(root, arcname='legacy-data', recursive=True)
            output.flush()
            os.fsync(output.fileno())
        with tarfile.open(snapshot, 'r:gz') as archive:
            for item in manifest['files']:
                stored = archive.extractfile('legacy-data/' + item['path'])
                if stored is None or hashlib.sha256(stored.read()).hexdigest() != item['sha256']:
                    raise ValueError('snapshot verification failed')
        boundary(root, clms_root)
        if inventory(root) != manifest:
            raise ValueError('legacy data changed during snapshot; nothing deleted')
        shutil.rmtree(root)
    except Exception:
        # Keep even a partial private snapshot for operator investigation.
        raise
    return {'removed_root': str(root), 'snapshot': str(snapshot), 'snapshot_sha256': hashlib.sha256(snapshot.read_bytes()).hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--clms-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--snapshot', type=Path)
    parser.add_argument('--confirm-root')
    args = parser.parse_args()
    try:
        root, clms_root = boundary(args.root, args.clms_root)
        if args.execute:
            if args.snapshot is None or args.confirm_root is None:
                parser.error('--execute requires --snapshot and --confirm-root')
            result = execute(root, clms_root, args.snapshot, json.loads(args.manifest.read_text()), args.confirm_root)
        else:
            result = inventory(root)
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'mode': 'execute' if args.execute else 'dry-run', **result}, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
