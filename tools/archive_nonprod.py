#!/usr/bin/env python3
"""
Archive non-production files into archive/YYYYMMDD while preserving relative paths.

Usage:
  python tools/archive_nonprod.py --dry-run
  python tools/archive_nonprod.py

This script implements conservative rules to move dev-only folders/files into an
archive directory to keep the main repo focused on production code.
"""
from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


ROOT = Path(__file__).resolve().parents[1]


DEFAULT_PATTERNS = [
    "notebooks",
    "experiments",
    "prototypes",
    "scripts/legacy",
    "docs/drafts",
    "tmp",
]


def gather_candidates(root: Path) -> List[Path]:
    candidates: List[Path] = []

    # explicit directories
    for pat in DEFAULT_PATTERNS:
        p = root.joinpath(pat)
        if p.exists():
            candidates.append(p)

    # scripts/legacy handled above; additionally find ps1 files and top-level dev files
    for p in root.rglob('*.ps1'):
        # skip if under archive already
        if 'archive' in p.parts:
            continue
        candidates.append(p)

    # tmp/ and other matches already covered by DEFAULT_PATTERNS; ensure uniqueness
    uniq = []
    for p in candidates:
        if p not in uniq:
            uniq.append(p)
    return uniq


def is_protected(path: Path, root: Path) -> bool:
    """Return True if path should NOT be archived per spec."""
    # Protected list (not moved)
    protected = [
        root / 'tools' / 'auroractl.py',
        root / 'tools' / 'run_all.py',
    ]
    # Protected directories/patterns
    protected_dirs = [
        'core',
        'app',
        'configs',
        'tests',
        'logs',
        'artifacts',
    ]

    for p in protected:
        try:
            if path.samefile(p):
                return True
        except Exception:
            pass

    for d in protected_dirs:
        if d in path.parts:
            return True

    # keep top-level Makefile and README.md
    if path.name in ('Makefile', 'README.md'):
        return True

    return False


def archive_items(items: List[Path], root: Path, dry_run: bool = True) -> List[Tuple[Path, Path]]:
    """Move items into archive/YYYYMMDD and return list of (src, dest).

    Preserves relative paths under archive/YYYYMMDD/<relative path>
    """
    moved: List[Tuple[Path, Path]] = []
    date = datetime.utcnow().strftime('%Y%m%d')
    base = root / 'archive' / date

    for src in items:
        if is_protected(src, root):
            print(f"[SKIP] protected: {src}")
            continue

        # Compute destination path
        try:
            rel = src.relative_to(root)
        except Exception:
            # fallback to name only
            rel = Path(src.name)

        dest = base / rel

        if dry_run:
            print(f"[DRY] {src} -> {dest}")
            moved.append((src, dest))
            continue

        # create destination parent
        dest.parent.mkdir(parents=True, exist_ok=True)

        # move file or directory
        try:
            shutil.move(str(src), str(dest))
            moved.append((src, dest))
            print(f"[MOVED] {src} -> {dest}")
        except Exception as e:
            print(f"[ERROR] moving {src} -> {dest}: {e}")

    # write ARCHIVE_INDEX.md if not dry run
    if not dry_run and moved:
        idx = base / 'ARCHIVE_INDEX.md'
        with idx.open('w', encoding='utf-8') as fh:
            fh.write('# Archive index\n\n')
            fh.write('| From | To |\n')
            fh.write('|---|---:|\n')
            for s, d in moved:
                fh.write(f'| {s.as_posix()} | {d.as_posix()} |\n')
        print(f"[INDEX] Written {idx}")

    return moved


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Archive non-production files.')
    parser.add_argument('--dry-run', action='store_true', help='List files to be archived without moving')
    parser.add_argument('--root', type=str, default=str(ROOT), help='Repository root')
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"Root not found: {root}")
        return 2

    items = gather_candidates(root)
    if not items:
        print('No candidate items found.')
        return 0

    # Filter out protected
    items = [p for p in items if not is_protected(p, root)]

    if args.dry_run:
        print('DRY RUN - items to archive:')
    else:
        print('ARCHIVE - moving items:')

    moved = archive_items(items, root, dry_run=args.dry_run)

    if args.dry_run:
        print(f"Total candidates: {len(items)}")
    else:
        print(f"Archived {len(moved)} items to archive/{datetime.utcnow().strftime('%Y%m%d')}")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
