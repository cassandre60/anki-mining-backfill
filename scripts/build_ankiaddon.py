#!/usr/bin/env python3
"""Build a distributable .ankiaddon archive from mining_fixer/.

Usage:
    python3 scripts/build_ankiaddon.py               # → dist/mining_fixer-<version>.ankiaddon
    python3 scripts/build_ankiaddon.py -o out.ankiaddon

The archive is a zip whose root contains manifest.json and __init__.py —
the layout Anki expects for add-on packages.  Dev artefacts (meta.json,
user_files/, __pycache__/, *.pyc) are excluded.

Read-only: touches nothing on disk except the output file and its parent
directory.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent.parent / "mining_fixer"

EXCLUDE_NAMES = {"meta.json", "__pycache__", "user_files"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def _should_include(rel: Path) -> bool:
    """Return True if *rel* (relative to ADDON_DIR) belongs in the archive."""
    for part in rel.parts:
        if part in EXCLUDE_NAMES or part.startswith("."):
            return False
    return rel.suffix not in EXCLUDE_SUFFIXES


def addon_version() -> str:
    """Read the human_version from manifest.json."""
    manifest = ADDON_DIR / "manifest.json"
    with manifest.open() as f:
        data = json.load(f)
    return data["human_version"]


def build(dest: Path) -> Path:
    """Create the .ankiaddon zip at *dest* and return the resolved path."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    sources: list[Path] = sorted(
        p for p in ADDON_DIR.rglob("*") if p.is_file() and _should_include(p.relative_to(ADDON_DIR))
    )
    if not sources:
        print("error: no source files found in", ADDON_DIR, file=sys.stderr)
        sys.exit(1)

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for src in sources:
            arcname = str(src.relative_to(ADDON_DIR))
            zf.write(src, arcname)

    return dest.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a .ankiaddon archive.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output path (default: dist/mining_fixer-<version>.ankiaddon)",
    )
    args = parser.parse_args()

    version = addon_version()
    dest: Path = args.output or (Path("dist") / f"mining_fixer-{version}.ankiaddon")

    result = build(dest)
    print(f"Built {result} ({result.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
